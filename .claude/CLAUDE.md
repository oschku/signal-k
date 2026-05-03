# Boat Dashboard — Quicksilver 410 Fish / Tohatsu MFS30DETL

Quicksilver 410 Fish with Tohatsu MFS30DETL 30hp outboard.
Goal: chartplotter + engine data dashboard using open-source software.
Full project context (hardware, budget, deployment, dashboard layouts): [docs/project-context.md](../docs/project-context.md)
Technical data-flow reference: [docs/data-flow.md](../docs/data-flow.md)

---

## Simulator — sim.py

`sim.py` is a TCP server that mimics the wellenvogel ESP32-NMEA2000 WiFi gateway
connected to the Tohatsu engine.  The Tohatsu speaks NMEA 2000 natively; the
gateway re-emits those PGNs as `$PCDIN` sentences over TCP.

**Run:**
```bash
python3 sim.py                         # cruise scenario, port 10111
python3 sim.py --scenario idle
python3 sim.py --scenario wot
python3 sim.py --port 10111            # if 10110 is taken by signalk-server
```

### How it works

Each tick (1 Hz) the sim encodes the following N2K PGNs as binary payloads,
wraps them in `$PCDIN,<pgn-hex>,<time>,<src>,<data-hex>*<cs>` sentences, and
streams them over TCP to any connected client.

Sim emits only the PGNs the MFS30D actually produces (no oil pressure/temp,
no fuel-tank sender, no depth sounder).

| PGN    | Name                            | Fields emitted |
|--------|---------------------------------|----------------|
| 127488 | Engine Params, Rapid Update     | RPM, trim |
| 127489 | Engine Params, Dynamic          | coolant temp, alternator voltage, fuel rate, engine hours (oil fields N/A) |
| 127508 | Battery Status                  | voltage |
| 129025 | Position, Rapid Update          | lat, lon (dev/test only — production uses the FZ-G1's u-blox GPS via the OS) |
| 129026 | COG & SOG, Rapid Update         | COG (rad), SOG (m/s) |

Signal K's NMEA 0183 pipeline auto-detects `$PCDIN` and routes it through
canboatjs — same code path as a real gateway (see `nmea0183-signalk.js` →
`isN2KOver0183`).  No canboat external binary required.

### Signal K connection

In **Server → Connections → Add**:
- Input Type: `NMEA 0183`
- NMEA 0183 source: `TCP`
- Host: `127.0.0.1`
- Port: `10111`

Port `10110` is typically already bound by signalk-server itself; use `10111`
(sim default) or pass `--port` when starting the sim.

---

## Signal K Data Paths (SI units)

All values stored in SI; KIP converts for display.

| Signal K path | SI unit | Display | Source |
|---|---|---|---|
| `propulsion.port.revolutions` | Hz | RPM (×60) | PGN 127488 |
| `propulsion.port.drive.trimState` | ratio 0–1 | % | PGN 127488 |
| `propulsion.port.temperature` | K | °C (−273.15) | PGN 127489 |
| `propulsion.port.fuel.rate` | m³/s | L/h (×3.6e6) | PGN 127489 |
| `propulsion.port.runTime` | s | hours | PGN 127489 |
| `propulsion.port.alternatorVoltage` | V | V | PGN 127489 |
| `propulsion.port.slip` | ratio 0–1 | % | signalk-slippage |
| `propulsion.port.theoreticalSpeed` | m/s | kn (×1.944) | signalk-slippage |
| `electrical.batteries.0.voltage` | V | V | PGN 127508 |
| `tanks.fuel.0.capacity` | m³ | L (×1000) | signalk-fuel-monitor |
| `tanks.fuel.0.currentVolume` | m³ | L (×1000) | signalk-fuel-monitor |
| `tanks.fuel.0.currentLevel` | ratio 0–1 | % | signalk-fuel-monitor |
| `tanks.fuel.0.timeRange` | s | Hours | signalk-fuel-monitor |
| `tanks.fuel.0.distanceRange` | m | nm | signalk-fuel-monitor |
| `tanks.fuel.0.distancePerFuel` | m/m³ | nm/L | signalk-fuel-monitor |
| `tanks.fuel.0.fuelPerDistance` | m³/m | L/nm (×1,852,000) | signalk-fuel-monitor |
| `navigation.position` | {lat,lon} deg | deg | OS GPS (FZ-G1 u-blox) — PGN 129025 in sim |
| `navigation.speedOverGround` | m/s | kn (×1.944) | PGN 129026 |
| `navigation.courseOverGroundTrue` | rad | ° (×57.3) | PGN 129026 |

### Engine notes (MFS30D / MFS30DETL-specific)
- ECU only powers when engine is running, not key-on → no data until engine starts.
- No oil pressure or oil temperature sensor on this engine class → those fields
  are always N/A.
- No fuel-tank sender (portable 25 L tank) → `signalk-fuel-monitor` derives
  `tanks.fuel.0.currentLevel` by integrating `fuel.rate` over time, with a
  PUT-based refill handler.
- No depth sounder fitted → no `environment.depth.belowTransducer`.
- Position comes from the FZ-G1 tablet's built-in u-blox GPS (Windows location
  service); the sim emits PGN 129025 only for development.
- `@signalk/n2k-signalk` maps engine instance 0 → `propulsion.port` (not `.0`),
  and uses `drive.trimState` for tilt/trim and `temperature` for coolant.
  Use the `propulsion.port.*` paths everywhere downstream (dashboards, plugins).

---

## KIP Dashboards

Four dashboards generated from [scripts/build_kip_config.py](../scripts/build_kip_config.py):

| Dashboard  | Focus | Key widgets |
|---|---|---|
| Cruising   | planing speed at-a-glance | RPM radial 0–7000, SOG + minichart, coolant, fuel %, voltage, fuel hours, trim, engine hours, fuel rate, **Refilled** button |
| Trolling   | low-speed lure control    | big SOG (1 dec) with min/max, COG compass, 10 min SOG chart, position, RPM, trim, fuel %, range |
| Statistics | efficiency + diagnostics  | prop slip %, economy nm/L, slip / fuel rate / coolant / SOG / RPM charts, time left, range, fuel L, hours |
| Fishing    | solunar fishing windows   | rating radial 0–4, phase name, illumination %, active period, sunrise/sunset/moonrise/moonset clocks, next major + minor start/end + minutes-to-next |

History is captured via dataSets in `app.dataSets`. Each chart widget needs a
matching dataset whose `path|convertUnitTo|source|scale|period` line up
exactly — KIP looks them up by tuple. Numeric/gauge widgets that have a
minichart get an automatic `simple-chart-<uuid>` dataset created at runtime
(via `supportAutomaticHistoricalSeries: true`) — these don't need to be
pre-listed.

**Regenerate** after editing `scripts/build_kip_config.py`:
```bash
python3 scripts/build_kip_config.py    # rewrites signalk-config/applicationData/users/panasonic/kip/11.0.0.json
```
KIP requires a hard browser refresh to pick up server-side config changes.

### KIP widget gotchas (lessons from prior breakage)
- **Boolean-switch** (e.g. the Refilled button) takes a `paths` ARRAY with
  `pathID` plus a parallel `multiChildCtrls` array — NOT `paths.statePath`.
  The flag is `putEnable`, not `putEnabled`.
- **Numeric / gauge / simple-linear** widgets need `supportAutomaticHistoricalSeries: true`
  (otherwise minicharts stay blank) and path `suppressBootstrapNull: true`
  (otherwise widgets show 0 before the first sample arrives).
- **Chart datasets** match by tuple `(path, convertUnitTo, source, timeScale, period)`;
  the `label` is rebuilt by KIP as `path|convertUnitTo|source|scale|period`
  and any drift between widget config and dataset entry breaks history.
- **String values** (moon phase name, solunar rating name, ISO timestamps)
  need `widget-text` (paths.stringPath, pathType "string") or `widget-datetime`
  (paths.gaugePath, pathType "Date") — not `widget-numeric`.

### Day / night theme
- `app.autoNightMode: true` — auto-flips at sunset/sunrise based on `navigation.position`.
- The KIP top-bar has a manual day/night toggle (sun/moon icon) regardless.
- `redNightMode` adds a red filter on top of the night theme to preserve dark adaptation.
- `themeName: ""` uses KIP 3's Material 3 dynamic theme (follows system preference).

---

## Custom plugins

All custom plugins live under [plugins/](../plugins/) and are wired into
`signalk-config/package.json` as relative-path deps:

```json
"signalk-fuel-monitor": "file:../plugins/signalk-fuel-monitor",
"signalk-slippage":     "file:../plugins/signalk-slippage",
"signalk-solunar":      "file:../plugins/signalk-solunar"
```

A plain `npm install` from `signalk-config/` puts each into `node_modules/`,
which is where Signal K's plugin-discovery code looks (per
[Publishing to the AppStore](https://demo.signalk.org/documentation/Developing/Plugins/Publishing_to_The_AppStore.html)
the `signalk-node-server-plugin` keyword is what makes the package eligible).
Then enable each in **Server → Plugin Config**.

Note: because npm symlinks `file:` deps, plugins with their own npm
dependencies (e.g. `signalk-solunar` → `suncalc`) need a `npm install` inside
the plugin directory itself so Node can resolve the deps from the plugin's
real path.

### signalk-slippage ([plugins/signalk-slippage/](../plugins/signalk-slippage/))

Computes prop slip from RPM, gear ratio, prop pitch, and SOG. Defaults match
the Tohatsu MFS30DETL + Quicksilver 410 (gear 2.17:1, 13" pitch, SOG-based).
Publishes `propulsion.port.slip` (ratio) and `propulsion.port.theoreticalSpeed` (m/s).

```
propRPM            = engineRPM / gearRatio
theoreticalSpeed   = propRPM * pitch_m / 60
slip               = clamp(1 - actualSpeed / theoreticalSpeed, 0, 1)
```

Below `minRpm` (default 1500) the plugin holds slip null — the prop is too
lightly loaded for the formula to be meaningful.

### signalk-fuel-monitor ([plugins/signalk-fuel-monitor/](../plugins/signalk-fuel-monitor/))

Replaces the missing tank sender. Subscribes to `propulsion.port.fuel.rate`
and `navigation.speedOverGround`, integrates over wall-clock time, and publishes:

| Path | SI unit | KIP display |
|---|---|---|
| `tanks.fuel.0.capacity` | m³ | L |
| `tanks.fuel.0.currentVolume` | m³ | L (absolute remaining) |
| `tanks.fuel.0.currentLevel` | ratio | % |
| `tanks.fuel.0.timeRange` | s | Hours remaining at current burn |
| `tanks.fuel.0.distanceRange` | m | nm until empty at current speed + burn |
| `tanks.fuel.0.distancePerFuel` | m/m³ | nm/L (KIP "Fuel Distance" category) |
| `tanks.fuel.0.fuelPerDistance` | m³/m | L/nm (× 1,852,000 to display) |

Range/economy outputs are suppressed below configurable rate (`minFuelRateLph`,
default 0.5 L/h) and SOG (`minSogKnots`, default 0.5 kn) thresholds.

State persists to the plugin data dir so the estimate survives restarts.

### signalk-solunar ([plugins/signalk-solunar/](../plugins/signalk-solunar/))

Computes sunrise/sunset, moon phase + illumination, and solunar major/minor
fishing periods for the boat's current position. Subscribes to
`navigation.position` (with a Helsinki Harmaja fallback until a fix arrives)
and publishes under `environment.sun.*`, `environment.moon.*`, and
`environment.solunar.*`.

| Path | Type | Notes |
|---|---|---|
| `environment.sun.sunrise` / `.sunset` / `.solarNoon` / `.dawn` / `.dusk` | ISO date | Today's events |
| `environment.moon.moonrise` / `.moonset` | ISO date | Today's events |
| `environment.moon.phase` | ratio 0..1 | 0/1 = new, 0.5 = full |
| `environment.moon.phaseName` | string | "Full Moon", "Waxing Crescent", … |
| `environment.moon.illumination` | ratio 0..1 | Lit fraction of the disc |
| `environment.solunar.rating` | 0..4 | Day fishing rating |
| `environment.solunar.ratingName` | string | "Excellent" / "Good" / "Average" / … |
| `environment.solunar.activeKind` | string | `major` / `minor` / `none` right now |
| `environment.solunar.nextMajorStart` / `.nextMajorEnd` | ISO date | Next major fishing window |
| `environment.solunar.nextMinorStart` / `.nextMinorEnd` | ISO date | Next minor fishing window |
| `environment.solunar.minutesToNextMajor` / `.minutesToNextMinor` | min | Countdown to next start |
| `environment.solunar.majorPeriods` / `.minorPeriods` | array | All `{kind,centre,start,end}` windows over a 72 h horizon |

Major periods are ±60 min around moon upper/lower transit (overhead /
underfoot); minor periods are ±30 min around moonrise/moonset. Transits are
located by sampling moon altitude every 5 min over 72 h. Full astronomy
recompute fires when local date rolls over or position moves > 25 km; the
"active"/"next" outputs refresh every 60 s.

Refill handlers (PUT) — pick whichever the UI uses:
- `tanks.fuel.0.refill` — any truthy value resets to capacity (the KIP
  "Refilled" boolean-switch on the Underway dashboard is wired to this).
- `tanks.fuel.0.currentVolume` — set m³ explicitly (e.g. `0.025` = 25 L).
- `tanks.fuel.0.currentLevel` — set ratio 0..1.

---

## File Structure

```
signal-k/
├── .claude/
│   ├── CLAUDE.md              # this file (AI context)
│   └── settings.local.json
├── docs/
│   ├── data-flow.md           # N2K → PCDIN → Signal K technical deep-dive
│   └── project-context.md     # hardware, budget, deployment, dashboard layouts
├── plugins/
│   ├── signalk-fuel-monitor/  # rate-integrated fuel level + refill PUT
│   └── signalk-slippage/      # derived prop slip + theoretical speed
├── scripts/
│   └── build_kip_config.py    # generates the KIP dashboard JSON
├── signalk-config/            # Signal K data directory
│   ├── settings.json
│   ├── security.json
│   ├── plugin-config-data/
│   └── applicationData/
│       └── users/admin/kip/11.0.0.json   # KIP dashboards (generated)
├── sim.py                     # PCDIN/N2K gateway simulator
├── signalk-server             # launch wrapper
└── package.json
```

---

## Known Issues

- **Port 10110 conflict** — signalk-server binds 10110 on startup; run sim on `--port 10111`.
- **Secure mode** — PCDIN over NMEA 0183 TCP bypasses auth entirely (Signal K
  connects out to the sim), so secure mode does not affect data ingestion.
- **KIP caches layouts** — hard-refresh browser (Ctrl+Shift+R) if config changes don't appear.
- **KIP shared config name** — the dashboards file lives under the active config
  name (default: `default`). If you rename it in KIP, regenerate with the new name.
- **signalk-config vs ~/.signalk** — server is launched with `--configdir ./signalk-config`;
  plugins save state there, not to the global default.
