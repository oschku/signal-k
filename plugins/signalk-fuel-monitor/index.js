/**
 * signalk-fuel-monitor
 *
 * Estimates fuel remaining by integrating engine fuel rate (no tank sender).
 * Also derives range and economy figures from the current fuel rate and SOG.
 *
 * Emitted paths (all SI units — KIP converts for display):
 *
 *   tanks.fuel.0.capacity          m³      constant from config
 *   tanks.fuel.0.currentVolume     m³      remaining fuel (KIP: litres)
 *   tanks.fuel.0.currentLevel      ratio   remaining / capacity (KIP: %)
 *
 *   tanks.fuel.0.timeRange         s       hours of fuel left at current rate (KIP: Hours)
 *   tanks.fuel.0.distanceRange     m       nm until empty at current rate + SOG (KIP: nm)
 *
 *   tanks.fuel.0.distancePerFuel   m/m³    fuel economy (KIP "Fuel Distance" → nm/L)
 *   tanks.fuel.0.fuelPerDistance   m³/m    fuel consumption per distance (→ L/nm = × 1,852,000)
 *
 * Refill PUT handlers:
 *   tanks.fuel.0.refill            any truthy value → reset to full (KIP boolean-switch)
 *   tanks.fuel.0.currentVolume     m³ value → set to that level
 *   tanks.fuel.0.currentLevel      ratio 0..1 → set to fraction of capacity
 */

const fs = require("fs");
const path = require("path");

// SI conversion constants
const M3_PER_S_TO_L_PER_H = 3.6e6;   // m³/s → L/h  (for debug logs only)
const NM_TO_M = 1852;
const L_TO_M3 = 0.001;
const NM_L_SCALE = NM_TO_M / L_TO_M3; // 1,852,000 — converts m/m³ ↔ nm/L

module.exports = function (app) {
  const plugin = {};
  plugin.id = "signalk-fuel-monitor";
  plugin.name = "Fuel Monitor (rate-integrated)";
  plugin.description =
    "Integrates fuel rate to track remaining fuel; derives time/distance range " +
    "and economy. PUT tanks.fuel.0.refill (boolean) to reset after refuelling.";

  plugin.schema = {
    type: "object",
    required: ["tankCapacityL"],
    properties: {
      tankCapacityL: {
        type: "number",
        title: "Tank capacity (L)",
        description: "Quicksilver 410 uses a 25 L portable tank.",
        default: 25,
      },
      fuelRatePath: {
        type: "string",
        title: "Fuel rate Signal K path",
        default: "propulsion.port.fuel.rate",
      },
      sogPath: {
        type: "string",
        title: "Speed over ground path",
        default: "navigation.speedOverGround",
      },
      tankPrefix: {
        type: "string",
        title: "Output tank path prefix",
        description: "Derived paths are published under <prefix>.*",
        default: "tanks.fuel.0",
      },
      minFuelRateLph: {
        type: "number",
        title: "Minimum fuel rate for range output (L/h)",
        description:
          "Below this rate the engine is effectively off and range figures are suppressed.",
        default: 0.5,
      },
      minSogKnots: {
        type: "number",
        title: "Minimum SOG for distance-based output (kn)",
        description:
          "Below this speed distance range and economy figures are suppressed (boat at rest).",
        default: 0.5,
      },
    },
  };

  const unsubscribes = [];
  let stateFile = null;
  let saveTimer = null;
  let opts = null;

  let remainingVolumeM3 = null;
  let lastRateM3s = 0;
  let lastSogMs = null;   // null = no SOG reading yet
  let lastUpdate = null;

  // ─── Persistence ────────────────────────────────────────────────────────

  function load() {
    try {
      if (fs.existsSync(stateFile)) {
        const data = JSON.parse(fs.readFileSync(stateFile, "utf8"));
        if (typeof data.remainingVolumeM3 === "number") {
          remainingVolumeM3 = data.remainingVolumeM3;
          app.debug(`loaded remaining=${(remainingVolumeM3 * 1000).toFixed(2)} L`);
          return;
        }
      }
    } catch (e) {
      app.error(`fuel-monitor load: ${e.message}`);
    }
    remainingVolumeM3 = opts.tankCapacityL * L_TO_M3;
  }

  function save() {
    try {
      fs.writeFileSync(stateFile, JSON.stringify({
        remainingVolumeM3,
        updatedAt: new Date().toISOString(),
      }));
    } catch (e) {
      app.error(`fuel-monitor save: ${e.message}`);
    }
  }

  function scheduleSave() {
    if (saveTimer) return;
    saveTimer = setTimeout(() => { saveTimer = null; save(); }, 5000);
  }

  // ─── Derived calculations ────────────────────────────────────────────────

  function deriveValues(rateM3s, sogMs) {
    const minRate = opts.minFuelRateLph / M3_PER_S_TO_L_PER_H;
    const minSog  = opts.minSogKnots * 0.51444;

    const engineRunning = rateM3s >= minRate;
    const boatMoving    = sogMs !== null && sogMs >= minSog;

    // Time remaining (s): remaining ÷ current rate
    const timeRange = engineRunning
      ? remainingVolumeM3 / rateM3s
      : null;

    // Distance remaining (m): time remaining × SOG
    const distanceRange = (timeRange !== null && boatMoving)
      ? timeRange * sogMs
      : null;

    // Economy: distance per fuel volume (m/m³) → KIP "Fuel Distance" → nm/L
    //   e.g. 9 m/s ÷ 2.2e-6 m³/s = 4,090,909 m/m³ ÷ 1,852,000 = 2.21 nm/L
    const distancePerFuel = (engineRunning && boatMoving)
      ? sogMs / rateM3s
      : null;

    // Economy: fuel per distance (m³/m) → L/nm = value × 1,852,000
    //   e.g. 2.2e-6 ÷ 9 = 2.44e-7 m³/m × 1,852,000 = 0.452 L/nm
    const fuelPerDistance = (engineRunning && boatMoving)
      ? rateM3s / sogMs
      : null;

    return { timeRange, distanceRange, distancePerFuel, fuelPerDistance };
  }

  // ─── Emission ────────────────────────────────────────────────────────────

  function emit(rateM3s) {
    const capacityM3 = opts.tankCapacityL * L_TO_M3;
    const level = Math.max(0, Math.min(1, remainingVolumeM3 / capacityM3));

    const { timeRange, distanceRange, distancePerFuel, fuelPerDistance } =
      deriveValues(rateM3s, lastSogMs);

    const values = [
      { path: `${opts.tankPrefix}.capacity`,      value: capacityM3 },
      { path: `${opts.tankPrefix}.currentVolume`, value: remainingVolumeM3 },
      { path: `${opts.tankPrefix}.currentLevel`,  value: level },
    ];

    if (timeRange !== null)        values.push({ path: `${opts.tankPrefix}.timeRange`,        value: timeRange });
    if (distanceRange !== null)    values.push({ path: `${opts.tankPrefix}.distanceRange`,    value: distanceRange });
    if (distancePerFuel !== null)  values.push({ path: `${opts.tankPrefix}.distancePerFuel`,  value: distancePerFuel });
    if (fuelPerDistance !== null)  values.push({ path: `${opts.tankPrefix}.fuelPerDistance`,  value: fuelPerDistance });

    app.handleMessage(plugin.id, {
      updates: [{ timestamp: new Date().toISOString(), values }],
    });
  }

  // ─── Refill handlers ─────────────────────────────────────────────────────

  function refillTo(volumeM3) {
    const capacityM3 = opts.tankCapacityL * L_TO_M3;
    remainingVolumeM3 = Math.max(0, Math.min(capacityM3, volumeM3));
    app.debug(`refill → ${(remainingVolumeM3 * 1000).toFixed(1)} L`);
    emit(lastRateM3s);
    save();
  }

  function onVolumePut(context, path, value) {
    const v = Number(value);
    if (!Number.isFinite(v) || v < 0)
      return { state: "FAILED", message: "currentVolume must be a non-negative number (m³)" };
    refillTo(v);
    return { state: "COMPLETED", statusCode: 200 };
  }

  function onLevelPut(context, path, value) {
    const v = Number(value);
    if (!Number.isFinite(v) || v < 0 || v > 1)
      return { state: "FAILED", message: "currentLevel must be a ratio between 0 and 1" };
    refillTo(v * opts.tankCapacityL * L_TO_M3);
    return { state: "COMPLETED", statusCode: 200 };
  }

  // Any truthy value = full refill (KIP boolean-switch button)
  function onRefillPut(context, path, value) {
    if (!value) return { state: "COMPLETED", statusCode: 200 };
    refillTo(opts.tankCapacityL * L_TO_M3);
    return { state: "COMPLETED", statusCode: 200 };
  }

  // ─── Lifecycle ───────────────────────────────────────────────────────────

  plugin.start = function (options) {
    opts = {
      tankCapacityL:    options.tankCapacityL    ?? 25,
      fuelRatePath:     options.fuelRatePath     ?? "propulsion.port.fuel.rate",
      sogPath:          options.sogPath          ?? "navigation.speedOverGround",
      tankPrefix:       options.tankPrefix       ?? "tanks.fuel.0",
      minFuelRateLph:   options.minFuelRateLph   ?? 0.5,
      minSogKnots:      options.minSogKnots      ?? 0.5,
    };

    const dataDir = app.getDataDirPath
      ? app.getDataDirPath()
      : path.join(__dirname, ".data");
    fs.mkdirSync(dataDir, { recursive: true });
    stateFile = path.join(dataDir, "fuel-state.json");

    load();

    // Register units/description for derived paths that aren't in the SK spec,
    // so the data browser shows the right unit labels.
    app.handleMessage(plugin.id, {
      updates: [{
        meta: [
          { path: `${opts.tankPrefix}.timeRange`,       value: { description: "Estimated time until empty at current fuel rate", units: "s",   displayName: "Time Remaining" } },
          { path: `${opts.tankPrefix}.distanceRange`,   value: { description: "Estimated range until empty at current rate and SOG", units: "m",   displayName: "Range Remaining" } },
          { path: `${opts.tankPrefix}.distancePerFuel`, value: { description: "Fuel economy: distance per unit volume (nm/L = value / 1,852,000)", units: "m/m3", displayName: "Economy (nm/L)" } },
          { path: `${opts.tankPrefix}.fuelPerDistance`, value: { description: "Fuel consumption per unit distance (L/nm = value × 1,852,000)", units: "m3/m", displayName: "Consumption (L/nm)" } },
        ]
      }]
    });

    emit(0);

    if (app.registerPutHandler) {
      app.registerPutHandler("vessels.self", `${opts.tankPrefix}.currentVolume`, onVolumePut, plugin.id);
      app.registerPutHandler("vessels.self", `${opts.tankPrefix}.currentLevel`,  onLevelPut,  plugin.id);
      app.registerPutHandler("vessels.self", `${opts.tankPrefix}.refill`,        onRefillPut, plugin.id);
    }

    app.subscriptionmanager.subscribe(
      {
        context: "vessels.self",
        subscribe: [
          { path: opts.fuelRatePath, minPeriod: 500 },
          { path: opts.sogPath,      minPeriod: 500 },
        ],
      },
      unsubscribes,
      (err) => app.error(`fuel-monitor subscribe: ${err}`),
      (delta) => {
        if (!delta.updates) return;
        const now = Date.now();
        let gotRate = false;

        for (const u of delta.updates) {
          if (!u.values) continue;
          for (const v of u.values) {
            const val = Number(v.value);
            if (!Number.isFinite(val)) continue;

            if (v.path === opts.sogPath) {
              lastSogMs = Math.max(0, val);
            } else if (v.path === opts.fuelRatePath) {
              if (val < 0) continue;
              // Integrate previous rate over the elapsed interval before updating
              if (lastUpdate !== null) {
                const dtSec = Math.max(0, (now - lastUpdate) / 1000);
                remainingVolumeM3 = Math.max(0, remainingVolumeM3 - lastRateM3s * dtSec);
              }
              lastRateM3s = val;
              lastUpdate = now;
              gotRate = true;
            }
          }
        }

        // Only emit + save on fuel-rate updates to keep the integration timestamp clean.
        // SOG updates alone don't change remaining fuel, so no write needed.
        if (gotRate) {
          emit(lastRateM3s);
          scheduleSave();
        }
      },
    );
  };

  plugin.stop = function () {
    unsubscribes.forEach(fn => fn());
    unsubscribes.length = 0;
    if (saveTimer) {
      clearTimeout(saveTimer);
      saveTimer = null;
    }
    save();
    lastUpdate = null;
    lastRateM3s = 0;
    lastSogMs = null;
  };

  return plugin;
};
