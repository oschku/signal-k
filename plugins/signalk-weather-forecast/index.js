/**
 * signalk-weather-forecast
 *
 * Pulls a 7-day hourly weather forecast from Open-Meteo (free, no API key)
 * for the boat's current position and writes each forecast point to InfluxDB
 * as measurement `weather.forecast` with SI-unit fields. Designed to be
 * combined with `solunar.forecast` in a Grafana dashboard.
 *
 * Open-Meteo docs: https://open-meteo.com/en/docs
 *
 * Fields written (all SI):
 *   temp        Kelvin
 *   windSpeed   m/s   (10 m above surface)
 *   windGust    m/s
 *   windDir     rad   (true, mathematical convention is irrelevant — same as
 *                       Signal K env.wind.directionTrue)
 *   cloudCover  ratio 0..1
 *   precip      mm    (per hour bucket)
 *   pressure    Pa    (surface pressure)
 */

const { InfluxDB, Point } = require("@influxdata/influxdb-client");

const FORECAST_REFRESH_MS = 30 * 60 * 1000;          // every 30 minutes
const POSITION_MOVE_KM = 25;                          // refetch on big move

const OPEN_METEO_URL = "https://api.open-meteo.com/v1/forecast";
const HOURLY_VARS = [
  "temperature_2m",
  "wind_speed_10m",
  "wind_gusts_10m",
  "wind_direction_10m",
  "cloud_cover",
  "precipitation",
  "surface_pressure",
];

module.exports = function (app) {
  const plugin = {};
  plugin.id = "signalk-weather-forecast";
  plugin.name = "Weather forecast (Open-Meteo → InfluxDB)";
  plugin.description =
    "Writes a 7-day hourly weather forecast (wind, clouds, temp, precip, " +
    "pressure) for the current position to InfluxDB. Combine with " +
    "solunar.forecast in Grafana for a fishing-conditions dashboard.";

  plugin.schema = {
    type: "object",
    required: ["influxUrl", "influxToken"],
    properties: {
      positionPath: {
        type: "string",
        title: "Position path",
        default: "navigation.position",
      },
      defaultLatitude: {
        type: "number",
        title: "Fallback latitude (°)",
        default: 60.11,
      },
      defaultLongitude: {
        type: "number",
        title: "Fallback longitude (°)",
        default: 24.98,
      },
      forecastDays: {
        type: "number",
        title: "Forecast horizon (days, max 16)",
        default: 7,
      },
      influxUrl: {
        type: "string",
        title: "InfluxDB URL",
        default: "http://influxdb:8086",
      },
      influxToken: { type: "string", title: "InfluxDB token", default: "" },
      influxOrg:    { type: "string", title: "InfluxDB organisation", default: "boat-data" },
      influxBucket: { type: "string", title: "InfluxDB bucket", default: "signalk" },
    },
  };

  let opts = null;
  let lastPosition = null;
  let fetchedFor = null;          // { lat, lon, at }
  let unsubscribes = [];
  let refreshTimer = null;

  let influxClient = null;
  let influxWriteApi = null;

  function distanceKm(a, b) {
    if (!a || !b) return Infinity;
    const R = 6371;
    const toRad = (d) => (d * Math.PI) / 180;
    const dLat = toRad(b.latitude - a.latitude);
    const dLon = toRad(b.longitude - a.longitude);
    const lat1 = toRad(a.latitude);
    const lat2 = toRad(b.latitude);
    const h =
      Math.sin(dLat / 2) ** 2 +
      Math.cos(lat1) * Math.cos(lat2) * Math.sin(dLon / 2) ** 2;
    return 2 * R * Math.asin(Math.sqrt(h));
  }

  function setupInflux() {
    influxClient = new InfluxDB({ url: opts.influxUrl, token: opts.influxToken });
    influxWriteApi = influxClient.getWriteApi(opts.influxOrg, opts.influxBucket, "ms", {
      batchSize: 200,
      flushInterval: 5000,
      maxRetries: 3,
    });
    app.debug(
      `weather forecast: writing to ${opts.influxUrl} ${opts.influxOrg}/${opts.influxBucket}`,
    );
  }

  async function fetchForecast(lat, lon) {
    const url = new URL(OPEN_METEO_URL);
    url.searchParams.set("latitude", lat.toFixed(4));
    url.searchParams.set("longitude", lon.toFixed(4));
    url.searchParams.set("hourly", HOURLY_VARS.join(","));
    url.searchParams.set("wind_speed_unit", "ms");
    url.searchParams.set("forecast_days", String(Math.min(16, Math.max(1, opts.forecastDays))));
    url.searchParams.set("timezone", "UTC");

    app.debug(`weather forecast: GET ${url.toString()}`);
    const ctrl = new AbortController();
    const t = setTimeout(() => ctrl.abort(), 30_000);
    let resp;
    try {
      resp = await fetch(url, { signal: ctrl.signal });
    } finally {
      clearTimeout(t);
    }
    if (!resp.ok) throw new Error(`Open-Meteo HTTP ${resp.status}`);
    return resp.json();
  }

  function writeToInflux(json, lat, lon) {
    const h = json.hourly;
    if (!h || !Array.isArray(h.time)) {
      app.error("weather forecast: response missing hourly.time");
      return 0;
    }
    const latTag = lat.toFixed(2);
    const lonTag = lon.toFixed(2);
    let written = 0;

    for (let i = 0; i < h.time.length; i++) {
      // Open-Meteo returns "YYYY-MM-DDTHH:00" (no Z) but timezone=UTC,
      // so append Z to parse correctly.
      const ts = new Date(h.time[i] + "Z").getTime();
      if (!Number.isFinite(ts)) continue;

      const point = new Point("weather.forecast")
        .tag("lat", latTag)
        .tag("lon", lonTag)
        .timestamp(ts);

      const tempC      = h.temperature_2m?.[i];
      const wsMs       = h.wind_speed_10m?.[i];
      const wgMs       = h.wind_gusts_10m?.[i];
      const wdDeg      = h.wind_direction_10m?.[i];
      const cloudPct   = h.cloud_cover?.[i];
      const precipMm   = h.precipitation?.[i];
      const pressureHpa= h.surface_pressure?.[i];

      let added = false;
      if (Number.isFinite(tempC))       { point.floatField("temp", tempC + 273.15); added = true; }
      if (Number.isFinite(wsMs))        { point.floatField("windSpeed", wsMs); added = true; }
      if (Number.isFinite(wgMs))        { point.floatField("windGust",  wgMs); added = true; }
      if (Number.isFinite(wdDeg))       { point.floatField("windDir",   wdDeg * Math.PI / 180); added = true; }
      if (Number.isFinite(cloudPct))    { point.floatField("cloudCover",cloudPct / 100); added = true; }
      if (Number.isFinite(precipMm))    { point.floatField("precip",    precipMm); added = true; }
      if (Number.isFinite(pressureHpa)) { point.floatField("pressure",  pressureHpa * 100); added = true; }

      if (added) { influxWriteApi.writePoint(point); written++; }
    }

    influxWriteApi.flush().catch((err) => app.error(`weather forecast flush: ${err.message}`));
    return written;
  }

  async function refresh(force = false) {
    const lat = lastPosition?.latitude ?? opts.defaultLatitude;
    const lon = lastPosition?.longitude ?? opts.defaultLongitude;

    if (
      !force &&
      fetchedFor &&
      Date.now() - fetchedFor.at < FORECAST_REFRESH_MS &&
      distanceKm(fetchedFor, { latitude: lat, longitude: lon }) < POSITION_MOVE_KM
    ) {
      return;
    }

    try {
      const json = await fetchForecast(lat, lon);
      const n = writeToInflux(json, lat, lon);
      fetchedFor = { latitude: lat, longitude: lon, at: Date.now() };
      app.setPluginStatus(`Wrote ${n} hourly points @ ${lat.toFixed(2)},${lon.toFixed(2)}`);
      app.debug(`weather forecast: wrote ${n} points to InfluxDB`);
    } catch (err) {
      app.setPluginError(`Open-Meteo fetch failed: ${err.message}`);
      app.error(`weather forecast: ${err.stack || err.message}`);
    }
  }

  plugin.start = function (options) {
    opts = {
      positionPath: options.positionPath ?? "navigation.position",
      defaultLatitude: options.defaultLatitude ?? 60.11,
      defaultLongitude: options.defaultLongitude ?? 24.98,
      forecastDays: options.forecastDays ?? 7,
      influxUrl: options.influxUrl ?? "http://influxdb:8086",
      influxToken: options.influxToken ?? "",
      influxOrg: options.influxOrg ?? "boat-data",
      influxBucket: options.influxBucket ?? "signalk",
    };

    if (!opts.influxToken) {
      app.setPluginError("InfluxDB token not configured");
      return;
    }

    setupInflux();

    app.subscriptionmanager.subscribe(
      {
        context: "vessels.self",
        subscribe: [{ path: opts.positionPath, minPeriod: 5000 }],
      },
      unsubscribes,
      (err) => app.error(`subscribe error: ${err}`),
      (delta) => {
        if (!delta.updates) return;
        for (const u of delta.updates) {
          if (!u.values) continue;
          for (const v of u.values) {
            if (
              v.path === opts.positionPath &&
              v.value &&
              typeof v.value.latitude === "number" &&
              typeof v.value.longitude === "number"
            ) {
              lastPosition = {
                latitude: v.value.latitude,
                longitude: v.value.longitude,
              };
            }
          }
        }
      },
    );

    refresh(true);
    refreshTimer = setInterval(() => refresh(false), FORECAST_REFRESH_MS);
  };

  plugin.stop = function () {
    unsubscribes.forEach((fn) => fn());
    unsubscribes = [];
    if (refreshTimer) clearInterval(refreshTimer);
    refreshTimer = null;
    if (influxWriteApi) {
      const w = influxWriteApi;
      influxWriteApi = null;
      w.close().catch((err) => app.error(`weather forecast close: ${err.message}`));
    }
    influxClient = null;
    fetchedFor = null;
    lastPosition = null;
  };

  return plugin;
};
