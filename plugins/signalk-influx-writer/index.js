const { InfluxDB, Point } = require('@influxdata/influxdb-client')

const DEFAULT_EXCLUDES = ['design.', 'notifications.', 'resources.']

// Sources without an RTC (notably the ESP32-NMEA2000 gateway and our sim)
// emit deltas with a sequence-number time field that decodes to 2010-01-01.
// Substitute wall-clock receive time when the reported timestamp is more
// than this far from now in either direction. Within the window we trust
// the source (e.g. GPS-derived timestamps).
const TS_DRIFT_TOLERANCE_MS = 24 * 60 * 60 * 1000  // 24 h

module.exports = (app) => {
  let writeApi = null
  let unsubscribes = []
  let stats = { written: 0, skipped: 0, lastFlushAt: null }
  let statsTimer = null

  const plugin = {
    id: 'signalk-influx-writer',
    name: 'Signal K → InfluxDB v2 writer',
    description:
      'Streams Signal K deltas to InfluxDB v2. Each path becomes a measurement; ' +
      'numeric → float field "value", boolean → int field "value", short string → "value_str", ' +
      'navigation.position → float fields latitude/longitude (and altitude if present). ' +
      '$source and context attached as tags.',

    schema: {
      type: 'object',
      required: ['url', 'token', 'org', 'bucket'],
      properties: {
        url: {
          type: 'string',
          title: 'InfluxDB URL',
          default: 'http://influxdb:8086'
        },
        token: {
          type: 'string',
          title: 'Auth token (admin or write-scoped)',
          default: ''
        },
        org: {
          type: 'string',
          title: 'Organisation',
          default: 'boat-data'
        },
        bucket: {
          type: 'string',
          title: 'Bucket',
          default: 'signalk'
        }
      }
    },

    start: (settings) => {
      app.setPluginStatus('starting')

      try {
        const client = new InfluxDB({ url: settings.url, token: settings.token })
        writeApi = client.getWriteApi(settings.org, settings.bucket, 'ms', {
          batchSize: 1000,
          flushInterval: 5000,
          maxRetries: 3
        })
      } catch (err) {
        app.setPluginError(`InfluxDB init failed: ${err.message}`)
        return
      }

      const handleDelta = (delta) => {
        if (!delta || !Array.isArray(delta.updates)) return
        const context = delta.context || 'vessels.self'

        for (const update of delta.updates) {
          if (!Array.isArray(update.values)) continue
          const source = update.$source || 'unknown'
          const now = Date.now()
          const reported = update.timestamp ? new Date(update.timestamp).getTime() : NaN
          const ts = Number.isFinite(reported) && Math.abs(now - reported) <= TS_DRIFT_TOLERANCE_MS
            ? reported
            : now

          for (const v of update.values) {
            const path = v && v.path
            if (!path) continue
            if (DEFAULT_EXCLUDES.some((p) => path.startsWith(p))) {
              stats.skipped++
              continue
            }
            const point = toPoint(path, v.value, source, context, ts)
            if (point) {
              writeApi.writePoint(point)
              stats.written++
            } else {
              stats.skipped++
            }
          }
        }
      }

      app.signalk.on('delta', handleDelta)
      unsubscribes.push(() => app.signalk.removeListener('delta', handleDelta))

      statsTimer = setInterval(() => {
        writeApi
          .flush()
          .then(() => {
            stats.lastFlushAt = new Date().toISOString().replace(/\..*/, 'Z')
          })
          .catch((err) => app.error(`flush: ${err.message}`))
        app.setPluginStatus(
          `wrote=${stats.written} skipped=${stats.skipped} lastFlush=${stats.lastFlushAt || 'pending'}`
        )
      }, 5000)

      app.setPluginStatus(`Connected ${settings.url} org=${settings.org} bucket=${settings.bucket}`)
      app.debug(`InfluxDB writer initialised: ${settings.url} ${settings.org}/${settings.bucket}`)
    },

    stop: () => {
      if (statsTimer) clearInterval(statsTimer)
      statsTimer = null
      unsubscribes.forEach((u) => {
        try {
          u()
        } catch (_) {}
      })
      unsubscribes = []
      if (writeApi) {
        const w = writeApi
        writeApi = null
        w.close().catch((err) => app.error(`close: ${err.message}`))
      }
    }
  }

  function toPoint(path, value, source, context, ts) {
    if (value === null || value === undefined) return null

    if (
      path === 'navigation.position' &&
      typeof value === 'object' &&
      typeof value.latitude === 'number' &&
      typeof value.longitude === 'number'
    ) {
      const p = new Point('navigation.position')
        .tag('source', source)
        .tag('context', context)
        .floatField('latitude', value.latitude)
        .floatField('longitude', value.longitude)
        .timestamp(ts)
      if (typeof value.altitude === 'number') p.floatField('altitude', value.altitude)
      return p
    }

    if (typeof value === 'number' && Number.isFinite(value)) {
      return new Point(path)
        .tag('source', source)
        .tag('context', context)
        .floatField('value', value)
        .timestamp(ts)
    }

    if (typeof value === 'boolean') {
      return new Point(path)
        .tag('source', source)
        .tag('context', context)
        .intField('value', value ? 1 : 0)
        .timestamp(ts)
    }

    if (typeof value === 'string' && value.length > 0 && value.length <= 256) {
      return new Point(path)
        .tag('source', source)
        .tag('context', context)
        .stringField('value_str', value)
        .timestamp(ts)
    }

    return null
  }

  return plugin
}
