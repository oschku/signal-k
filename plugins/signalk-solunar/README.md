# signalk-solunar

Sunrise/sunset, moon phase, and solunar fishing periods for the boat's
current position. Built as a data source for a fishing dashboard.

## How solunar works

Solunar theory predicts that fish (and most game animals) feed most actively
during specific lunar windows:

- **Major periods** — ~2 hours centred on **moon overhead** and **moon underfoot**
  (upper / lower transit). Strongest activity.
- **Minor periods** — ~1 hour centred on **moonrise** and **moonset**.
  Secondary activity peaks.

Activity is highest near new and full moons, and is amplified further when
a major period coincides with sunrise or sunset.

## Inputs

- `navigation.position` — used to localise sun & moon events.
  If no position has been received yet, falls back to a configurable lat/lon
  (default = Helsinki Harmaja, 60.11°N 24.98°E).

## Outputs

All times are ISO-8601 strings; numeric values are SI / unitless.

| Path                                   | Type     | Meaning |
|----------------------------------------|----------|---------|
| `environment.sun.sunrise`              | ISO date | Today's sunrise |
| `environment.sun.sunset`               | ISO date | Today's sunset |
| `environment.sun.solarNoon`            | ISO date | Sun at upper transit |
| `environment.sun.dawn` / `.dusk`       | ISO date | Civil twilight |
| `environment.sun.nauticalDawn` / `Dusk`| ISO date | Nautical twilight |
| `environment.sun.nightEnd` / `.night`  | ISO date | Astronomical twilight |
| `environment.moon.moonrise`            | ISO date | Today's moonrise |
| `environment.moon.moonset`             | ISO date | Today's moonset |
| `environment.moon.phase`               | 0..1     | 0/1 = new, 0.5 = full |
| `environment.moon.phaseName`           | string   | "Full Moon", "Waxing Crescent", … |
| `environment.moon.illumination`        | 0..1     | Illuminated fraction of the disc |
| `environment.solunar.rating`           | 0..4     | Day rating (phase score + sun-overlap bonus) |
| `environment.solunar.ratingName`       | string   | "Excellent", "Good", … |
| `environment.solunar.activeKind`       | string   | `major` / `minor` / `none` right now |
| `environment.solunar.nextMajorStart`   | ISO date | Start of the next major period |
| `environment.solunar.nextMajorEnd`     | ISO date | End of the next major period |
| `environment.solunar.nextMinorStart`   | ISO date | Start of the next minor period |
| `environment.solunar.nextMinorEnd`     | ISO date | End of the next minor period |
| `environment.solunar.minutesToNextMajor` | number | Minutes from now to next major start |
| `environment.solunar.minutesToNextMinor` | number | Minutes from now to next minor start |
| `environment.solunar.majorPeriods`     | array    | All major windows in the 72 h horizon: `{kind, centre, start, end}` |
| `environment.solunar.minorPeriods`     | array    | All minor windows in the 72 h horizon |
| `environment.solunar.activeMajor`      | object   | Active major window (or null) |
| `environment.solunar.activeMinor`      | object   | Active minor window (or null) |
| `environment.solunar.nextMajor`        | object   | Full next-major object `{kind, centre, start, end}` |
| `environment.solunar.nextMinor`        | object   | Full next-minor object |

## Rating algorithm

```
phaseScore  = cos(2π · 2 · phase) · 0.5 + 0.5     // 0..1, peaks at new + full
sunBonus    = any of today's major periods within ±60 min of sunrise/sunset ? 1 : 0
rating      = clamp(phaseScore · 3 + sunBonus, 0, 4)
```

## Configuration

| Key              | Default                  | Notes |
|------------------|--------------------------|-------|
| `positionPath`   | `navigation.position`    | Source path for current position |
| `defaultLatitude`  | `60.11`                | Used until first fix |
| `defaultLongitude` | `24.98`                | Used until first fix |
| `tickSeconds`    | `60`                     | How often to refresh "active"/"next" outputs |
| `positionMoveKm` | `25`                     | Triggers full astronomy recompute when boat moves this far |

## Notes

- Moon transits are found by sampling `SunCalc.getMoonPosition` altitude every
  5 min over a 72 h window centred on today; that's well below the ±60 min
  major-window half-width.
- Astronomy recomputes when the local date rolls over or position moves more
  than `positionMoveKm`. The "active period" / "next period" / "minutes to
  next" fields refresh every `tickSeconds`.
- Output paths follow Signal K's `environment.*` convention; phase/illumination
  are unitless ratios so KIP gauges can render them as percentages directly.
