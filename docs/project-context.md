# Project Context — Quicksilver 410 Fish Build

Full reference for the hardware, software, budget, deployment plan, and
dashboard design.  Not loaded into AI context by default; linked from CLAUDE.md.

---

## Hardware Components

### Display / Chartplotter
**Panasonic Toughbook FZ-G1 mk5** (ordered, €244 delivered from Germany)
- 10.1" IPS 1920×1200 (224 PPI), 800 nit, IP65, MIL-STD-810G, 1.2m drop
- i5-7300U (Kaby Lake 7th gen), 8 GB RAM, 128 GB SSD
- Built-in GPS (u-blox), LTE/4G, active stylus support
- Power: 16V 4.06A (65W) proprietary barrel connector
- Win 10 64-bit; target OS: Win 10 IoT LTSC 2021

### Engine
**Tohatsu MFS30DETL** (30hp, 4-stroke EFI)
- 526cc 3-cylinder, gear ratio 2.17:1, WOT 5250–6250 RPM
- 17.5A alternator, electric start/tilt/trim
- NMEA 2000 data cable required (Tohatsu part ~€80–120, verify if included)
- ECU only powers when engine running (no key-on data)

### NMEA 2000 Gateway (DIY ESP32)
- **M5Stack ATOM Lite** (C008) — €7.15, Mouser
- **M5Stack ATOMIC CANBus Base** (A103, CA-IS3050G isolated transceiver) — €6.45, Mouser
- Hammond 1551L enclosure (~€4)
- Wellenvogel ESP32-NMEA2000 firmware (open-source, browser-based web flasher)
- Powered from N2K bus 12V or USB-C
- **Total ~€35–40** vs. Hat Labs SH-wg €110 or YDWG-02 €205

### NMEA 2000 Backbone
Friend's starter kit (Micro-C format).  If incomplete: marinea.fi or
veneilijantähti.fi (~€30–40 for basic kit).

### Electrical
- MTX Energy 77 Ah leisure battery (Motonet €90)
- Master cutoff switch (~€20), battery box (~€20), inline fuse (~€10)
- CTEK or Biltema trickle charger (~€40–80)
- **Total ~€140–180**

### Mounting
- RAM Tab-Tite Universal Cradle (RAM-HOL-TAB20U) — fits 9–10.5", ~€80
- RAM Tough-Claw Small (RAP-B-400U) — clamps 16–29mm rails, ~€40
- RAM Composite Double Socket Arm (RAP-B-201U-A) — short arm, ~€15
- **Total ~€135** from Verkkokauppa.com or boatlocker.fi

### 12V Power for Tablet
- KFD/PWR+ car charger for FZ-G1: 12–24V DC → 16V 4.5A (~€20–25 from Amazon DE)
- Alternative: hardwired 12V→16V buck converter (~€15)

### Existing Equipment
- **Garmin Striker 7sv** fishfinder (no NMEA 2000 output — proprietary WiFi only)
  - Stays as dedicated sonar display, independent from tablet
  - QuickDraw Contours bathymetry exportable via ActiveCaptain → KAP for OpenCPN
- 25L metal portable fuel tank
- Navionics on phone (subscription expires June 2026) — trip planning backup

---

## Software Stack

### Operating System
**Windows 10 IoT Enterprise LTSC 2021** (€15–30 license, deferred until needed)
- Supported until January 2032
- i5-7300U is not Win 11 compatible (7th gen vs 8th gen requirement)
- Auto-login via netplwiz; auto-start: Signal K + OpenCPN + Chrome kiosk to KIP
- Sleep: 30 min on battery, never on 12V power

### Navigation
**OpenCPN** (free, open-source)
- Charts: Traficom Finnish ENC (free non-commercial, vayla.fi)
- Bathymetry: SYKE open data, Väylävirasto coastal data
- GPS: internal FZ-G1 u-blox module

**Alternatives evaluated:**
- TimeZero Navigator (~€90/yr) — best Windows-native UX
- C-MAP with Reveal X (~€30–50/yr)
- qtVlm (free) — backup/secondary chartplotter

### Engine Data & Dashboards
**Signal K Server** 2.26.0, Node.js, global install via npm.
- Config: `--configdir ./signalk-config`
- Admin: `http://localhost:3000/admin/`
- Data Browser: `http://localhost:3000/admin/#/databrowser`

**Signal K Plugins:**
- `@mxtommy/kip` — primary dashboard (drag-drop gauge designer)
- `signalk-fuel-monitor` — fuel consumption tracking
- `signalk-derived-data` — true wind, trip stats
- Optional later: `signalk-to-influxdb`, `signalk-mqtt-gw`

**KIP Dashboard:** `http://localhost:3000/@mxtommy/kip/`
- Drag-drop layout; multiple pages swipeable
- Color zones, alarms, unit conversion (SI → display units)
- Config stored in `signalk-config/plugin-config-data/kip-config.json`

---

## KIP Dashboard Configuration

### Widget Schema Pattern
```json
{
  "uuid": "<uuid4>",
  "type": "gauge-radial",
  "options": {
    "paths": { "gaugePath": "self.propulsion.0.revolutions" },
    "gaugeScale": { "min": 0, "max": 7000, "decimals": 0 },
    "gaugeUnits": "RPM",
    "title": "Engine RPM",
    "zones": [
      { "lower": 0,    "upper": 5250, "state": "normal" },
      { "lower": 5250, "upper": 6250, "state": "warn"   },
      { "lower": 6250, "upper": 7000, "state": "alarm"  }
    ]
  },
  "layout": { "x": 0, "y": 0, "w": 4, "h": 3 }
}
```

Layout is a 12-column grid.  Generate configs programmatically with Python
(`uuid.uuid4()` for IDs) rather than hand-editing JSON.

### Widget Types
| Type | Use |
|---|---|
| `gauge-radial` | RPM, speed, depth |
| `gauge-linear` | fuel level, trim |
| `numeric` | coolant temp, voltage, engine hours |
| `line-chart` | RPM history, fuel rate over time |
| `text` / `datetime` | static labels, clock |
| `wind-gauge` | if wind sensor added later |

### Recommended Dashboard Pages

**Page 1 — Underway** (while planing)
- Big radial: RPM (0–7000, yellow 5250–6250, red >6250)
- Numeric large: Depth (m, safety-critical)
- Numeric: SOG (kn, 1 decimal)
- Linear gauge: Fuel Level (%, red <25%, yellow 25–50%)
- Numeric: Coolant Temp (°C, alarm ≥90°C)
- Numeric small: Voltage, Engine Hours

**Page 2 — Fishing** (low speed / trolling)
- Big numeric: Depth
- Numeric: SOG (1 decimal for trolling speed control)
- Numeric: COG / Heading
- Numeric: Trim (%)
- Position: Lat/Lon

**Page 3 — Engine Detail** (diagnostics)
- All engine values: RPM, fuel rate L/h, fuel remaining L, coolant, voltage, hours, trim
- Line charts: RPM + fuel rate last 5 min

### Screen Constraints (FZ-G1)
- 1920×1200, 10.1" (~16:10)
- Split-screen: OpenCPN left (960px) + KIP right (960px)
- Touch targets: ≥44×44px for finger; stylus allows smaller
- High contrast for sun readability

---

## Signal K Unit Conversions

| Quantity | SK unit | Display | Factor |
|---|---|---|---|
| RPM | Hz | RPM | ×60 |
| Temperature | K | °C | −273.15 |
| Speed | m/s | knots | ×1.944 |
| Fuel rate | m³/s | L/h | ×3.6e6 |
| Distance | m | nm | ÷1852 |
| Pressure | Pa | bar | ÷100000 |
| Angle | rad | ° | ×57.296 |
| Ratio | 0–1 | % | ×100 |

---

## Deployment Plan

### Week 1 — Tablet arrives
1. Verify FZ-G1 is MK5 (i5-7300U CPU confirms it)
2. Test GPS, check screen brightness outdoors
3. Install Win 10 IoT LTSC 2021 or keep existing Win 10
4. Install Node.js, Signal K Server, KIP plugin
5. Clone repo, point Signal K to `./signalk-config`
6. Confirm KIP dashboard loads with simulated data
7. Configure auto-login + auto-start

### Week 2 — ESP32 + engine arrive
1. Flash wellenvogel firmware via browser
2. Wire N2K cable to ATOMIC base (Red=V+, Black=GND, White=CAN-H, Blue=CAN-L)
3. Seal in enclosure, connect to N2K backbone
4. Configure ESP32 WiFi + PCDIN TCP output on port 10110
5. Update Signal K connection host to ESP32 LAN IP
6. Start engine → verify PGNs appear in Data Browser

### Week 3 — Boat integration
1. Install battery + master switch + fuse + charger
2. Wire 12V to N2K bus power tap and tablet charger
3. Mount RAM hardware to handrails (zero hull modification)
4. Install OpenCPN + Traficom ENC charts
5. Configure split-screen layout
6. Sea trial, tune alarm thresholds from real engine data
7. Final Git commit with production config

---

## Budget Summary (May 2026)

| Category | Items | Cost (EUR) |
|---|---|---|
| Display | FZ-G1 mk5, stylus, car charger | ~€280–300 |
| Gateway | M5Stack ATOM + CANBus base, enclosure | ~€35–50 |
| NMEA 2000 | Tohatsu data cable, backbone kit | €0–160 |
| Electrical | Battery, switch, charger, accessories | ~€140–180 |
| Mounting | RAM cradle + arm + clamp | ~€135 |
| Software | Win 10 LTSC (deferred), all else free | €0–30 |
| **TOTAL** | | **€650–770** |

**vs. Garmin GPSMAP 753xsv + GMI 20 + install: ~€1480** → savings ~€710–830.

---

## Known Issues

**FZ-G1:**
- MK4 vs MK5 confusion in listings — CPU i5-7300U definitively confirms MK5
- Win 11 unsupported on 7th gen; use Win 10 LTSC 2021

**Tohatsu NMEA 2000:**
- ECU only powers when engine running (no key-on data)
- No oil pressure sensor — don't expect this data
- Data cable may need interface adapter; confirm with dealer

**Signal K + KIP:**
- Config changes require server restart
- KIP caches layouts; hard-refresh (Ctrl+Shift+R) if changes don't show
- `signalk-config/` is the config dir (not `~/.signalk`)

**OpenCPN + Finnish Charts:**
- Traficom ENC: download fresh seasonally from vayla.fi
- SYKE bathymetry requires QGIS → KAP conversion for OpenCPN raster overlay
- No auto-routing; manual waypoint clicking

---

## Success Criteria

**MVP:**
- [ ] OpenCPN displays Finnish ENC charts with internal GPS
- [ ] KIP displays live RPM, coolant temp, voltage, fuel rate from engine
- [ ] Calculated fuel remaining updates based on fuel rate
- [ ] Basic alarm thresholds (RPM redline, coolant overtemp)
- [ ] All systems survive 2-hour sea trial

**V1.0:**
- [ ] Three KIP pages (Underway, Fishing, Engine Detail)
- [ ] Color zones and alarms tuned to real engine behavior
- [ ] Split-screen layout (OpenCPN + KIP) ergonomic
- [ ] Auto-login + auto-start on tablet
- [ ] Git repo fully documents build

**Future:**
- [ ] AIS receiver, wind sensor
- [ ] Anchor watch alarm
- [ ] InfluxDB data logging
- [ ] Striker QuickDraw → OpenCPN overlay
- [ ] MQTT bridge to home server

---

## Reference Links

**Hardware:** m5stack.com, mouser.fi, botland.store, verkkokauppa.com, boatlocker.fi

**Software:** signalk.org, github.com/mxtommy/Kip, wellenvogel.de/software/esp32, opencpn.org

**Charts:** vayla.fi (Traficom ENC), paikkatieto.ymparisto.fi (SYKE bathymetry)

**Marine suppliers (Finland):** motonet.fi, marinea.fi, veneilijantahti.fi

**Community:** signalk-dev.slack.com, github.com/mxtommy/Kip (issues), veneily.fi, kippari.fi

---

*Last updated: May 2026 — parts ordering phase, simulator working, KIP design in progress.*
*Next milestone: FZ-G1 delivery (est. May 6–12), ESP32 delivery (est. May 3–7)*
