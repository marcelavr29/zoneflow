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

# --- Chei config (entry.data) -------------------------------------------------
CONF_WEATHER_ENTITY = "weather_entity"
CONF_TEST_MINUTES = "test_minutes"
CONF_FORECAST_DAYS = "forecast_days"

CONF_ZONE_A_C1 = "zone_a_circuit1"
CONF_ZONE_A_C2 = "zone_a_circuit2"
CONF_ZONE_B_EDGE = "zone_b_edge"
CONF_ZONE_B_MID = "zone_b_mid"

DEFAULT_TEST_MINUTES = 10
DEFAULT_FORECAST_DAYS = 7

# --- Circuite -----------------------------------------------------------------
# Ordinea în care se udă secvențial într-o sesiune.
CIRCUIT_KEYS = ["a1", "a2", "b_mid", "b_edge"]

CIRCUIT_NAMES = {
    "a1": "Zona A · circuit 1",
    "a2": "Zona A · circuit 2",
    "b_mid": "Zona B · circuit mijloc",
    "b_edge": "Zona B · circuit margine",
}

# Maparea cheie circuit -> cheia de config a entității switch.
CIRCUIT_CONF = {
    "a1": CONF_ZONE_A_C1,
    "a2": CONF_ZONE_A_C2,
    "b_mid": CONF_ZONE_B_MID,
    "b_edge": CONF_ZONE_B_EDGE,
}

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

# --- Chei valori reglabile (coordinator.values) -------------------------------
# Suprafețe (m²) per circuit.
VAL_AREA = {key: f"area_{key}" for key in CIRCUIT_KEYS}
# Caserole (mm / test) pentru circuitele simple.
VAL_DEPTH_SIMPLE = {"a1": "depth_a1", "a2": "depth_a2"}
# Caserole (mm / test) pe poziții pentru zona cu suprapunere.
VAL_DEPTH_B_MID_INNER = "depth_b_mid_inner"
VAL_DEPTH_B_MID_MARGIN = "depth_b_mid_margin"
VAL_DEPTH_B_EDGE_MARGIN = "depth_b_edge_margin"

VAL_FACTOR = "factor"
VAL_ENABLED = "enabled"
VAL_START_TIME = "start_time"
VAL_DAY = {key: f"day_{key}" for key in WEEKDAYS}

# Servicii
SERVICE_RUN_NOW = "run_now"
SERVICE_STOP = "stop"
