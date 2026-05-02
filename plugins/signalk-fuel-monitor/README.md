# signalk-fuel-monitor

Estimates fuel level by integrating engine fuel rate, since the Tohatsu MFS30D
on the Quicksilver 410 has no tank sender (portable 25 L tank). Also derives
time/distance range and fuel economy from the current rate and SOG.

## Output paths (all SI units — KIP converts for display)

### Fuel level
| Path | SI unit | KIP display |
|---|---|---|
| `tanks.fuel.0.capacity` | m³ | L (Volume category) |
| `tanks.fuel.0.currentVolume` | m³ | L |
| `tanks.fuel.0.currentLevel` | ratio 0..1 | % |

### Range
| Path | SI unit | KIP display | Notes |
|---|---|---|---|
| `tanks.fuel.0.timeRange` | s | Hours (Time category) | remaining ÷ current rate |
| `tanks.fuel.0.distanceRange` | m | nm (Length category) | timeRange × SOG |

### Economy
| Path | SI unit | KIP display | Conversion |
|---|---|---|---|
| `tanks.fuel.0.distancePerFuel` | m/m³ | nm/L (KIP "Fuel Distance") | ÷ 1,852,000 |
| `tanks.fuel.0.fuelPerDistance` | m³/m | L/nm | × 1,852,000 |

Range and economy outputs are suppressed when fuel rate < `minFuelRateLph`
(engine off) or SOG < `minSogKnots` (boat at rest).

**Example at 5500 RPM / 17.5 kn / 8 L/h with 25 L remaining:**
- timeRange → 3.1 h
- distanceRange → 54.7 nm
- distancePerFuel → 2.19 nm/L
- fuelPerDistance → 0.46 L/nm

## Refill (reset after refuelling)

Three PUT endpoints — whichever your UI uses:

```bash
# Boolean refill (KIP boolean-switch button → writes true)
curl -X PUT http://localhost:3000/signalk/v1/api/vessels/self/tanks/fuel/0/refill \
     -H 'Content-Type: application/json' -d '{"value": true}'

# Explicit volume in m³ (25 L = 0.025 m³)
curl -X PUT http://localhost:3000/signalk/v1/api/vessels/self/tanks/fuel/0/currentVolume \
     -H 'Content-Type: application/json' -d '{"value": 0.025}'

# Level as ratio (full = 1.0)
curl -X PUT http://localhost:3000/signalk/v1/api/vessels/self/tanks/fuel/0/currentLevel \
     -H 'Content-Type: application/json' -d '{"value": 1.0}'
```

State persists to `<plugin-data-dir>/fuel-state.json` and is reloaded on
restart — the estimate stays valid across server reboots.

## Install (from this repo)

The plugin is wired into `signalk-config/package.json` as a relative dep:

```json
"signalk-fuel-monitor": "file:../plugins/signalk-fuel-monitor"
```

Run `npm install` from `signalk-config/`, then enable in the admin UI under
Server → Plugin Config → Fuel Monitor. Configure tank capacity (default 25 L)
and the minimum thresholds for range output.
