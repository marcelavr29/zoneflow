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
# entry.options[CONF_ZONES] = listă de zone. Schema v4:
#   zone: {id, name, area, factor_pct, groups: [{id, name, switches[], rate}]}
# - zonă: suprafață (m², pt. litri) + factor (% — ex. umbră 70);
# - grup (group) = una sau mai multe supape care pornesc DEODATĂ, cu o rată (mm/test).
# Durata grupului = țintă_zonă / rata lui (metoda testului cu caserole). Fără optimizator.
CONF_ZONES = "zones"

# Chei comune / zonă.
CONF_ID = "id"
CONF_NAME = "name"
CONF_AREA = "area"  # m² ai zonei (pt. raportare litri)
CONF_FACTOR_PCT = "factor_pct"  # ajustare per zonă (%), default 100
# Cycle & soak per zonă (opțional); dacă lipsesc → fallback la valorile globale.
CONF_MAX_CYCLE = "max_cycle"  # minute max/ciclu pentru zonă
CONF_SOAK = "soak"  # pauză de infiltrare pentru zonă (min)

# Grupuri.
CONF_GROUPS = "groups"
CONF_SWITCHES = "switches"  # listă de entity_id-uri de switch pornite simultan
CONF_RATE = "rate"  # mm / test — măsurat cu tot grupul pornit (testul cu caserole)

# Chei vechi (doar pentru migrare din scheme v2/v3).
CONF_SECTIONS = "sections"
CONF_RATES = "rates"

DEFAULT_DEPTH = 10.0
DEFAULT_AREA = 0.0
DEFAULT_FACTOR_PCT = 100.0

# --- Chei valori reglabile live (coordinator.values) --------------------------
VAL_TARGET_MM = "target_mm"  # cantitate fixă pe sesiune (L/m²)
VAL_FACTOR = "factor"  # multiplicator global (sezonier), ×
VAL_ENABLED = "enabled"
VAL_START_TIME = "start_time"
VAL_AUTO_INTERVAL = "auto_interval"  # intervalul vine din temperatură (altfel manual)
VAL_INTERVAL = "interval_days"  # interval manual (zile), când Auto e oprit
VAL_RAIN_COMP = "rain_comp"  # compensarea ploii (scade ploaia prevăzută din țintă)
VAL_MAX_CYCLE = "max_cycle_min"  # cycle & soak: minute max pe repriză (0 = dezactivat)
VAL_SOAK = "soak_min"  # cycle & soak: pauză de infiltrare între reprize (min)
VAL_NOTIFY = "notify"  # notificări HA la start/stop/skip

DEFAULT_TARGET_MM = 15.0
DEFAULT_INTERVAL_DAYS = 3
DEFAULT_MAX_CYCLE_MIN = 15.0
DEFAULT_SOAK_MIN = 20.0

# Fereastra de prognoză orară pentru ploaia luată în calcul.
RAIN_WINDOW_HOURS = 24

# Fereastra de prognoză orară pentru ploaia luată în calcul.
RAIN_WINDOW_HOURS = 24

# Servicii
SERVICE_RUN_NOW = "run_now"
SERVICE_STOP = "stop"
