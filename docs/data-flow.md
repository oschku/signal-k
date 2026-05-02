# Data Flow: Tohatsu NMEA 2000 → Signal K

## Overview

```
Tohatsu MFS30DETL
  │  (NMEA 2000 / CAN bus, 250 kbit/s)
  │  Tohatsu data cable + T-piece
  ▼
M5Stack ATOM Lite + ATOMIC CANBus Base
  running wellenvogel esp32-nmea2000 firmware
  │  WiFi (802.11 b/g/n, 2.4 GHz)
  │  TCP stream, port 10110  ← sim uses 10111
  ▼  $PCDIN sentences (N2K binary wrapped in NMEA 0183)
Signal K Server (Node.js)
  │  @signalk/streams nmea0183-signalk.js
  │  isN2KOver0183() → canboatjs FromPgn.parseN2KOver0183()
  ▼
Signal K data model (vessels.self.*)
  │  WebSocket / REST API
  ▼
KIP dashboard  |  OpenCPN  |  signalk-fuel-monitor plugin
```

---

## Stage 1 — Tohatsu on NMEA 2000

The MFS30DETL ECU connects to the N2K backbone via the Tohatsu data cable
(part 3NV-76133-0 or equivalent).  The engine broadcasts these PGNs:

| PGN    | Update rate | Fields |
|--------|-------------|--------|
| 127488 | 100 ms | Engine Instance, Speed (RPM), Boost Pressure, Tilt/Trim |
| 127489 | 500 ms | Instance, Oil Pressure*, Oil Temp*, Coolant Temp, Alternator Voltage, Fuel Rate, Engine Hours, Discrete Status |

*Oil pressure and oil temperature are **not fitted** on the MFS30D — the
fields exist in PGN 127489 but always report "not available" (0xFFFF sentinel).
The boat also has no PGN 127505 (no fuel-tank sender — portable 25 L tank,
fuel level is derived by the `signalk-fuel-monitor` plugin) and no PGN 128267
(no depth sounder).

NMEA 2000 uses ISO 11783-3 (CAN) at 250 kbit/s.  Every field has a defined
resolution and unit in the canboat PGN definitions:

- RPM: uint16, 0.25 RPM/bit → raw value = RPM × 4
- Coolant temperature: uint16, 0.01 K/bit → raw = K × 100
- Alternator voltage: int16, 0.01 V/bit → raw = V × 100
- Fuel rate: int16, 0.1 L/h per bit → raw = (L/h) × 10
- Engine hours: uint32, 1 s/bit → raw = seconds
- Fluid level: int16, 0.004 %/bit → raw = % × 250

Multi-frame PGNs (>8 bytes, e.g. 127489 at 26 bytes) use the NMEA 2000
**Fast Packet Protocol**: the first CAN frame carries a sequence counter, total
length, and bytes 0–5; subsequent frames carry bytes 6-N in 7-byte chunks.

---

## Stage 2 — ESP32-NMEA2000 Gateway (wellenvogel firmware)

GitHub: https://github.com/wellenvogel/esp32-nmea2000

The gateway runs on an M5Stack ATOM Lite (ESP32-PICO) with an ATOMIC CANBus
base (CA-IS3050G isolated CAN transceiver).

### What it does
1. Reads raw N2K CAN frames from the bus (ISO 11783-3).
2. Reassembles multi-frame Fast Packet PGNs into complete payloads.
3. Converts to one of several output formats over WiFi.

### Output formats (configurable in web UI at 192.168.15.1)
- **NMEA 0183 sentences** — XDR, RPM, RMC, GGA, DPT, VHW (most compatible)
- **PCDIN sentences** — `$PCDIN,<pgn-hex>,<time>,<src>,<data-hex>*<cs>` — N2K binary wrapped verbatim in NMEA 0183 framing
- **YDWG RAW** — `HH:MM:SS.MMM R <canid> BB BB BB ...` over UDP (Yacht Devices format)

The sim uses **PCDIN** because:
- The raw N2K binary is preserved intact (no lossy NMEA 0183 conversion)
- Multi-frame PGNs are coalesced into one sentence (no Fast Packet reconstruction needed by the consumer)
- Signal K's NMEA 0183 pipeline auto-detects `$PCDIN` without any extra plugin
- Same transport (NMEA 0183 TCP) works in Signal K secure mode

### PCDIN sentence format
```
$PCDIN,<pgn>,<time>,<src>,<data>*<cs>
```

| Field   | Example      | Description |
|---------|--------------|-------------|
| `pgn`   | `01F200`     | PGN in 6-char uppercase hex (127488 = 0x1F200) |
| `time`  | `00000000`   | 32-bit timestamp, base-32, seconds since 2010-01-01 (≈0 is fine; canboatjs replaces with receive time) |
| `src`   | `17`         | N2K source address, 2-char hex (0x17 = 23 decimal, arbitrary for sim) |
| `data`  | `002AF800FF` | Full PGN payload as uppercase hex, any length |
| `cs`    | `4A`         | NMEA 0183 XOR checksum of everything between `$` and `*` |

Example for PGN 127488 at 5500 RPM, 35% trim:
```
$PCDIN,01F200,00000000,17,0058560023FFFF*23
```
Binary breakdown of `0058560023FFFF`:
- `00` = engine instance 0
- `5856` = 22104 LE → 22104 / 4 = 5526 RPM
- `0023` = boost pressure (low byte first, N/A)
- `FF` = trim int8 = -1 (≈35% in the signed encoding)
- `FF` = reserved

---

## Stage 3 — Signal K ingestion

Signal K server (Node.js) consumes the TCP stream via the
`providers/simple` pipeline with `type: NMEA0183` and `subOptions.type: tcp`.

### Code path (inside signalk-server node_modules)

```
@signalk/streams/simple.js
  nmea0183input()
    → tcp.js           connects to host:port, emits lines
    → liner.js         splits on \r\n
  dataTypeMapping.NMEA0183()
    → nmea0183-signalk.js
        _transform(line)
          isN2KOver0183(line)     ← checks line.startsWith('$PCDIN,')
            true → parseN2KOver0183(line)
                     FromPgn.parseN2KOver0183()   ← @canboat/canboatjs
                       parseString() → parsePCDIN()
                         Buffer.from(hexData, 'hex')
                         _parse(pgn, bitstream, length)
                     → decoded PGN object {pgn, fields, timestamp, src}
            → @signalk/n2k-signalk toDelta()
                     → Signal K delta {context, updates: [{source, values}]}
          false → standard NMEA 0183 parser
```

### canboatjs PGN field → Signal K path mapping

`@signalk/n2k-signalk` maps each decoded PGN field to a Signal K path:

Engine instance 0 maps to `propulsion.port.*` (1 → `starboard`, etc.). Several
field names also differ from what you'd guess from the PGN: tilt/trim lives at
`drive.trimState`, coolant at `temperature` (not `coolantTemperature`), and the
alternator output appears at `propulsion.port.alternatorVoltage` in addition to
`electrical.batteries.0.voltage` from PGN 127508.

| PGN + field | Signal K path | Conversion |
|---|---|---|
| 127488 Speed | `propulsion.port.revolutions` | RPM → Hz (/60) |
| 127488 Tilt/Trim | `propulsion.port.drive.trimState` | % → ratio (/100) |
| 127489 Temperature | `propulsion.port.temperature` | K (native) |
| 127489 Alternator Potential | `propulsion.port.alternatorVoltage` | V (native) |
| 127489 Fuel Rate | `propulsion.port.fuel.rate` | L/h → m³/s (/3.6e6) |
| 127489 Total Engine Hours | `propulsion.port.runTime` | s (native) |
| 127489 Oil Pressure | `propulsion.port.oilPressure` | Pa (always N/A on MFS30D) |
| 127489 Oil Temperature | `propulsion.port.oilTemperature` | K (always N/A on MFS30D) |
| 127508 Voltage | `electrical.batteries.0.voltage` | V (native) |
| 129025 Latitude/Longitude | `navigation.position` | degrees (native) |
| 129026 SOG | `navigation.speedOverGround` | m/s (native) |
| 129026 COG | `navigation.courseOverGroundTrue` | rad (native) |

PGN 127505 (Fluid Level) and PGN 128267 (Water Depth) are absent on this
boat — the corresponding Signal K paths come from the
`signalk-fuel-monitor` plugin (rate-integrated fuel level) and are not
populated for depth (`environment.depth.belowTransducer`).

---

## sim.py — how the binary encoding works

Each PGN encoder in `sim.py` uses `struct.pack` with little-endian layout
matching the canboat PGN definitions.  Examples:

```python
# PGN 127488 — 8 bytes
struct.pack("<BHHbBB",
    instance,                         # uint8
    int(rpm * 4) & 0xFFFF,            # uint16, 0.25 RPM/bit
    0xFFFF,                           # boost pressure N/A
    int(trim_pct),                    # int8 %
    0xFF, 0xFF,                       # reserved
)

# PGN 127489 — 26 bytes (coalesced multi-frame, no Fast Packet split needed)
struct.pack("<BHHHhhIHHBHHbb",
    instance,                         # uint8
    0xFFFF,                           # oil pressure: N/A on MFS30D
    0xFFFF,                           # oil temperature: N/A on MFS30D
    int(coolant_k * 100) & 0xFFFF,    # uint16 0.01 K
    int(voltage * 100),               # int16 0.01 V
    int(fuel_lph * 10),               # int16 0.1 L/h
    int(hours_s),                     # uint32 s
    0xFFFF, 0xFFFF,                   # coolant/fuel pressure N/A
    0xFF,                             # reserved
    0x0000, 0x0000,                   # discrete status
    0x7F, 0x7F,                       # load/torque N/A
)
```

Verified by piping output through `@canboat/canboatjs` `FromPgn.parseN2KOver0183()`
— all 5 PGNs decode to correct physical values.

---

## When the real hardware arrives

Replace the sim with the actual gateway:

1. Flash wellenvogel firmware on M5Stack ATOM Lite via browser flasher.
2. Configure the gateway at `192.168.15.1`:
   - WiFi client mode → connect to boat/home network
   - Enable **PCDIN** (or **NMEA 0183**) TCP output on port 10110
   - Listen-only mode (don't write to N2K bus)
   - Disable 120 Ω terminator (backbone already terminated)
3. In Signal K: update the TCP connection host from `127.0.0.1` to the ESP32's
   LAN IP (e.g. `192.168.1.42`) and port to `10110`.
4. The `sim.py` TCP provider entry in `signalk-config/settings.json` can stay;
   just toggle `"enabled": false` on it and add the real gateway connection.

### Alternative: YDWG RAW over UDP

If PCDIN output is not available in a firmware version, use:
- Gateway output: **YDWG RAW**, UDP, port 2002
- Signal K connection: Type `NMEA 2000`, source `ydwg02-canboatjs`, UDP, port 2002
- This uses Yacht Devices raw binary text format; canboatjs handles Fast Packet
  reassembly before passing to `n2k-signalk`.
