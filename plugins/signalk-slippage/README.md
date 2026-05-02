# signalk-slippage

Computes prop slippage from engine RPM, prop geometry, and SOG (or STW).

## Output paths

- `propulsion.port.theoreticalSpeed` — m/s the prop would push the boat at zero slip.
- `propulsion.port.slip` — ratio (0–1). 0 = no slip, 1 = engine spinning, boat not moving.

## Math

```
propRPM         = engineRPM / gearRatio
theoreticalSpeed[m/s] = propRPM * pitch[m] / 60
slip             = 1 - actualSpeed / theoreticalSpeed   (clamped to [0, 1])
```

Slip is only emitted above `minRpm` (default 1500). Below that the prop is
freewheeling and the formula breaks down.

## Install (from this repo)

The plugin is wired into `signalk-config/package.json` as a relative dep:

```json
"signalk-slippage": "file:../plugins/signalk-slippage"
```

So a plain `npm install` from `signalk-config/` puts it in `node_modules/`
and Signal K discovers it on next start. Enable and configure in the admin UI
under Server → Plugin Config → Prop Slippage.

## Defaults (Quicksilver 410 + Tohatsu MFS30DETL)

- gearRatio:    2.17
- pitchInches:  13
- speedSource:  sog
- minRpm:       1500
