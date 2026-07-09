"""API websocket pentru panoul ZoneFlow (citire/scriere configurație + comenzi)."""

from __future__ import annotations

import voluptuous as vol

from homeassistant.components import websocket_api
from homeassistant.config_entries import ConfigEntry
from homeassistant.core import HomeAssistant, callback

from .const import (
    CONF_FORECAST_DAYS,
    CONF_NOTIFY_SERVICE,
    CONF_RAIN_SENSOR,
    CONF_TEST_MINUTES,
    CONF_WEATHER_ENTITY,
    CONF_ZONES,
    DOMAIN,
    VAL_AUTO_INTERVAL,
    VAL_ENABLED,
    VAL_FACTOR,
    VAL_INTERVAL,
    VAL_MAX_CYCLE,
    VAL_NOTIFY,
    VAL_RAIN_COMP,
    VAL_SOAK,
    VAL_START_TIME,
    VAL_TARGET_MM,
)


def async_register(hass: HomeAssistant) -> None:
    """Înregistrează comenzile websocket o singură dată (apelat la setup-ul intrării)."""
    store = hass.data.setdefault(DOMAIN, {})
    if store.get("ws_registered"):
        return
    store["ws_registered"] = True
    websocket_api.async_register_command(hass, ws_get)
    websocket_api.async_register_command(hass, ws_refresh)
    websocket_api.async_register_command(hass, ws_save_zones)
    websocket_api.async_register_command(hass, ws_save_general)
    websocket_api.async_register_command(hass, ws_run_now)
    websocket_api.async_register_command(hass, ws_stop)
    websocket_api.async_register_command(hass, ws_schedule_due)
    websocket_api.async_register_command(hass, ws_history)
    websocket_api.async_register_command(hass, ws_skip_next)
    websocket_api.async_register_command(hass, ws_postpone)
    websocket_api.async_register_command(hass, ws_test_zone)


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
        "auto_interval": eid("switch", VAL_AUTO_INTERVAL),
        "notify": eid("switch", VAL_NOTIFY),
        "target": eid("number", VAL_TARGET_MM),
        "factor": eid("number", VAL_FACTOR),
        "interval": eid("number", VAL_INTERVAL),
        "max_cycle": eid("number", VAL_MAX_CYCLE),
        "soak": eid("number", VAL_SOAK),
        "start_time": eid("time", VAL_START_TIME),
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
                for k in (
                    CONF_WEATHER_ENTITY,
                    CONF_TEST_MINUTES,
                    CONF_FORECAST_DAYS,
                    CONF_RAIN_SENSOR,
                    CONF_NOTIFY_SERVICE,
                )
            },
            "zones": entry.options.get(CONF_ZONES, []),
            "live": live,
            "switches": _entities(hass, "switch"),
            "weathers": _entities(hass, "weather"),
            "sensors": _entities(hass, "sensor"),
            "notify_services": sorted(hass.services.async_services().get("notify", {})),
            "controls": _controls(hass, entry),
        },
    )


@websocket_api.websocket_command({vol.Required("type"): "zoneflow/refresh"})
@websocket_api.async_response
async def ws_refresh(
    hass: HomeAssistant, connection: websocket_api.ActiveConnection, msg: dict
) -> None:
    """Forțează re-interogarea prognozei + recalcularea."""
    entry = _entry(hass)
    if entry is not None:
        await entry.runtime_data.async_request_refresh()
    connection.send_result(msg["id"], {"ok": True})


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
        vol.Optional(CONF_RAIN_SENSOR): vol.Any(str, None),
        vol.Optional(CONF_NOTIFY_SERVICE): vol.Any(str, None),
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
        CONF_RAIN_SENSOR: msg.get(CONF_RAIN_SENSOR) or None,
        CONF_NOTIFY_SERVICE: msg.get(CONF_NOTIFY_SERVICE) or None,
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


@websocket_api.websocket_command({vol.Required("type"): "zoneflow/schedule_due"})
@websocket_api.require_admin
@websocket_api.async_response
async def ws_schedule_due(
    hass: HomeAssistant, connection: websocket_api.ActiveConnection, msg: dict
) -> None:
    entry = _entry(hass)
    if entry is not None:
        entry.runtime_data.mark_due()
    connection.send_result(msg["id"], {"ok": True})


@websocket_api.websocket_command({vol.Required("type"): "zoneflow/history"})
@callback
def ws_history(hass: HomeAssistant, connection: websocket_api.ActiveConnection, msg: dict) -> None:
    entry = _entry(hass)
    if entry is None:
        connection.send_error(msg["id"], "not_found", "ZoneFlow nu e configurat")
        return
    connection.send_result(msg["id"], entry.runtime_data.history())


@websocket_api.websocket_command({vol.Required("type"): "zoneflow/skip_next"})
@websocket_api.require_admin
@websocket_api.async_response
async def ws_skip_next(
    hass: HomeAssistant, connection: websocket_api.ActiveConnection, msg: dict
) -> None:
    entry = _entry(hass)
    if entry is not None:
        entry.runtime_data.skip_next()
    connection.send_result(msg["id"], {"ok": True})


@websocket_api.websocket_command({vol.Required("type"): "zoneflow/postpone"})
@websocket_api.require_admin
@websocket_api.async_response
async def ws_postpone(
    hass: HomeAssistant, connection: websocket_api.ActiveConnection, msg: dict
) -> None:
    entry = _entry(hass)
    if entry is not None:
        entry.runtime_data.postpone()
    connection.send_result(msg["id"], {"ok": True})


@websocket_api.websocket_command(
    {
        vol.Required("type"): "zoneflow/test_zone",
        vol.Required("zone_id"): str,
        vol.Required("minutes"): vol.Coerce(float),
    }
)
@websocket_api.require_admin
@websocket_api.async_response
async def ws_test_zone(
    hass: HomeAssistant, connection: websocket_api.ActiveConnection, msg: dict
) -> None:
    entry = _entry(hass)
    if entry is not None:
        entry.runtime_data.test_zone(msg["zone_id"], msg["minutes"])
    connection.send_result(msg["id"], {"ok": True})
