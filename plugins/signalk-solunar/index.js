/**
 * signalk-solunar
 *
 * Computes sunrise/sunset, moon phase + illumination, and solunar major/minor
 * fishing periods for the boat's current position. Designed to feed a fishing
 * dashboard.
 *
 * Solunar theory in one paragraph: fish (and most game animals) feed most
 * actively when the moon is overhead or directly underfoot ("major" periods,
 * ~2 h centred on transit) and to a lesser extent at moonrise / moonset
 * ("minor" periods, ~1 h centred on the event). Activity is strongest near
 * new and full moons. We compute these windows for the local 36-hour horizon
 * starting at local midnight, then expose:
 *
 *   - the times of today's sun & moon events
 *   - moon phase (0..1) and illumination fraction
 *   - the next major and next minor period (start / end / minutes from now)
 *   - whether a major or minor period is active right now
 *   - a 0..4 day rating (phase score + sunrise/sunset overlap bonus)
 *
 * All times are emitted as ISO-8601 strings; numeric values are SI / unitless.
 */

const SunCalc = require("suncalc");
const { InfluxDB, Point } = require("@influxdata/influxdb-client");

const MS_PER_MIN = 60_000;
const MS_PER_HOUR = 3_600_000;
const MS_PER_DAY = 86_400_000;
const FORECAST_HOURS = 168;          // 7 days of hourly forecast
const FORECAST_REWRITE_MS = 60 * 60 * 1000;  // refresh forecast hourly

// Solunar window half-widths
const MAJOR_HALF_MIN = 60;   // ±60 min around moon transit  (2 h major)
const MINOR_HALF_MIN = 30;   // ±30 min around moonrise/set  (1 h minor)
const SUN_OVERLAP_MIN = 60;  // ±60 min around sunrise/sunset for rating bonus

const PHASE_NAMES = [
  { max: 0.0625, name: "New Moon" },
  { max: 0.1875, name: "Waxing Crescent" },
  { max: 0.3125, name: "First Quarter" },
  { max: 0.4375, name: "Waxing Gibbous" },
  { max: 0.5625, name: "Full Moon" },
  { max: 0.6875, name: "Waning Gibbous" },
  { max: 0.8125, name: "Last Quarter" },
  { max: 0.9375, name: "Waning Crescent" },
  { max: 1.0001, name: "New Moon" },
];

const RATING_NAMES = ["Poor", "Below Average", "Average", "Good", "Excellent"];

module.exports = function (app) {
  const plugin = {};
  plugin.id = "signalk-solunar";
  plugin.name = "Solunar (sun, moon, fishing periods)";
  plugin.description =
    "Publishes sunrise/sunset, moon phase, and solunar major/minor periods " +
    "for the current position. Useful for a fishing dashboard.";

  plugin.schema = {
    type: "object",
    properties: {
      positionPath: {
        type: "string",
        title: "Position path",
        default: "navigation.position",
      },
      defaultLatitude: {
        type: "number",
        title: "Fallback latitude (°)",
        description:
          "Used when no position has been received yet. Default is Helsinki Harmaja.",
        default: 60.11,
      },
      defaultLongitude: {
        type: "number",
        title: "Fallback longitude (°)",
        description:
          "Used when no position has been received yet. Default is Helsinki Harmaja.",
        default: 24.98,
      },
      tickSeconds: {
        type: "number",
        title: "Update interval (s)",
        description:
          "How often to refresh active-period flags and 'next period' values.",
        default: 60,
      },
      positionMoveKm: {
        type: "number",
        title: "Recompute distance threshold (km)",
        description:
          "Force a full astronomy recompute when position has moved by this much.",
        default: 25,
      },
      influxUrl: {
        type: "string",
        title: "InfluxDB URL (forecast write target)",
        description:
          "Leave empty to disable forecast writes. When set, an hourly fishing-score forecast over the next 168 h is written to the bucket below.",
        default: "http://influxdb:8086",
      },
      influxToken: {
        type: "string",
        title: "InfluxDB token",
        default: "",
      },
      influxOrg: {
        type: "string",
        title: "InfluxDB organisation",
        default: "boat-data",
      },
      influxBucket: {
        type: "string",
        title: "InfluxDB bucket",
        default: "signalk",
      },
    },
  };

  let opts = null;
  let unsubscribes = [];
  let tickTimer = null;

  let lastPosition = null;     // { latitude, longitude }
  let computedFor = null;      // { date: 'YYYY-MM-DD', lat, lon }
  let cache = null;            // result of computeAstronomy()

  // ─── Geo helpers ────────────────────────────────────────────────────────

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

  function localDateKey(d) {
    // Local-time YYYY-MM-DD so day rollover is detected correctly even on
    // a server in UTC running for a vessel in another timezone.
    const y = d.getFullYear();
    const m = String(d.getMonth() + 1).padStart(2, "0");
    const day = String(d.getDate()).padStart(2, "0");
    return `${y}-${m}-${day}`;
  }

  function localMidnight(d) {
    const x = new Date(d);
    x.setHours(0, 0, 0, 0);
    return x;
  }

  // ─── Astronomy ──────────────────────────────────────────────────────────

  /**
   * Find moon transit times (upper = overhead, lower = underfoot) by sampling
   * altitude over `hours` from `start`. The maximum of altitude is the upper
   * transit; the minimum is the lower transit.
   *
   * Sampling every 5 min is plenty for ±2.5 min accuracy, which is well below
   * the half-width of the major window we care about (±60 min).
   */
  function findMoonTransits(start, hours, lat, lon) {
    const stepMs = 5 * MS_PER_MIN;
    const samples = Math.floor((hours * MS_PER_HOUR) / stepMs);
    const transits = []; // { time, altitude, kind: 'upper'|'lower' }
    let prev = null;
    let prevPrev = null;

    for (let i = 0; i <= samples; i++) {
      const t = new Date(start.getTime() + i * stepMs);
      const alt = SunCalc.getMoonPosition(t, lat, lon).altitude;
      if (prev !== null && prevPrev !== null) {
        // Interior local extremum
        if (prev.alt > prevPrev.alt && prev.alt > alt) {
          transits.push({ time: prev.t, altitude: prev.alt, kind: "upper" });
        } else if (prev.alt < prevPrev.alt && prev.alt < alt) {
          transits.push({ time: prev.t, altitude: prev.alt, kind: "lower" });
        }
      }
      prevPrev = prev;
      prev = { t, alt };
    }
    return transits;
  }

  function moonPhaseName(phase) {
    for (const p of PHASE_NAMES) if (phase < p.max) return p.name;
    return "New Moon";
  }

  function makeWindow(centre, halfMin, kind) {
    if (!centre || isNaN(centre.getTime())) return null;
    return {
      kind,
      centre: centre.toISOString(),
      start: new Date(centre.getTime() - halfMin * MS_PER_MIN).toISOString(),
      end: new Date(centre.getTime() + halfMin * MS_PER_MIN).toISOString(),
    };
  }

  /**
   * Compute everything that depends only on date + position. Refreshed when
   * position moves more than the threshold or when the local day rolls over.
   */
  function computeAstronomy(now, lat, lon) {
    // Build periods over a 48h window starting at yesterday-midnight so that
    // "next period" lookups work near midnight too.
    const horizonStart = new Date(localMidnight(now).getTime() - MS_PER_DAY);
    const horizonHours = 72;

    const transits = findMoonTransits(horizonStart, horizonHours, lat, lon);

    // Walk day-by-day for moonrise/set + sun times. Cover yesterday→day after
    // tomorrow so we always have at least one upcoming event of each kind.
    const days = [];
    for (let d = -1; d <= 2; d++) {
      const dayDate = new Date(now.getTime() + d * MS_PER_DAY);
      const sun = SunCalc.getTimes(dayDate, lat, lon);
      const moon = SunCalc.getMoonTimes(dayDate, lat, lon, true);
      days.push({ dayDate, sun, moon });
    }

    const today = days.find(
      (d) => localDateKey(d.dayDate) === localDateKey(now),
    ) || days[1];

    const majors = transits.map((t) =>
      makeWindow(t.time, MAJOR_HALF_MIN, t.kind === "upper" ? "major-overhead" : "major-underfoot"),
    ).filter(Boolean);

    const minors = [];
    for (const d of days) {
      if (d.moon.rise) minors.push(makeWindow(d.moon.rise, MINOR_HALF_MIN, "minor-rise"));
      if (d.moon.set)  minors.push(makeWindow(d.moon.set,  MINOR_HALF_MIN, "minor-set"));
    }

    // Deduplicate (consecutive days can yield duplicate rise/set within a few
    // minutes around the date boundary).
    const dedupe = (arr) => {
      const seen = new Set();
      return arr.filter((w) => {
        if (!w) return false;
        const key = w.kind + "|" + w.centre.slice(0, 16);
        if (seen.has(key)) return false;
        seen.add(key);
        return true;
      }).sort((a, b) => a.start.localeCompare(b.start));
    };

    const majorPeriods = dedupe(majors);
    const minorPeriods = dedupe(minors.filter(Boolean));

    const moonIllum = SunCalc.getMoonIllumination(now);
    const phase = moonIllum.phase;             // 0..1, 0 = new
    const illumination = moonIllum.fraction;   // 0..1

    // Day rating 0..4 — combines phase strength with sun-overlap bonus.
    //   phaseScore: peaks at new (0) and full (0.5), zero at quarters.
    //   bonus: +1 if any major period falls within ±60 min of sunrise or sunset.
    const phaseScore = Math.cos(2 * Math.PI * 2 * phase) * 0.5 + 0.5;

    const sunSet = today.sun.sunset;
    const sunRise = today.sun.sunrise;
    const overlap = (centreIso) => {
      const c = new Date(centreIso).getTime();
      const window = SUN_OVERLAP_MIN * MS_PER_MIN + MAJOR_HALF_MIN * MS_PER_MIN;
      return (
        (sunRise && Math.abs(c - sunRise.getTime()) <= window) ||
        (sunSet && Math.abs(c - sunSet.getTime()) <= window)
      );
    };
    const todayMajors = majorPeriods.filter((p) => {
      const c = new Date(p.centre);
      return (
        c.getTime() >= localMidnight(now).getTime() &&
        c.getTime() < localMidnight(now).getTime() + MS_PER_DAY
      );
    });
    const sunBonus = todayMajors.some((p) => overlap(p.centre)) ? 1 : 0;

    const rating = Math.max(0, Math.min(4, phaseScore * 3 + sunBonus));
    const ratingName = RATING_NAMES[Math.round(rating)];

    const iso = (d) => (d && !isNaN(d.getTime()) ? d.toISOString() : null);

    return {
      sun: {
        sunrise: iso(today.sun.sunrise),
        sunset: iso(today.sun.sunset),
        solarNoon: iso(today.sun.solarNoon),
        dawn: iso(today.sun.dawn),
        dusk: iso(today.sun.dusk),
        nightEnd: iso(today.sun.nightEnd),
        night: iso(today.sun.night),
        nauticalDawn: iso(today.sun.nauticalDawn),
        nauticalDusk: iso(today.sun.nauticalDusk),
      },
      moon: {
        moonrise: iso(today.moon.rise),
        moonset: iso(today.moon.set),
        phase,                  // 0..1
        phaseName: moonPhaseName(phase),
        illumination,           // 0..1
      },
      solunar: {
        majorPeriods,
        minorPeriods,
        rating,
        ratingName,
      },
    };
  }

  // ─── Active period / next period ────────────────────────────────────────

  function findActiveAndNext(periods, now) {
    const t = now.getTime();
    let active = null;
    let next = null;
    for (const p of periods) {
      const start = new Date(p.start).getTime();
      const end = new Date(p.end).getTime();
      if (t >= start && t < end) active = p;
      else if (t < start && (next === null || start < new Date(next.start).getTime())) {
        next = p;
      }
    }
    return { active, next };
  }

  // ─── Emission ───────────────────────────────────────────────────────────

  function emitMeta() {
    app.handleMessage(plugin.id, {
      updates: [{
        meta: [
          { path: "environment.sun.sunrise",         value: { description: "Sunrise (ISO 8601)", displayName: "Sunrise" } },
          { path: "environment.sun.sunset",          value: { description: "Sunset (ISO 8601)", displayName: "Sunset" } },
          { path: "environment.sun.solarNoon",       value: { description: "Solar noon (ISO 8601)", displayName: "Solar Noon" } },
          { path: "environment.sun.dawn",            value: { description: "Civil dawn (ISO 8601)", displayName: "Dawn" } },
          { path: "environment.sun.dusk",            value: { description: "Civil dusk (ISO 8601)", displayName: "Dusk" } },
          { path: "environment.moon.moonrise",       value: { description: "Moonrise (ISO 8601)", displayName: "Moonrise" } },
          { path: "environment.moon.moonset",        value: { description: "Moonset (ISO 8601)", displayName: "Moonset" } },
          { path: "environment.moon.phase",          value: { description: "Lunar phase 0..1 (0/1=new, 0.5=full)", units: "ratio", displayName: "Moon Phase" } },
          { path: "environment.moon.illumination",   value: { description: "Illuminated fraction of disc", units: "ratio", displayName: "Moon Illumination" } },
          { path: "environment.moon.phaseName",      value: { description: "Human-readable lunar phase", displayName: "Moon Phase Name" } },
          { path: "environment.solunar.rating",      value: { description: "Day fishing rating (0=poor, 4=excellent)", displayName: "Solunar Rating" } },
          { path: "environment.solunar.ratingName",  value: { description: "Human-readable solunar day rating", displayName: "Solunar Rating Name" } },
          { path: "environment.solunar.activeKind",  value: { description: "Currently active solunar window: 'major', 'minor', or 'none'", displayName: "Active Period" } },
          { path: "environment.solunar.minutesToNextMajor", value: { description: "Minutes until the next major period start", units: "min", displayName: "Next Major (min)" } },
          { path: "environment.solunar.minutesToNextMinor", value: { description: "Minutes until the next minor period start", units: "min", displayName: "Next Minor (min)" } },
        ],
      }],
    });
  }

  function emitAll(now) {
    if (!cache) return;
    const { sun, moon, solunar } = cache;

    const majorAN = findActiveAndNext(solunar.majorPeriods, now);
    const minorAN = findActiveAndNext(solunar.minorPeriods, now);

    const activeKind = majorAN.active
      ? "major"
      : minorAN.active
        ? "minor"
        : "none";

    const minutesUntil = (p) =>
      p ? Math.round((new Date(p.start).getTime() - now.getTime()) / MS_PER_MIN) : null;

    const values = [
      { path: "environment.sun.sunrise",        value: sun.sunrise },
      { path: "environment.sun.sunset",         value: sun.sunset },
      { path: "environment.sun.solarNoon",      value: sun.solarNoon },
      { path: "environment.sun.dawn",           value: sun.dawn },
      { path: "environment.sun.dusk",           value: sun.dusk },
      { path: "environment.sun.nightEnd",       value: sun.nightEnd },
      { path: "environment.sun.night",          value: sun.night },
      { path: "environment.sun.nauticalDawn",   value: sun.nauticalDawn },
      { path: "environment.sun.nauticalDusk",   value: sun.nauticalDusk },

      { path: "environment.moon.moonrise",      value: moon.moonrise },
      { path: "environment.moon.moonset",       value: moon.moonset },
      { path: "environment.moon.phase",         value: moon.phase },
      { path: "environment.moon.phaseName",     value: moon.phaseName },
      { path: "environment.moon.illumination",  value: moon.illumination },

      { path: "environment.solunar.rating",     value: solunar.rating },
      { path: "environment.solunar.ratingName", value: solunar.ratingName },
      { path: "environment.solunar.activeKind", value: activeKind },

      { path: "environment.solunar.activeMajor", value: majorAN.active || null },
      { path: "environment.solunar.activeMinor", value: minorAN.active || null },
      { path: "environment.solunar.nextMajor",   value: majorAN.next || null },
      { path: "environment.solunar.nextMinor",   value: minorAN.next || null },

      { path: "environment.solunar.nextMajorStart", value: majorAN.next?.start ?? null },
      { path: "environment.solunar.nextMajorEnd",   value: majorAN.next?.end   ?? null },
      { path: "environment.solunar.nextMinorStart", value: minorAN.next?.start ?? null },
      { path: "environment.solunar.nextMinorEnd",   value: minorAN.next?.end   ?? null },

      { path: "environment.solunar.minutesToNextMajor", value: minutesUntil(majorAN.next) },
      { path: "environment.solunar.minutesToNextMinor", value: minutesUntil(minorAN.next) },

      { path: "environment.solunar.majorPeriods", value: solunar.majorPeriods },
      { path: "environment.solunar.minorPeriods", value: solunar.minorPeriods },
    ];

    app.handleMessage(plugin.id, {
      updates: [{ timestamp: now.toISOString(), values }],
    });
  }

  // ─── Forecast (hourly score over 168 h, written to InfluxDB) ───────────

  /**
   * Hourly fishing score for a given moment. Combines:
   *   - daily rating (slow-changing, phase-driven 0..4)
   *   - +1.5 if inside a major period
   *   - +0.75 if inside a minor period
   *   - +0.75 if within ±60 min of sunrise or sunset
   *
   * Capped at 4. Independent of the daily-rating-only metric, so a poor day
   * can still have a few hours that bump above average if all stars align.
   */
  function scoreAt(t, dailyRating, majors, minors, sun) {
    const ms = t.getTime();
    const within = (centreIso, halfMs) => {
      if (!centreIso) return false;
      const c = new Date(centreIso).getTime();
      return Math.abs(ms - c) <= halfMs;
    };

    const inMajor = majors.some(
      (p) => ms >= new Date(p.start).getTime() && ms < new Date(p.end).getTime(),
    );
    const inMinor = minors.some(
      (p) => ms >= new Date(p.start).getTime() && ms < new Date(p.end).getTime(),
    );
    const sunWindow = SUN_OVERLAP_MIN * MS_PER_MIN;
    const nearSun =
      within(sun.sunrise, sunWindow) || within(sun.sunset, sunWindow);

    let score = dailyRating * 0.5;       // 0..2 from daily phase quality
    if (inMajor) score += 1.5;
    if (inMinor) score += 0.75;
    if (nearSun) score += 0.75;
    return {
      score: Math.max(0, Math.min(4, score)),
      inMajor: inMajor ? 1 : 0,
      inMinor: inMinor ? 1 : 0,
      nearSun: nearSun ? 1 : 0,
    };
  }

  /**
   * Compute hourly forecast over `hours` from `start`. We pre-compute one
   * big set of moon transits over the full range and per-day sun events so
   * the per-hour loop is cheap.
   */
  function computeForecast(start, hours, lat, lon) {
    const transits = findMoonTransits(start, hours, lat, lon);
    const majors = transits.map((t) =>
      makeWindow(t.time, MAJOR_HALF_MIN, t.kind === "upper" ? "major-overhead" : "major-underfoot"),
    ).filter(Boolean);

    const minors = [];
    const sunByDate = new Map();
    const dailyByDate = new Map();
    const days = Math.ceil(hours / 24) + 1;
    for (let d = 0; d <= days; d++) {
      const dayDate = new Date(start.getTime() + d * MS_PER_DAY);
      const dayKey = localDateKey(dayDate);
      const sun = SunCalc.getTimes(dayDate, lat, lon);
      const moon = SunCalc.getMoonTimes(dayDate, lat, lon, true);
      sunByDate.set(dayKey, sun);
      if (moon.rise) minors.push(makeWindow(moon.rise, MINOR_HALF_MIN, "minor-rise"));
      if (moon.set)  minors.push(makeWindow(moon.set,  MINOR_HALF_MIN, "minor-set"));

      // Cache daily rating: compute once per day using the noon point as ref.
      const noon = new Date(dayDate);
      noon.setHours(12, 0, 0, 0);
      const moonIllum = SunCalc.getMoonIllumination(noon);
      const phaseScore = Math.cos(2 * Math.PI * 2 * moonIllum.phase) * 0.5 + 0.5;
      const window = SUN_OVERLAP_MIN * MS_PER_MIN + MAJOR_HALF_MIN * MS_PER_MIN;
      const dayMidnight = localMidnight(dayDate).getTime();
      const todayMajors = majors.filter((p) => {
        const c = new Date(p.centre).getTime();
        return c >= dayMidnight && c < dayMidnight + MS_PER_DAY;
      });
      const sunBonus = todayMajors.some((p) => {
        const c = new Date(p.centre).getTime();
        return (
          (sun.sunrise && Math.abs(c - sun.sunrise.getTime()) <= window) ||
          (sun.sunset  && Math.abs(c - sun.sunset.getTime())  <= window)
        );
      }) ? 1 : 0;
      dailyByDate.set(dayKey, Math.max(0, Math.min(4, phaseScore * 3 + sunBonus)));
    }

    const points = [];
    for (let h = 0; h < hours; h++) {
      const t = new Date(start.getTime() + h * MS_PER_HOUR);
      const dayKey = localDateKey(t);
      const dailyRating = dailyByDate.get(dayKey) ?? 0;
      const sun = sunByDate.get(dayKey) ?? {};
      const s = scoreAt(t, dailyRating, majors, minors, sun);
      points.push({ time: t, dailyRating, ...s });
    }
    return points;
  }

  let influxClient = null;
  let influxWriteApi = null;
  let lastForecastWrite = 0;

  function setupInflux() {
    if (!opts.influxUrl || !opts.influxToken) {
      app.debug("solunar forecast: InfluxDB not configured, skipping forecast writes");
      return;
    }
    try {
      influxClient = new InfluxDB({ url: opts.influxUrl, token: opts.influxToken });
      influxWriteApi = influxClient.getWriteApi(opts.influxOrg, opts.influxBucket, "ms", {
        batchSize: 200,
        flushInterval: 5000,
        maxRetries: 3,
      });
      app.debug(
        `solunar forecast: writing to ${opts.influxUrl} ${opts.influxOrg}/${opts.influxBucket}`,
      );
    } catch (err) {
      app.error(`solunar forecast: InfluxDB init failed: ${err.message}`);
      influxWriteApi = null;
    }
  }

  function writeForecast(now) {
    if (!influxWriteApi) return;
    const lat = lastPosition?.latitude ?? opts.defaultLatitude;
    const lon = lastPosition?.longitude ?? opts.defaultLongitude;
    const start = new Date(now.getTime() - now.getTime() % MS_PER_HOUR);  // round down to hour

    const forecast = computeForecast(start, FORECAST_HOURS, lat, lon);
    const latTag = lat.toFixed(2);
    const lonTag = lon.toFixed(2);

    for (const p of forecast) {
      const point = new Point("solunar.forecast")
        .tag("lat", latTag)
        .tag("lon", lonTag)
        .floatField("score", p.score)
        .floatField("dailyRating", p.dailyRating)
        .intField("inMajor", p.inMajor)
        .intField("inMinor", p.inMinor)
        .intField("nearSun", p.nearSun)
        .timestamp(p.time);
      influxWriteApi.writePoint(point);
    }
    influxWriteApi.flush().catch((err) => app.error(`solunar forecast flush: ${err.message}`));
    lastForecastWrite = now.getTime();
    app.debug(`solunar forecast: wrote ${forecast.length} hourly points to InfluxDB`);
  }

  // ─── Main loop ──────────────────────────────────────────────────────────

  function ensureFresh(now) {
    const lat = lastPosition?.latitude ?? opts.defaultLatitude;
    const lon = lastPosition?.longitude ?? opts.defaultLongitude;

    const dateKey = localDateKey(now);
    const stale =
      !cache ||
      !computedFor ||
      computedFor.date !== dateKey ||
      distanceKm({ latitude: computedFor.lat, longitude: computedFor.lon }, { latitude: lat, longitude: lon }) >= opts.positionMoveKm;

    if (stale) {
      app.debug(`recompute astronomy for ${dateKey} @ ${lat.toFixed(3)},${lon.toFixed(3)}`);
      cache = computeAstronomy(now, lat, lon);
      computedFor = { date: dateKey, lat, lon };
    }
  }

  function tick() {
    const now = new Date();
    ensureFresh(now);
    emitAll(now);
    if (influxWriteApi && now.getTime() - lastForecastWrite >= FORECAST_REWRITE_MS) {
      writeForecast(now);
    }
  }

  plugin.start = function (options) {
    opts = {
      positionPath: options.positionPath ?? "navigation.position",
      defaultLatitude: options.defaultLatitude ?? 60.11,
      defaultLongitude: options.defaultLongitude ?? 24.98,
      tickSeconds: Math.max(10, options.tickSeconds ?? 60),
      positionMoveKm: options.positionMoveKm ?? 25,
      influxUrl: options.influxUrl ?? "",
      influxToken: options.influxToken ?? "",
      influxOrg: options.influxOrg ?? "boat-data",
      influxBucket: options.influxBucket ?? "signalk",
    };

    app.debug(
      `solunar: position=${opts.positionPath}, fallback=${opts.defaultLatitude},${opts.defaultLongitude}, tick=${opts.tickSeconds}s`,
    );

    emitMeta();
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

    // Compute & emit immediately, then on tick interval.
    tick();
    tickTimer = setInterval(tick, opts.tickSeconds * 1000);
  };

  plugin.stop = function () {
    unsubscribes.forEach((fn) => fn());
    unsubscribes = [];
    if (tickTimer) clearInterval(tickTimer);
    tickTimer = null;
    if (influxWriteApi) {
      const w = influxWriteApi;
      influxWriteApi = null;
      w.close().catch((err) => app.error(`solunar forecast close: ${err.message}`));
    }
    influxClient = null;
    cache = null;
    computedFor = null;
    lastPosition = null;
    lastForecastWrite = 0;
  };

  return plugin;
};
