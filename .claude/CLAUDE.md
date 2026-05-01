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

| PGN    | Name                            | Fields emitted |
|--------|---------------------------------|----------------|
| 127488 | Engine Params, Rapid Update     | RPM, trim |
| 127489 | Engine Params, Dynamic          | coolant temp, oil pressure/temp, alternator voltage, fuel rate, engine hours |
| 127505 | Fluid Level                     | fuel tank level %, capacity |
| 127508 | Battery Status                  | voltage |
| 128267 | Water Depth                     | depth |
| 129025 | Position, Rapid Update          | lat, lon |
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

| Signal K path | SI unit | Display | Source PGN |
|---|---|---|---|
| `propulsion.0.revolutions` | Hz | RPM (×60) | 127488 |
| `propulsion.0.trim` | ratio 0–1 | % | 127488 |
| `propulsion.0.coolantTemperature` | K | °C (−273.15) | 127489 |
| `propulsion.0.fuel.rate` | m³/s | L/h (×3.6e6) | 127489 |
| `propulsion.0.runTime` | s | hours | 127489 |
| `electrical.batteries.0.voltage` | V | V | 127489 / 127508 |
| `tanks.fuel.0.currentLevel` | ratio 0–1 | % | 127505 |
| `tanks.fuel.0.capacity` | m³ | L (×1000) | 127505 |
| `environment.depth.belowTransducer` | m | m | 128267 |
| `navigation.position` | {lat,lon} deg | deg | 129025 |
| `navigation.speedOverGround` | m/s | kn (×1.944) | 129026 |
| `navigation.courseOverGroundTrue` | rad | ° (×57.3) | 129026 |

### Engine notes (MFS30DETL-specific)
- ECU only powers when engine is running, not key-on → no data until engine starts
- No oil pressure sensor on this engine class → oil pressure always N/A
- Fuel level is calculated by `signalk-fuel-monitor` integrating `fuel.rate` over
  time (portable tank, no physical sender)

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
├── signalk-config/            # Signal K data directory
│   ├── settings.json
│   ├── security.json
│   └── plugin-config-data/
│       └── kip-config.json    # KIP dashboard layout (primary deliverable)
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
- **signalk-config vs ~/.signalk** — server is launched with `--configdir ./signalk-config`;
  plugins save state there, not to the global default.
