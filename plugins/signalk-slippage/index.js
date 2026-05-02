/**
 * signalk-slippage
 *
 * Publishes propulsion.port.theoreticalSpeed and propulsion.port.slip from
 * the engine RPM and the boat's speed over ground (or speed through water).
 *
 * Theoretical speed (m/s) = (RPM / gearRatio) * pitch_m / 60
 *   - RPM/gearRatio = prop revolutions per minute
 *   - pitch_m       = how far one full prop turn would move in zero-slip water
 *   - /60           = per second
 *
 * Slip ratio = 1 - (actualSpeed / theoreticalSpeed),  clamped to [0, 1].
 *
 * Slip is only emitted when the engine is loaded enough for the value to be
 * meaningful (rpm above minRpm). Below that the prop is essentially freewheeling
 * and slip math diverges. theoreticalSpeed is emitted whenever RPM is present.
 */

module.exports = function (app) {
  const plugin = {};
  plugin.id = "signalk-slippage";
  plugin.name = "Prop Slippage";
  plugin.description =
    "Derives propulsion.port.slip and propulsion.port.theoreticalSpeed from RPM, prop geometry, and SOG/STW.";

  plugin.schema = {
    type: "object",
    properties: {
      gearRatio: {
        type: "number",
        title: "Gear ratio (engine:prop)",
        description:
          "Tohatsu MFS30DETL is 2.17:1. Engine RPM / gear ratio = prop RPM.",
        default: 2.17,
      },
      pitchInches: {
        type: "number",
        title: "Prop pitch (inches)",
        description:
          "Stock pitch for the Quicksilver 410 + MFS30DETL is typically 11–13\".",
        default: 13,
      },
      speedSource: {
        type: "string",
        title: "Speed source",
        enum: ["sog", "stw"],
        enumNames: ["SOG (over ground)", "STW (through water)"],
        description:
          "STW is more accurate for slip when there is current; SOG is the only option without a paddlewheel.",
        default: "sog",
      },
      minRpm: {
        type: "number",
        title: "Minimum engine RPM",
        description:
          "Below this engine RPM the prop is too lightly loaded for slip to be meaningful.",
        default: 1500,
      },
      enginePath: {
        type: "string",
        title: "Engine RPM path",
        default: "propulsion.port.revolutions",
      },
      sogPath: {
        type: "string",
        title: "SOG path",
        default: "navigation.speedOverGround",
      },
      stwPath: {
        type: "string",
        title: "STW path",
        default: "navigation.speedThroughWater",
      },
      outputPrefix: {
        type: "string",
        title: "Output path prefix",
        description: "Slip is emitted at <prefix>.slip and <prefix>.theoreticalSpeed.",
        default: "propulsion.port",
      },
    },
  };

  const unsubscribes = [];
  let lastRpmHz = null;
  let lastSpeedMs = null;

  function emitMeta(prefix) {
    app.handleMessage(plugin.id, {
      updates: [{
        meta: [
          {
            path: `${prefix}.slip`,
            value: { description: "Propeller slip ratio (0 = no slip, 1 = full slip)", units: "ratio", displayName: "Prop Slip" }
          },
          {
            path: `${prefix}.theoreticalSpeed`,
            value: { description: "Theoretical hull speed at zero prop slip", units: "m/s", displayName: "Theoretical Speed" }
          }
        ]
      }]
    });
  }

  function emit(prefix, slipRatio, theoreticalMs) {
    const values = [];
    if (theoreticalMs !== null && Number.isFinite(theoreticalMs)) {
      values.push({ path: `${prefix}.theoreticalSpeed`, value: theoreticalMs });
    }
    if (slipRatio !== null && Number.isFinite(slipRatio)) {
      values.push({ path: `${prefix}.slip`, value: slipRatio });
    }
    if (values.length === 0) return;
    app.handleMessage(plugin.id, {
      updates: [
        {
          timestamp: new Date().toISOString(),
          values,
        },
      ],
    });
  }

  function recompute(opts) {
    if (lastRpmHz === null) return;

    // RPM stored in Signal K as Hz (rev/sec). Engine rev/sec / gearRatio =
    // prop rev/sec. Multiply by pitch (m) for theoretical speed (m/s).
    const pitchM = (opts.pitchInches * 0.0254);
    const propRevPerSec = lastRpmHz / opts.gearRatio;
    const theoreticalMs = propRevPerSec * pitchM;

    let slipRatio = null;
    const engineRpm = lastRpmHz * 60;
    if (
      engineRpm >= opts.minRpm &&
      lastSpeedMs !== null &&
      theoreticalMs > 0.01
    ) {
      // Below the actual prop speed the engine is just spinning; clamp to [0,1]
      // so a stationary boat with throttle reads 100% slip rather than NaN/inf.
      const ratio = 1 - lastSpeedMs / theoreticalMs;
      slipRatio = Math.min(1, Math.max(0, ratio));
    }

    emit(opts.outputPrefix, slipRatio, theoreticalMs);
  }

  plugin.start = function (options) {
    const opts = {
      gearRatio: options.gearRatio ?? 2.17,
      pitchInches: options.pitchInches ?? 13,
      speedSource: options.speedSource ?? "sog",
      minRpm: options.minRpm ?? 1500,
      enginePath: options.enginePath ?? "propulsion.port.revolutions",
      sogPath: options.sogPath ?? "navigation.speedOverGround",
      stwPath: options.stwPath ?? "navigation.speedThroughWater",
      outputPrefix: options.outputPrefix ?? "propulsion.port",
    };

    const speedPath =
      opts.speedSource === "stw" ? opts.stwPath : opts.sogPath;

    app.debug(
      `slip: gearRatio=${opts.gearRatio}, pitch=${opts.pitchInches}\", ` +
        `engine=${opts.enginePath}, speed=${speedPath}, minRpm=${opts.minRpm}`,
    );

    emitMeta(opts.outputPrefix);

    app.subscriptionmanager.subscribe(
      {
        context: "vessels.self",
        subscribe: [
          { path: opts.enginePath, minPeriod: 500 },
          { path: speedPath,       minPeriod: 500 },
        ],
      },
      unsubscribes,
      (err) => app.error(`subscribe error: ${err}`),
      (delta) => {
        if (!delta.updates) return;
        for (const u of delta.updates) {
          if (!u.values) continue;
          for (const v of u.values) {
            if (typeof v.value !== "number") continue;
            if (v.path === opts.enginePath)  lastRpmHz   = v.value;
            else if (v.path === speedPath)    lastSpeedMs = v.value;
          }
        }
        recompute(opts);
      },
    );
  };

  plugin.stop = function () {
    unsubscribes.forEach(fn => fn());
    unsubscribes.length = 0;
    lastRpmHz = null;
    lastSpeedMs = null;
  };

  return plugin;
};
