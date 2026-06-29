"""Constante pentru integrarea ZoneFlow."""

from __future__ import annotations

from homeassistant.const import Platform

DOMAIN = "zoneflow"

PLATFORMS: list[Platform] = [
    Platform.SENSOR,
    Platform.BINARY_SENSOR,
    Platform.NUMBER,
    Platform.TIME,
    Platform.SWITCH,
    Platform.BUTTON,
]

# --- Setări generale (entry.data) ---------------------------------------------
CONF_WEATHER_ENTITY = "weather_entity"
CONF_TEST_MINUTES = "test_minutes"
CONF_FORECAST_DAYS = "forecast_days"

DEFAULT_TEST_MINUTES = 10
DEFAULT_FORECAST_DAYS = 7

# --- Topologie dinamică (entry.options) ---------------------------------------
# entry.options[CONF_ZONES] = listă de zone; fiecare zonă: id, name, mode, circuits[].
CONF_ZONES = "zones"

# Chei câmpuri zonă / circuit.
CONF_ID = "id"
CONF_NAME = "name"
CONF_MODE = "mode"
CONF_CIRCUITS = "circuits"
CONF_SWITCH = "switch"
CONF_AREA = "area"
CONF_ROLE = "role"
CONF_DEPTH = "depth"  # circuit simple sau edge: mm / test pe suprafața lui
CONF_DEPTH_INNER = "depth_inner"  # primar: mm / test pe zona interioară (doar primar)
CONF_DEPTH_MARGIN = "depth_margin"  # primar: mm / test pe sub-zonele acoperite de edge-uri

# Moduri zonă.
MODE_INDEPENDENT = "independent"
MODE_OVERLAP = "overlap"
ZONE_MODES = [MODE_INDEPENDENT, MODE_OVERLAP]

# Roluri circuit.
ROLE_SIMPLE = "simple"  # zonă independentă
ROLE_PRIMARY = "primary"  # zonă overlap: acoperă toată zona
ROLE_EDGE = "edge"  # zonă overlap: completează o sub-zonă

DEFAULT_DEPTH = 10.0
DEFAULT_AREA = 0.0

# --- Zile săptămână (datetime.weekday(): 0 = luni) ----------------------------
WEEKDAYS = ["mon", "tue", "wed", "thu", "fri", "sat", "sun"]
WEEKDAY_NAMES = {
    "mon": "Luni",
    "tue": "Marți",
    "wed": "Miercuri",
    "thu": "Joi",
    "fri": "Vineri",
    "sat": "Sâmbătă",
    "sun": "Duminică",
}

# --- Chei valori reglabile live (coordinator.values) --------------------------
VAL_FACTOR = "factor"
VAL_ENABLED = "enabled"
VAL_START_TIME = "start_time"
VAL_DAY = {key: f"day_{key}" for key in WEEKDAYS}

# Servicii
SERVICE_RUN_NOW = "run_now"
SERVICE_STOP = "stop"
