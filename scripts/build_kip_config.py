#!/usr/bin/env python3
"""
Generate the KIP dashboard configuration for the Quicksilver 410 / Tohatsu MFS30DETL build.

KIP config lives at:
  signalk-config/applicationData/users/<user>/kip/<schemaVersion>.json

The file is `{ "<sharedConfigName>": IConfig }` where IConfig = { app, theme, dashboards }.
The user's currently-active config is named "default".

Run:  python3 scripts/build_kip_config.py
This rewrites the user config with four dashboards: Cruising, Trolling,
Statistics, Fishing — plus the history datasets the charts depend on.

KIP-specific notes (gleaned from comparing against a known-good live config):

  • Numeric / gauge / simple-linear widgets must set
    `supportAutomaticHistoricalSeries: true` so KIP creates and binds the
    auto `simple-chart-<uuid>` dataset that backs minicharts.
  • Numeric paths should set `suppressBootstrapNull: true` so the widget
    shows "—" rather than 0 before the first sample arrives.
  • Chart datasets are matched to chart widgets by
    (path, convertUnitTo, source, timeScale, period). The label format
    that KIP writes back is exactly `path|convertUnitTo|source|scale|period`.
  • Boolean-switch (used for the Refilled button) takes a `paths` ARRAY
    with `pathID` and a parallel `multiChildCtrls` array; the field is
    `putEnable` (not `putEnabled`).
"""
import json
import uuid
from pathlib import Path

REPO = Path(__file__).resolve().parent.parent
KIP_CONFIG = REPO / "signalk-config/applicationData/users/panasonic/kip/11.0.0.json"
SHARED_NAME = "default"
CONFIG_VERSION = 12

# ─── NOTE ───────────────────────────────────────────────────────────────────
# Do NOT run this script while you are experimenting with the KIP UI — it will
# overwrite the live config file. Run it only when you want to reset back to
# the generated baseline: python3 scripts/build_kip_config.py

# Stable UUIDs so re-running produces the same file (= clean diffs)
NS = uuid.UUID("a4d2c6ce-1f84-4b9c-8a9b-2f3e4d5a6b7c")
def uid(*parts: str) -> str:
    return str(uuid.uuid5(NS, "/".join(parts)))


# ─── SI base units per Signal K path (used for chart datasets) ─────────────
BASE_UNITS = {
    "self.navigation.speedOverGround":        "m/s",
    "self.navigation.courseOverGroundTrue":   "rad",
    "self.propulsion.port.revolutions":       "Hz",
    "self.propulsion.port.fuel.rate":         "m3/s",
    "self.propulsion.port.temperature":       "K",
    "self.propulsion.port.slip":              "ratio",
    "self.propulsion.port.drive.trimState":   "ratio",
    "self.propulsion.port.runTime":           "s",
    "self.propulsion.port.alternatorVoltage": "V",
    "self.electrical.batteries.0.voltage":    "V",
    "self.tanks.fuel.0.currentLevel":         "ratio",
    "self.tanks.fuel.0.currentVolume":        "m3",
    "self.tanks.fuel.0.timeRange":            "s",
    "self.tanks.fuel.0.distanceRange":        "m",
    "self.tanks.fuel.0.distancePerFuel":      "m/m3",
    "self.tanks.fuel.0.fuelPerDistance":      "m3/m",
    "self.environment.moon.illumination":     "ratio",
    "self.environment.moon.phase":            "ratio",
    "self.environment.solunar.rating":        "",
    "self.environment.solunar.minutesToNextMajor": "min",
    "self.environment.solunar.minutesToNextMinor": "min",
}


# ─── Chart datasets (history tracking) ─────────────────────────────────────
# Each entry must match a data-chart widget exactly: same (path, unit, scale,
# period). KIP looks up chart history by these four values; if any one drifts,
# the chart shows "no data". Auto `simple-chart-<uuid>` datasets that back
# minichart-equipped numerics are created by KIP at runtime — don't list them.
DATASETS = [
    # (path, convertUnitTo, scale, period)
    ("self.navigation.speedOverGround",   "knots",   "minute", 10),  # trolling SOG
    ("self.navigation.speedOverGround",   "knots",   "minute", 30),  # stats SOG
    ("self.propulsion.port.revolutions",  "rpm",     "minute", 30),  # stats RPM
    ("self.propulsion.port.fuel.rate",    "l/h",     "hour",   1),   # stats fuel rate
    ("self.propulsion.port.temperature",  "celsius", "minute", 30),  # stats coolant
    ("self.propulsion.port.slip",         "percent", "minute", 30),  # stats slip
    ("self.tanks.fuel.0.distancePerFuel", "nm/l",    "minute", 10),  # cruising economy (if added)
]


def chart_dataset(path, unit, scale, period):
    base = BASE_UNITS.get(path, "")
    label = f"{path}|{unit}|default|{scale}|{period}"
    return {
        "uuid": uid("ds", label),
        "path": path,
        "pathSource": "default",
        "baseUnit": base,
        "timeScaleFormat": scale,
        "period": period,
        "label": label,
        "editable": False,
    }


# ─── Widget builders ──────────────────────────────────────────────────────

def w_numeric(slug, x, y, w, h, *, name, path, unit, decimals=1,
              minichart=False, color="contrast", show_min_max=False,
              y_min=None, y_max=None, sk_unit_filter=None):
    """Numeric value with optional minichart trail.

    `supportAutomaticHistoricalSeries: True` is what makes the minichart show
    history; KIP auto-registers a `simple-chart-<uuid>` dataset for the path.
    `suppressBootstrapNull: True` keeps the widget blank until a real sample
    arrives instead of showing 0.
    """
    wid = uid("w", slug)
    return {
        "x": x, "y": y, "w": w, "h": h,
        "id": wid,
        "selector": "widget-host2",
        "input": {"widgetProperties": {
            "type": "widget-numeric",
            "uuid": wid,
            "config": {
                "supportAutomaticHistoricalSeries": True,
                "displayName": name,
                "filterSelfPaths": True,
                "paths": {"numericPath": {
                    "description": "Numeric Data",
                    "path": path,
                    "source": "default",
                    "pathType": "number",
                    "suppressBootstrapNull": True,
                    "isPathConfigurable": True,
                    "convertUnitTo": unit,
                    "showPathSkUnitsFilter": True,
                    "pathSkUnitsFilter": sk_unit_filter,
                    "sampleTime": 500,
                }},
                "showMax": show_min_max,
                "showMin": show_min_max,
                "numDecimal": decimals,
                "showMiniChart": minichart,
                "yScaleMin": y_min if y_min is not None else 0,
                "yScaleMax": y_max if y_max is not None else 100,
                "inverseYAxis": False,
                "verticalChart": False,
                "color": color,
                "enableTimeout": False,
                "dataTimeout": 5,
                "ignoreZones": False,
            },
        }},
    }


def w_radial(slug, x, y, w, h, *, name, path, unit, lower, upper,
             decimals=0, color="contrast", subtype="measuring",
             scale_start=180, sk_unit_filter=None):
    wid = uid("w", slug)
    return {
        "x": x, "y": y, "w": w, "h": h,
        "id": wid,
        "selector": "widget-host2",
        "input": {"widgetProperties": {
            "type": "widget-gauge-ng-radial",
            "uuid": wid,
            "config": {
                "supportAutomaticHistoricalSeries": True,
                "displayName": name,
                "filterSelfPaths": True,
                "paths": {"gaugePath": {
                    "description": "Numeric Data",
                    "path": path,
                    "source": "default",
                    "pathType": "number",
                    "suppressBootstrapNull": True,
                    "isPathConfigurable": True,
                    "showPathSkUnitsFilter": True,
                    "pathSkUnitsFilter": sk_unit_filter,
                    "convertUnitTo": unit,
                    "sampleTime": 500,
                }},
                "displayScale": {"lower": lower, "upper": upper, "type": "linear"},
                "gauge": {
                    "type": "ngRadial",
                    "subType": subtype,
                    "enableTicks": True,
                    "enableNeedle": True,
                    "enableProgressbar": True,
                    "highlightsWidth": 5,
                    "scaleStart": scale_start,
                    "barStartPosition": "left",
                },
                "numInt": 1,
                "numDecimal": decimals,
                "enableTimeout": False,
                "color": color,
                "dataTimeout": 5,
                "ignoreZones": False,
            },
        }},
    }


def w_compass(slug, x, y, w, h, *, name, path, color="purple"):
    wid = uid("w", slug)
    return {
        "x": x, "y": y, "w": w, "h": h,
        "id": wid,
        "selector": "widget-host2",
        "input": {"widgetProperties": {
            "type": "widget-gauge-ng-compass",
            "uuid": wid,
            "config": {
                "displayName": name,
                "filterSelfPaths": True,
                "paths": {"gaugePath": {
                    "description": "Numeric Data",
                    "path": path,
                    "source": "default",
                    "pathType": "number",
                    "isPathConfigurable": True,
                    "showPathSkUnitsFilter": False,
                    "pathSkUnitsFilter": "rad",
                    "showConvertUnitTo": False,
                    "convertUnitTo": "deg",
                    "sampleTime": 500,
                }},
                "gauge": {
                    "type": "ngRadial",
                    "subType": "marineCompass",
                    "enableTicks": True,
                    "compassUseNumbers": True,
                    "showValueBox": True,
                },
                "enableTimeout": False,
                "color": color,
                "dataTimeout": 5,
            },
        }},
    }


def w_simple_linear(slug, x, y, w, h, *, name, path, unit, lower, upper,
                    decimals=1, color="green", sk_unit_filter=None,
                    ignore_zones=False):
    wid = uid("w", slug)
    return {
        "x": x, "y": y, "w": w, "h": h,
        "id": wid,
        "selector": "widget-host2",
        "input": {"widgetProperties": {
            "type": "widget-simple-linear",
            "uuid": wid,
            "config": {
                "supportAutomaticHistoricalSeries": True,
                "displayName": name,
                "filterSelfPaths": True,
                "paths": {"gaugePath": {
                    "description": "Numeric Data",
                    "path": path,
                    "source": "default",
                    "pathType": "number",
                    "isPathConfigurable": True,
                    "showPathSkUnitsFilter": True,
                    "pathSkUnitsFilter": sk_unit_filter,
                    "convertUnitTo": unit,
                    "sampleTime": 500,
                }},
                "displayScale": {"lower": lower, "upper": upper, "type": "linear"},
                "gauge": {"type": "simpleLinear", "unitLabelFormat": "full"},
                "numInt": 1,
                "numDecimal": decimals,
                "ignoreZones": ignore_zones,
                "color": color,
                "enableTimeout": False,
                "dataTimeout": 5,
            },
        }},
    }


def w_position(slug, x, y, w, h, *, name="Position"):
    wid = uid("w", slug)
    return {
        "x": x, "y": y, "w": w, "h": h, "minW": 1, "minH": 1,
        "id": wid,
        "selector": "widget-host2",
        "input": {"widgetProperties": {
            "type": "widget-position",
            "uuid": wid,
            "config": {
                "displayName": name,
                "filterSelfPaths": True,
                "paths": {
                    "longPath": {
                        "description": "Longitude",
                        "path": "self.navigation.position.longitude",
                        "source": "default",
                        "pathType": "number",
                        "isPathConfigurable": True,
                        "convertUnitTo": "longitudeMin",
                        "showPathSkUnitsFilter": True,
                        "pathSkUnitsFilter": None,
                        "sampleTime": 500,
                    },
                    "latPath": {
                        "description": "Latitude",
                        "path": "self.navigation.position.latitude",
                        "source": "default",
                        "pathType": "number",
                        "isPathConfigurable": True,
                        "convertUnitTo": "latitudeMin",
                        "showPathSkUnitsFilter": True,
                        "pathSkUnitsFilter": None,
                        "sampleTime": 500,
                    },
                },
                "color": "grey",
                "enableTimeout": False,
                "dataTimeout": 5,
            },
        }},
    }


def w_chart(slug, x, y, w, h, *, name, path, convert_unit, period, scale="minute",
            color="orange", y_min=None, y_max=None,
            show_average=True, show_max=False):
    wid = uid("w", slug)
    return {
        "x": x, "y": y, "w": w, "h": h,
        "id": wid,
        "selector": "widget-host2",
        "input": {"widgetProperties": {
            "type": "widget-data-chart",
            "uuid": wid,
            "config": {
                "displayName": name,
                "color": color,
                "filterSelfPaths": True,
                "datachartPath": path,
                "datachartSource": "default",
                "convertUnitTo": convert_unit,
                "timeScale": scale,
                "period": period,
                "numDecimal": 1,
                "inverseYAxis": False,
                "datasetAverageArray": "sma",
                "showDataPoints": False,
                "showAverageData": True,
                "trackAgainstAverage": False,
                "showDatasetMinimumValueLine": False,
                "showDatasetMaximumValueLine": show_max,
                "showDatasetAverageValueLine": show_average,
                "showDatasetAngleAverageValueLine": False,
                "showLabel": True,
                "showTimeScale": True,
                "startScaleAtZero": True,
                "verticalChart": False,
                "showYScale": True,
                "yScaleSuggestedMin": y_min,
                "yScaleSuggestedMax": y_max,
                "enableMinMaxScaleLimit": False,
                "yScaleMin": None,
                "yScaleMax": None,
                "timeScaleFormat": scale,
                "invertData": False,
                "verticalGraph": False,
            },
        }},
    }


def w_datetime(slug, x, y, w, h, *, name, path="self.environment.time",
               fmt="HH:mm", tz="Europe/Helsinki", color="contrast"):
    wid = uid("w", slug)
    return {
        "x": x, "y": y, "w": w, "h": h,
        "id": wid,
        "selector": "widget-host2",
        "input": {"widgetProperties": {
            "type": "widget-datetime",
            "uuid": wid,
            "config": {
                "displayName": name,
                "filterSelfPaths": True,
                "paths": {"gaugePath": {
                    "description": "Date / Time",
                    "path": path,
                    "source": "default",
                    "pathType": "Date",
                    "isPathConfigurable": True,
                    "sampleTime": 1000,
                }},
                "dateFormat": fmt,
                "dateTimezone": tz,
                "color": color,
                "enableTimeout": False,
                "dataTimeout": 5,
            },
        }},
    }


def w_text(slug, x, y, w, h, *, name, path, color="contrast"):
    """String value display (e.g. moon phase name, solunar rating name)."""
    wid = uid("w", slug)
    return {
        "x": x, "y": y, "w": w, "h": h,
        "id": wid,
        "selector": "widget-host2",
        "input": {"widgetProperties": {
            "type": "widget-text",
            "uuid": wid,
            "config": {
                "displayName": name,
                "filterSelfPaths": True,
                "paths": {"stringPath": {
                    "description": "String Data",
                    "path": path,
                    "source": "default",
                    "pathType": "string",
                    "isPathConfigurable": True,
                    "sampleTime": 500,
                }},
                "color": color,
                "enableTimeout": False,
                "dataTimeout": 5,
            },
        }},
    }


def w_button(slug, x, y, w, h, *, name, path, ctrl_label,
             color="green", value=True, is_numeric=False):
    """Boolean / numeric PUT switch — used for the Refilled button.

    KIP's widget-boolean-switch takes a paths ARRAY (one per controlled
    element) plus a parallel `multiChildCtrls` array describing each control.
    `is_numeric=False` issues a boolean PUT (the fuel-monitor plugin treats
    any truthy PUT to `tanks.fuel.0.refill` as "tank is full").
    `is_numeric=True` issues a numeric PUT carrying `value` (e.g. ratio 1.0
    written to `tanks.fuel.0.currentLevel`).
    """
    wid = uid("w", slug)
    pid = uid("p", slug)
    return {
        "x": x, "y": y, "w": w, "h": h, "minW": 1, "minH": 2,
        "id": wid,
        "selector": "widget-host2",
        "input": {"widgetProperties": {
            "type": "widget-boolean-switch",
            "uuid": wid,
            "config": {
                "displayName": name,
                "showLabel": True,
                "filterSelfPaths": True,
                "paths": [{
                    "description": ctrl_label,
                    "path": path,
                    "pathID": pid,
                    "source": "default",
                    "pathType": "number" if is_numeric else "boolean",
                    "zonesOnlyPaths": False,
                    "isPathConfigurable": True,
                    "showPathSkUnitsFilter": False,
                    "pathSkUnitsFilter": None,
                    "convertUnitTo": "ratio" if is_numeric else "unitless",
                    "sampleTime": 500,
                    "supportsPut": True,
                }],
                "enableTimeout": False,
                "dataTimeout": 5,
                "color": color,
                "zonesOnlyPaths": False,
                "putEnable": True,
                "putMomentary": True,
                "multiChildCtrls": [{
                    "ctrlLabel": ctrl_label,
                    "type": "2",
                    "pathID": pid,
                    "color": color,
                    "isNumeric": is_numeric,
                    "value": value,
                }],
            },
        }},
    }


# ─── Grid: 24 columns, variable height rows ──────────────────────────────
# No depth sounder. Fuel level from signalk-fuel-monitor (rate-integrated).
# Position from FZ-G1 u-blox GPS via Windows OS location service.

# ═══════════════════════════════════════════════════════════════════════════
# Dashboard 1 — Cruising
# Goal: everything needed at planing speed in one glance.
# ═══════════════════════════════════════════════════════════════════════════
cruising_widgets = [
    # ── Row 0-11 ── RPM radial (hero) | SOG | Coolant
    w_radial("c_rpm", 0, 0, 12, 12,
             name="RPM", path="self.propulsion.port.revolutions", unit="rpm",
             lower=0, upper=7000, decimals=0, color="yellow",
             subtype="measuring", scale_start=180, sk_unit_filter="Hz"),
    w_numeric("c_sog", 12, 0, 12, 6,
              name="SOG", path="self.navigation.speedOverGround",
              unit="knots", decimals=1, minichart=True, color="blue",
              y_min=0, y_max=30),
    w_numeric("c_coolant", 12, 6, 12, 6,
              name="Coolant", path="self.propulsion.port.temperature",
              unit="celsius", decimals=0, minichart=True, color="orange",
              y_min=0, y_max=110),

    # ── Row 12-19 ── Fuel bar | Voltage bar | Time remaining
    w_simple_linear("c_fuel", 0, 12, 8, 8,
                    name="Fuel Level", path="self.tanks.fuel.0.currentLevel",
                    unit="percent", lower=0, upper=100, decimals=0, color="green",
                    ignore_zones=True),
    w_simple_linear("c_voltage", 8, 12, 8, 8,
                    name="Voltage", path="self.electrical.batteries.0.voltage",
                    unit="V", lower=10, upper=15, decimals=2, color="green"),
    w_numeric("c_timerange", 16, 12, 8, 8,
              name="Fuel Hours", path="self.tanks.fuel.0.timeRange",
              unit="Hours", decimals=1, minichart=True, color="green",
              y_min=0, y_max=5),

    # ── Row 20-23 ── Trim | Engine hours | Fuel rate | Refilled button
    w_numeric("c_trim", 0, 20, 6, 4,
              name="Trim", path="self.propulsion.port.drive.trimState",
              unit="percent", decimals=0, color="contrast", y_min=0, y_max=100),
    w_numeric("c_hours", 6, 20, 6, 4,
              name="Hours", path="self.propulsion.port.runTime",
              unit="Hours", decimals=1, color="contrast"),
    w_numeric("c_fuelrate", 12, 20, 6, 4,
              name="Fuel Rate", path="self.propulsion.port.fuel.rate",
              unit="l/h", decimals=1, color="orange"),
    w_button("c_refill", 18, 20, 6, 4,
             name="Refilled (25 L)", path="self.tanks.fuel.0.refill",
             ctrl_label="Refill tank", color="green",
             is_numeric=False, value=True),
]

# ═══════════════════════════════════════════════════════════════════════════
# Dashboard 2 — Trolling
# Goal: precise lure-speed control; keep COG and position accessible.
# ═══════════════════════════════════════════════════════════════════════════
trolling_widgets = [
    # ── Row 0-11 ── Big SOG (visible from the stern) | COG compass
    w_numeric("t_sog", 0, 0, 14, 12,
              name="Trolling Speed", path="self.navigation.speedOverGround",
              unit="knots", decimals=1, minichart=True, color="blue",
              show_min_max=True, y_min=0, y_max=10),
    w_compass("t_cog", 14, 0, 10, 12,
              name="COG", path="self.navigation.courseOverGroundTrue",
              color="purple"),

    # ── Row 12-19 ── Speed consistency chart | Position
    # Flat SOG line = consistent lure depth.
    w_chart("t_sog_chart", 0, 12, 14, 8,
            name="Speed (10 min)",
            path="self.navigation.speedOverGround",
            convert_unit="knots", period=10, scale="minute", color="blue",
            y_min=0, y_max=8),
    w_position("t_pos", 14, 12, 10, 8, name="Position"),

    # ── Row 20-23 ── RPM | Trim | Fuel % | Distance remaining
    w_numeric("t_rpm", 0, 20, 6, 4,
              name="RPM", path="self.propulsion.port.revolutions",
              unit="rpm", decimals=0, color="yellow", y_min=0, y_max=7000),
    w_numeric("t_trim", 6, 20, 6, 4,
              name="Trim", path="self.propulsion.port.drive.trimState",
              unit="percent", decimals=0, color="contrast", y_min=0, y_max=100),
    w_numeric("t_fuelrem", 12, 20, 6, 4,
              name="Fuel %", path="self.tanks.fuel.0.currentLevel",
              unit="percent", decimals=0, color="green", y_min=0, y_max=100),
    w_numeric("t_distrange", 18, 20, 6, 4,
              name="Range", path="self.tanks.fuel.0.distanceRange",
              unit="nm", decimals=1, color="green", y_min=0, y_max=100),
]

# ═══════════════════════════════════════════════════════════════════════════
# Dashboard 3 — Statistics
# Goal: efficiency and trend analysis — slippage, fuel economy, history.
# ═══════════════════════════════════════════════════════════════════════════
stats_widgets = [
    # ── Row 0-7 ── Slip hero | Economy (nm/L) hero
    w_numeric("s_slip", 0, 0, 12, 8,
              name="Prop Slip", path="self.propulsion.port.slip",
              unit="percent", decimals=0, minichart=True, color="purple",
              show_min_max=True, y_min=0, y_max=100),
    w_numeric("s_economy", 12, 0, 12, 8,
              name="Economy (nm/L)", path="self.tanks.fuel.0.distancePerFuel",
              unit="nm/l", decimals=2, minichart=True, color="green",
              y_min=0, y_max=5),

    # ── Row 8-15 ── Slip chart | Fuel-rate chart | Coolant chart
    w_chart("s_slip_chart", 0, 8, 8, 8,
            name="Slip % (30 min)",
            path="self.propulsion.port.slip",
            convert_unit="percent", period=30, scale="minute", color="purple",
            y_min=0, y_max=100),
    w_chart("s_fuelrate_chart", 8, 8, 8, 8,
            name="Fuel Rate (60 min)",
            path="self.propulsion.port.fuel.rate",
            convert_unit="l/h", period=1, scale="hour", color="orange",
            y_min=0, y_max=15),
    w_chart("s_coolant_chart", 16, 8, 8, 8,
            name="Coolant °C (30 min)",
            path="self.propulsion.port.temperature",
            convert_unit="celsius", period=30, scale="minute", color="orange",
            y_min=0, y_max=110),

    # ── Row 16-23 ── SOG chart | RPM chart | 4 key numbers
    w_chart("s_sog_chart", 0, 16, 8, 8,
            name="SOG (30 min)",
            path="self.navigation.speedOverGround",
            convert_unit="knots", period=30, scale="minute", color="blue",
            y_min=0, y_max=30),
    w_chart("s_rpm_chart", 8, 16, 8, 8,
            name="RPM (30 min)",
            path="self.propulsion.port.revolutions",
            convert_unit="rpm", period=30, scale="minute", color="yellow",
            y_min=0, y_max=7000),
    # Right column: 4 compact numerics giving the current balance sheet
    w_numeric("s_timerange", 16, 16, 4, 4,
              name="Time Left", path="self.tanks.fuel.0.timeRange",
              unit="Hours", decimals=1, color="green", y_min=0, y_max=5),
    w_numeric("s_distrange", 20, 16, 4, 4,
              name="Range", path="self.tanks.fuel.0.distanceRange",
              unit="nm", decimals=1, color="green", y_min=0, y_max=100),
    w_numeric("s_fuelvol", 16, 20, 4, 4,
              name="Fuel L", path="self.tanks.fuel.0.currentVolume",
              unit="liter", decimals=1, color="green", y_min=0, y_max=25),
    w_numeric("s_hours", 20, 20, 4, 4,
              name="Eng Hours", path="self.propulsion.port.runTime",
              unit="Hours", decimals=0, color="contrast"),
]

# ═══════════════════════════════════════════════════════════════════════════
# Dashboard 4 — Fishing
# Goal: pick the best fishing windows of the day. Driven by signalk-solunar.
#
# Solunar at a glance:
#   • rating 0–4 — "Excellent" days are near new/full moon AND have a major
#     period overlapping sunrise or sunset.
#   • Major periods (~2 h) centred on moon overhead/underfoot — best bite.
#   • Minor periods (~1 h) centred on moonrise/moonset — secondary peaks.
# ═══════════════════════════════════════════════════════════════════════════
fishing_widgets = [
    # ── Row 0-9 ── Rating radial (hero) | phase, illumination, names
    w_radial("f_rating", 0, 0, 12, 10,
             name="Solunar Rating", path="self.environment.solunar.rating",
             unit="unitless", lower=0, upper=4, decimals=1, color="green",
             subtype="measuring", scale_start=180),
    w_text("f_rating_name", 12, 0, 6, 5,
           name="Rating", path="self.environment.solunar.ratingName",
           color="green"),
    w_text("f_active", 18, 0, 6, 5,
           name="Active Period", path="self.environment.solunar.activeKind",
           color="orange"),
    w_text("f_phase", 12, 5, 6, 5,
           name="Moon Phase", path="self.environment.moon.phaseName",
           color="contrast"),
    w_numeric("f_illum", 18, 5, 6, 5,
              name="Illumination", path="self.environment.moon.illumination",
              unit="percent", decimals=0, color="contrast",
              y_min=0, y_max=100),

    # ── Row 10-17 ── Sunrise / Sunset / Moonrise / Moonset
    w_datetime("f_sunrise", 0, 10, 6, 8,
               name="Sunrise", path="self.environment.sun.sunrise",
               fmt="HH:mm", color="yellow"),
    w_datetime("f_sunset", 6, 10, 6, 8,
               name="Sunset", path="self.environment.sun.sunset",
               fmt="HH:mm", color="orange"),
    w_datetime("f_moonrise", 12, 10, 6, 8,
               name="Moonrise", path="self.environment.moon.moonrise",
               fmt="HH:mm", color="blue"),
    w_datetime("f_moonset", 18, 10, 6, 8,
               name="Moonset", path="self.environment.moon.moonset",
               fmt="HH:mm", color="purple"),

    # ── Row 18-23 ── Next major / minor windows + countdowns
    w_datetime("f_next_major_start", 0, 18, 5, 6,
               name="Major Start", path="self.environment.solunar.nextMajorStart",
               fmt="HH:mm", color="green"),
    w_datetime("f_next_major_end", 5, 18, 5, 6,
               name="Major End", path="self.environment.solunar.nextMajorEnd",
               fmt="HH:mm", color="green"),
    w_numeric("f_mins_major", 10, 18, 4, 6,
              name="To Major", path="self.environment.solunar.minutesToNextMajor",
              unit="min", decimals=0, color="green", y_min=0, y_max=720),
    w_datetime("f_next_minor_start", 14, 18, 5, 6,
               name="Minor Start", path="self.environment.solunar.nextMinorStart",
               fmt="HH:mm", color="blue"),
    w_datetime("f_next_minor_end", 19, 18, 5, 6,
               name="Minor End", path="self.environment.solunar.nextMinorEnd",
               fmt="HH:mm", color="blue"),
]


def dashboard(slug, name, icon, widgets, collapse=False):
    return {
        "id": uid("dash", slug),
        "name": name,
        "icon": icon,
        "configuration": widgets,
        "collapseSplitShell": collapse,
    }


config = {
    SHARED_NAME: {
        "app": {
            "configVersion": CONFIG_VERSION,
            "autoNightMode": True,
            "redNightMode": False,
            "nightModeBrightness": 0.27,
            "isRemoteControl": False,
            "instanceName": "Quicksilver 410",
            "dataSets": [chart_dataset(p, u, s, per)
                         for p, u, s, per in DATASETS],
            "unitDefaults": {
                "Unitless": "unitless",
                "Speed": "knots",
                "Flow": "l/h",
                "Temperature": "celsius",
                "Length": "nm",
                "Volume": "liter",
                "Current": "A",
                "Potential": "V",
                "Charge": "C",
                "Power": "W",
                "Energy": "J",
                "Pressure": "mmHg",
                "Fuel Distance": "nm/l",
                "Energy Distance": "nm/kWh",
                "Density": "kg/m3",
                "Time": "Hours",
                "Angular Velocity": "deg/min",
                "Angle": "deg",
                "Frequency": "Hz",
                "Ratio": "ratio",
                "Resistance": "ohm",
            },
            "notificationConfig": {
                "disableNotifications": False,
                "menuGrouping": True,
                "security": {"disableSecurity": True},
                "devices": {
                    "disableDevices": False,
                    "showNormalState": False,
                    "showNominalState": False,
                },
                "sound": {
                    "disableSound": False,
                    "muteNormal": True,
                    "muteNominal": True,
                    "muteWarn": True,
                    "muteAlert": False,
                    "muteAlarm": False,
                    "muteEmergency": False,
                },
            },
            "splitShellEnabled": True,
            "splitShellSide": "left",
            "splitShellWidth": 0.5,
            "splitShellSwipeDisabled": False,
            "widgetHistoryDisabled": False,
        },
        "theme": {"themeName": ""},
        "dashboards": [
            dashboard("cruising",   "Cruising",   "dashboard-dashboard", cruising_widgets),
            dashboard("trolling",   "Trolling",   "dashboard-map",       trolling_widgets),
            dashboard("statistics", "Statistics", "dashboard-sailing",   stats_widgets),
            dashboard("fishing",    "Fishing",    "dashboard-sailing",   fishing_widgets),
        ],
    }
}


def main():
    KIP_CONFIG.parent.mkdir(parents=True, exist_ok=True)
    KIP_CONFIG.write_text(json.dumps(config, indent=2) + "\n")
    print(f"Wrote {KIP_CONFIG}")
    print(f"  dashboards: {len(config[SHARED_NAME]['dashboards'])}")
    print(f"  datasets:   {len(config[SHARED_NAME]['app']['dataSets'])}")
    total = sum(len(d['configuration']) for d in config[SHARED_NAME]['dashboards'])
    print(f"  widgets:    {total}")


if __name__ == "__main__":
    main()
