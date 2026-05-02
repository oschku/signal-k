#!/usr/bin/env python3
"""
Generate the KIP dashboard configuration for the Quicksilver 410 / Tohatsu MFS30DETL build.

KIP config lives at:
  signalk-config/applicationData/users/<user>/kip/<schemaVersion>.json

The file is `{ "<sharedConfigName>": IConfig }` where IConfig = { app, theme, dashboards }.
The user's currently-active config is named "default".

Run:  python3 scripts/build_kip_config.py
This rewrites the admin-user config with four dashboards: Underway, Trolling, Navigation,
Engine, plus the history datasets the charts depend on.
"""
import json
import uuid
from pathlib import Path

REPO = Path(__file__).resolve().parent.parent
KIP_CONFIG = REPO / "signalk-config/applicationData/users/admin/kip/11.0.0.json"
SHARED_NAME = "default"
CONFIG_VERSION = 12

# Stable UUIDs so re-running produces the same file (= clean diffs)
NS = uuid.UUID("a4d2c6ce-1f84-4b9c-8a9b-2f3e4d5a6b7c")
def uid(*parts: str) -> str:
    return str(uuid.uuid5(NS, "/".join(parts)))


# ─── Dataset definitions (history tracking) ────────────────────────────────
# baseUnit must match the Signal K SI unit so the historian stores raw values.
# Engine paths use the .port instance (not .0) because @signalk/n2k-signalk
# maps PGN 127488/127489 instance 0 → "port" (1 → "starboard", etc.).
# Note: coolant arrives as `.temperature` and trim as `.drive.trimState`.
# No depth dataset — the boat has no depth sounder.
DATASETS = [
    ("sog",      "self.navigation.speedOverGround",         "m/s",   "minute", 30),
    ("rpm",      "self.propulsion.port.revolutions",        "Hz",    "minute", 30),
    ("fuelrate", "self.propulsion.port.fuel.rate",          "m3/s",  "hour",   1),
    ("coolant",  "self.propulsion.port.temperature",        "K",     "minute", 30),
    ("voltage",  "self.electrical.batteries.0.voltage",     "V",     "minute", 30),
    ("slip",     "self.propulsion.port.slip",               "ratio", "minute", 30),
    ("fuelrem",  "self.tanks.fuel.0.currentLevel",          "ratio", "hour",   2),
]


def dataset_entry(slug, path, base_unit, scale, period):
    ds_uuid = uid("ds", slug)
    return {
        "uuid": ds_uuid,
        "path": path,
        "pathSource": "default",
        "baseUnit": base_unit,
        "timeScaleFormat": scale,
        "period": period,
        "label": f"{slug} ({scale} x{period})",
        "editable": True,
    }


# ─── Widget builders ──────────────────────────────────────────────────────

def w_numeric(slug, x, y, w, h, *, name, path, unit, decimals=1,
              minichart=False, color="contrast", show_min_max=False,
              y_min=None, y_max=None, sk_unit_filter=None):
    wid = uid("w", slug)
    return {
        "x": x, "y": y, "w": w, "h": h,
        "id": wid,
        "selector": "widget-host2",
        "input": {"widgetProperties": {
            "type": "widget-numeric",
            "uuid": wid,
            "config": {
                "displayName": name,
                "filterSelfPaths": True,
                "paths": {"numericPath": {
                    "description": "Numeric Data",
                    "path": path,
                    "source": "default",
                    "pathType": "number",
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
                    decimals=1, color="green", sk_unit_filter=None):
    wid = uid("w", slug)
    return {
        "x": x, "y": y, "w": w, "h": h,
        "id": wid,
        "selector": "widget-host2",
        "input": {"widgetProperties": {
            "type": "widget-simple-linear",
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
                    "showPathSkUnitsFilter": True,
                    "pathSkUnitsFilter": sk_unit_filter,
                    "convertUnitTo": unit,
                    "sampleTime": 500,
                }},
                "displayScale": {"lower": lower, "upper": upper, "type": "linear"},
                "gauge": {"type": "simpleLinear", "unitLabelFormat": "full"},
                "numInt": 1,
                "numDecimal": decimals,
                "ignoreZones": False,
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
            color="orange", y_min=None, y_max=None):
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
                "filterSelfPaths": True,
                "datachartPath": path,
                "datachartSource": "default",
                "period": period,
                "timeScale": scale,
                "convertUnitTo": convert_unit,
                "timeScaleFormat": scale,
                "inverseYAxis": False,
                "datasetAverageArray": "sma",
                "showAverageData": True,
                "trackAgainstAverage": False,
                "showDatasetMinimumValueLine": False,
                "showDatasetMaximumValueLine": False,
                "showDatasetAverageValueLine": True,
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
                "numDecimal": 1,
                "color": color,
                "invertData": False,
                "verticalGraph": False,
            },
        }},
    }


def w_datetime(slug, x, y, w, h, *, name="Time", fmt="HH:mm:ss",
               tz="Europe/Helsinki", color="contrast"):
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
                    "description": "String Data",
                    "path": "self.environment.time",
                    "source": "default",
                    "pathType": "Date",
                    "isPathConfigurable": True,
                    "sampleTime": 500,
                }},
                "dateFormat": fmt,
                "dateTimezone": tz,
                "color": color,
                "enableTimeout": False,
                "dataTimeout": 5,
            },
        }},
    }


def w_button(slug, x, y, w, h, *, name, path, color="green", on_value=True,
             off_value=False):
    """Boolean-switch widget configured as a momentary refill button.

    Wired to the signalk-fuel-monitor plugin's PUT handler at
    `tanks.fuel.0.refill`: any truthy value resets the tank to capacity.
    """
    wid = uid("w", slug)
    return {
        "x": x, "y": y, "w": w, "h": h,
        "id": wid,
        "selector": "widget-host2",
        "input": {"widgetProperties": {
            "type": "widget-boolean-switch",
            "uuid": wid,
            "config": {
                "displayName": name,
                "filterSelfPaths": True,
                "paths": {"statePath": {
                    "description": "Refill action",
                    "path": path,
                    "source": "default",
                    "pathType": "boolean",
                    "isPathConfigurable": True,
                    "convertUnitTo": "unitless",
                    "putEnabled": True,
                    "sampleTime": 500,
                }},
                "putMomentary": True,
                "putMomentaryValue": on_value,
                "putValue": on_value,
                "putValueOff": off_value,
                "color": color,
                "enableTimeout": False,
                "dataTimeout": 5,
            },
        }},
    }


# Layouts assume a 24-column grid. The MFS30D has no depth sounder and no
# fuel-tank sender, so depth is omitted everywhere and fuel level comes from
# the signalk-fuel-monitor plugin (rate-integrated, refillable via PUT).

# ─── Dashboard 1: Underway (cruising) ─────────────────────────────────────
underway_widgets = [
    # Top half: big RPM gauge | SOG | Slip
    w_radial("u_rpm", 0, 0, 12, 12,
             name="RPM", path="self.propulsion.port.revolutions", unit="RPM",
             lower=0, upper=7000, decimals=0, color="yellow",
             subtype="measuring", scale_start=180, sk_unit_filter="Hz"),
    w_numeric("u_sog", 12, 0, 12, 6,
              name="SOG", path="self.navigation.speedOverGround", unit="knots",
              decimals=1, minichart=True, color="blue", y_min=0, y_max=25),
    w_numeric("u_slip", 12, 6, 12, 6,
              name="Prop Slip", path="self.propulsion.port.slip",
              unit="%", decimals=0, minichart=True, color="purple",
              y_min=0, y_max=100),

    # Mid section: fuel + coolant + voltage
    w_simple_linear("u_fuel", 0, 12, 8, 8,
                    name="Fuel Level", path="self.tanks.fuel.0.currentLevel",
                    unit="%", lower=0, upper=100, decimals=0, color="green"),
    w_numeric("u_coolant", 8, 12, 8, 8,
              name="Coolant", path="self.propulsion.port.temperature",
              unit="celsius", decimals=0, minichart=True, color="orange",
              y_min=0, y_max=110),
    w_simple_linear("u_voltage", 16, 12, 8, 8,
                    name="Voltage", path="self.electrical.batteries.0.voltage",
                    unit="V", lower=10, upper=15, decimals=2, color="green"),

    # Bottom strip: trim, hours, fuel rate, refill button
    w_numeric("u_trim", 0, 20, 6, 4,
              name="Trim", path="self.propulsion.port.drive.trimState", unit="%",
              decimals=0, color="contrast", y_min=0, y_max=100),
    w_numeric("u_hours", 6, 20, 6, 4,
              name="Engine Hours", path="self.propulsion.port.runTime",
              unit="Hours", decimals=1, color="contrast"),
    w_numeric("u_fuelrate", 12, 20, 6, 4,
              name="Fuel Rate", path="self.propulsion.port.fuel.rate",
              unit="l/h", decimals=2, color="orange"),
    w_button("u_refill", 18, 20, 6, 4,
             name="Refilled (25 L)", path="self.tanks.fuel.0.refill",
             color="green"),
]

# ─── Dashboard 2: Trolling (low-speed fishing) ────────────────────────────
# No depth sounder on the boat — the trolling dashboard is built around
# precise speed control, course, and position rather than bottom following.
trolling_widgets = [
    # Trolling speed needs visible-from-the-rod-holder size and 1-decimal precision
    w_numeric("t_sog", 0, 0, 14, 12,
              name="Trolling Speed", path="self.navigation.speedOverGround",
              unit="knots", decimals=1, minichart=True, color="blue",
              show_min_max=True, y_min=0, y_max=10),
    w_compass("t_cog", 14, 0, 10, 12,
              name="COG", path="self.navigation.courseOverGroundTrue",
              color="purple"),

    # SOG history shows trolling consistency — the lure is happiest at a steady speed
    w_chart("t_sog_chart", 0, 12, 14, 8,
            name="Trolling Speed (10 min)",
            path="self.navigation.speedOverGround",
            convert_unit="knots", period=10, scale="minute", color="blue",
            y_min=0, y_max=10),
    w_position("t_pos", 14, 12, 10, 8, name="Position"),

    # Quick reference strip
    w_numeric("t_rpm", 0, 20, 8, 4,
              name="RPM", path="self.propulsion.port.revolutions",
              unit="RPM", decimals=0, color="yellow",
              y_min=0, y_max=7000),
    w_numeric("t_trim", 8, 20, 8, 4,
              name="Trim", path="self.propulsion.port.drive.trimState",
              unit="%", decimals=0, color="contrast", y_min=0, y_max=100),
    w_numeric("t_fuelrem", 16, 20, 8, 4,
              name="Fuel %", path="self.tanks.fuel.0.currentLevel",
              unit="%", decimals=0, color="green", y_min=0, y_max=100),
]

# ─── Dashboard 3: Navigation ───────────────────────────────────────────────
# Position comes from the FZ-G1's built-in u-blox GPS via the OS sensor stack.
nav_widgets = [
    # Big compass for COG
    w_compass("n_cog", 0, 0, 12, 12,
              name="COG", path="self.navigation.courseOverGroundTrue",
              color="purple"),
    w_numeric("n_sog", 12, 0, 12, 6,
              name="SOG", path="self.navigation.speedOverGround",
              unit="knots", decimals=1, minichart=True, color="blue",
              y_min=0, y_max=25),
    w_position("n_pos", 12, 6, 12, 6, name="Position"),

    # Speed history over a longer window to see passage progress
    w_chart("n_sog_chart", 0, 12, 24, 8,
            name="Speed Over Ground (30 min)",
            path="self.navigation.speedOverGround",
            convert_unit="knots", period=30, scale="minute", color="blue",
            y_min=0, y_max=25),

    # Bottom strip — clock, voltage (was depth), heading
    w_datetime("n_clock", 0, 20, 8, 4, name="Local Time", fmt="HH:mm:ss",
               tz="Europe/Helsinki", color="contrast"),
    w_numeric("n_voltage", 8, 20, 8, 4,
              name="Voltage", path="self.electrical.batteries.0.voltage",
              unit="V", decimals=2, color="green", y_min=10, y_max=15),
    w_numeric("n_heading", 16, 20, 8, 4,
              name="COG (deg)", path="self.navigation.courseOverGroundTrue",
              unit="deg", decimals=0, color="purple",
              sk_unit_filter="rad", y_min=0, y_max=360),
]

# ─── Dashboard 4: Engine Detail (diagnostics + slippage) ──────────────────
engine_widgets = [
    # Slippage hero — only meaningful when running, alarms above ~40%
    w_numeric("e_slip", 0, 0, 12, 8,
              name="Prop Slip", path="self.propulsion.port.slip",
              unit="%", decimals=0, minichart=True, color="purple",
              show_min_max=True, y_min=0, y_max=100),
    w_chart("e_slip_chart", 12, 0, 12, 8,
            name="Slip vs Theoretical (30 min)",
            path="self.propulsion.port.slip",
            convert_unit="%", period=30, scale="minute", color="purple",
            y_min=0, y_max=100),

    # History grid: RPM, fuel rate, coolant
    w_chart("e_rpm_chart", 0, 8, 8, 8,
            name="RPM (30 min)",
            path="self.propulsion.port.revolutions",
            convert_unit="RPM", period=30, scale="minute", color="yellow",
            y_min=0, y_max=7000),
    w_chart("e_fuelrate_chart", 8, 8, 8, 8,
            name="Fuel Rate (60 min)",
            path="self.propulsion.port.fuel.rate",
            convert_unit="l/h", period=1, scale="hour", color="orange",
            y_min=0, y_max=15),
    w_chart("e_coolant_chart", 16, 8, 8, 8,
            name="Coolant °C (30 min)",
            path="self.propulsion.port.temperature",
            convert_unit="celsius", period=30, scale="minute", color="orange",
            y_min=0, y_max=110),

    # Bottom diagnostic strip
    w_simple_linear("e_voltage", 0, 16, 6, 8,
                    name="Voltage", path="self.electrical.batteries.0.voltage",
                    unit="V", lower=10, upper=15, decimals=2, color="green"),
    w_numeric("e_trim", 6, 16, 6, 8,
              name="Trim", path="self.propulsion.port.drive.trimState", unit="%",
              decimals=0, color="contrast", y_min=0, y_max=100),
    w_numeric("e_hours", 12, 16, 6, 8,
              name="Hours", path="self.propulsion.port.runTime",
              unit="Hours", decimals=1, color="contrast"),
    w_numeric("e_fuelrem", 18, 16, 6, 8,
              name="Fuel L", path="self.tanks.fuel.0.currentLevel",
              unit="liter", decimals=1, color="green"),
]


def dashboard(slug, name, icon, widgets):
    return {
        "id": uid("dash", slug),
        "name": name,
        "icon": icon,
        "configuration": widgets,
        "collapseSplitShell": False,
    }


config = {
    SHARED_NAME: {
        "app": {
            "configVersion": CONFIG_VERSION,
            # Manual day/night toggle stays available in KIP's top bar.
            # autoNightMode flips at sunset/sunrise; redNightMode adds the
            # red filter on top of night theme (preserves dark-adapted vision).
            "autoNightMode": True,
            "redNightMode": False,
            "nightModeBrightness": 0.27,
            "isRemoteControl": False,
            "instanceName": "Quicksilver 410",
            "dataSets": [dataset_entry(slug, p, u, s, per)
                         for slug, p, u, s, per in DATASETS],
            "unitDefaults": {
                "Unitless": "unitless",
                "Speed": "knots",
                "Flow": "l/h",
                "Temperature": "celsius",
                "Length": "m",
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
            dashboard("underway", "Underway",   "dashboard-dashboard", underway_widgets),
            dashboard("trolling", "Trolling",   "dashboard-map",       trolling_widgets),
            dashboard("nav",      "Navigation", "dashboard-sailing",   nav_widgets),
            dashboard("engine",   "Engine",     "dashboard-dashboard", engine_widgets),
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
