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
# entry.options[CONF_ZONES] = listă de zone. Schema v3:
#   zone: {id, name, sections: [{id, name, area}], groups: [{id, name, switches[], rates{}}]}
# - porțiune (section) = sub-zonă care trebuie să primească ținta Q;
# - grup (group) = una sau mai multe supape care pornesc DEODATĂ, cu rata (mm/test) per porțiune.
CONF_ZONES = "zones"

# Chei comune / zonă.
CONF_ID = "id"
CONF_NAME = "name"

# Porțiuni.
CONF_SECTIONS = "sections"
CONF_AREA = "area"  # m² ai porțiunii

# Grupuri.
CONF_GROUPS = "groups"
CONF_SWITCHES = "switches"  # listă de entity_id-uri de switch pornite simultan
CONF_RATES = "rates"  # {section_id: mm / test} — măsurat cu tot grupul pornit

DEFAULT_DEPTH = 10.0
DEFAULT_AREA = 0.0
DEFAULT_SECTION_NAME = "Toată zona"

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
VAL_RAIN_COMP = "rain_comp"  # compensarea ploii (scade ploaia prevăzută din țintă)

# Fereastra de prognoză orară pentru ploaia luată în calcul.
RAIN_WINDOW_HOURS = 24

# Servicii
SERVICE_RUN_NOW = "run_now"
SERVICE_STOP = "stop"
