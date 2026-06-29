"""API websocket pentru panoul ZoneFlow (citire/scriere configurație + comenzi)."""

from __future__ import annotations

import voluptuous as vol

from homeassistant.components import websocket_api
from homeassistant.config_entries import ConfigEntry
from homeassistant.core import HomeAssistant, callback

from .const import (
    CONF_FORECAST_DAYS,
    CONF_TEST_MINUTES,
    CONF_WEATHER_ENTITY,
    CONF_ZONES,
    DOMAIN,
    VAL_DAY,
    VAL_ENABLED,
    VAL_FACTOR,
    VAL_RAIN_COMP,
    VAL_START_TIME,
    WEEKDAYS,
)


def async_register(hass: HomeAssistant) -> None:
    """Înregistrează comenzile websocket o singură dată (apelat la setup-ul intrării)."""
    store = hass.data.setdefault(DOMAIN, {})
    if store.get("ws_registered"):
        return
    store["ws_registered"] = True
    websocket_api.async_register_command(hass, ws_get)
    websocket_api.async_register_command(hass, ws_save_zones)
    websocket_api.async_register_command(hass, ws_save_general)
    websocket_api.async_register_command(hass, ws_run_now)
    websocket_api.async_register_command(hass, ws_stop)


def _entry(hass: HomeAssistant) -> ConfigEntry | None:
    for entry in hass.config_entries.async_entries(DOMAIN):
        if getattr(entry, "runtime_data", None) is not None:
            return entry
    return None


@callback
def _entities(hass: HomeAssistant, domain: str) -> list[dict]:
    out = [
        {"entity_id": st.entity_id, "name": st.attributes.get("friendly_name", st.entity_id)}
        for st in hass.states.async_all(domain)
    ]
    out.sort(key=lambda s: s["name"].lower())
    return out


@callback
def _controls(hass: HomeAssistant, entry: ConfigEntry) -> dict:
    from homeassistant.helpers import entity_registry as er

    reg = er.async_get(hass)

    def eid(platform: str, suffix: str) -> str | None:
        return reg.async_get_entity_id(platform, DOMAIN, f"{entry.entry_id}_{suffix}")

    return {
        "enabled": eid("switch", VAL_ENABLED),
        "rain_comp": eid("switch", VAL_RAIN_COMP),
        "factor": eid("number", VAL_FACTOR),
        "start_time": eid("time", VAL_START_TIME),
        "days": {key: eid("switch", VAL_DAY[key]) for key in WEEKDAYS},
    }


@websocket_api.websocket_command({vol.Required("type"): "zoneflow/get"})
@callback
def ws_get(hass: HomeAssistant, connection: websocket_api.ActiveConnection, msg: dict) -> None:
    """Întoarce configurarea + starea live + listele pentru pickere."""
    entry = _entry(hass)
    if entry is None:
        connection.send_error(msg["id"], "not_found", "ZoneFlow nu e configurat")
        return
    coordinator = entry.runtime_data
    data = coordinator._build_data()
    next_run = data.get("next_run")
    live = {
        **data,
        "next_run": next_run.isoformat() if next_run else None,
        "is_watering": coordinator.is_watering,
    }
    connection.send_result(
        msg["id"],
        {
            "general": {
                k: entry.data.get(k)
                for k in (CONF_WEATHER_ENTITY, CONF_TEST_MINUTES, CONF_FORECAST_DAYS)
            },
            "zones": entry.options.get(CONF_ZONES, []),
            "live": live,
            "switches": _entities(hass, "switch"),
            "weathers": _entities(hass, "weather"),
            "controls": _controls(hass, entry),
        },
    )


@websocket_api.websocket_command(
    {vol.Required("type"): "zoneflow/save_zones", vol.Required("zones"): list}
)
@websocket_api.require_admin
@websocket_api.async_response
async def ws_save_zones(
    hass: HomeAssistant, connection: websocket_api.ActiveConnection, msg: dict
) -> None:
    entry = _entry(hass)
    if entry is None:
        connection.send_error(msg["id"], "not_found", "ZoneFlow nu e configurat")
        return
    hass.config_entries.async_update_entry(
        entry, options={**entry.options, CONF_ZONES: msg["zones"]}
    )
    connection.send_result(msg["id"], {"ok": True})


@websocket_api.websocket_command(
    {
        vol.Required("type"): "zoneflow/save_general",
        vol.Required(CONF_WEATHER_ENTITY): str,
        vol.Required(CONF_TEST_MINUTES): vol.Coerce(float),
        vol.Required(CONF_FORECAST_DAYS): vol.Coerce(int),
    }
)
@websocket_api.require_admin
@websocket_api.async_response
async def ws_save_general(
    hass: HomeAssistant, connection: websocket_api.ActiveConnection, msg: dict
) -> None:
    entry = _entry(hass)
    if entry is None:
        connection.send_error(msg["id"], "not_found", "ZoneFlow nu e configurat")
        return
    new_data = {
        **entry.data,
        CONF_WEATHER_ENTITY: msg[CONF_WEATHER_ENTITY],
        CONF_TEST_MINUTES: msg[CONF_TEST_MINUTES],
        CONF_FORECAST_DAYS: msg[CONF_FORECAST_DAYS],
    }
    hass.config_entries.async_update_entry(entry, data=new_data)
    connection.send_result(msg["id"], {"ok": True})


@websocket_api.websocket_command({vol.Required("type"): "zoneflow/run_now"})
@websocket_api.require_admin
@websocket_api.async_response
async def ws_run_now(
    hass: HomeAssistant, connection: websocket_api.ActiveConnection, msg: dict
) -> None:
    entry = _entry(hass)
    if entry is not None:
        entry.runtime_data.start_watering()
    connection.send_result(msg["id"], {"ok": True})


@websocket_api.websocket_command({vol.Required("type"): "zoneflow/stop"})
@websocket_api.require_admin
@websocket_api.async_response
async def ws_stop(
    hass: HomeAssistant, connection: websocket_api.ActiveConnection, msg: dict
) -> None:
    entry = _entry(hass)
    if entry is not None:
        await entry.runtime_data.async_stop_watering()
    connection.send_result(msg["id"], {"ok": True})
