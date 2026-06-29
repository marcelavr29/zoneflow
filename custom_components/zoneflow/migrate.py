"""Migrarea intrărilor de config între versiuni de schemă."""

from __future__ import annotations

import logging
import uuid

from homeassistant.config_entries import ConfigEntry
from homeassistant.core import HomeAssistant

from .const import (
    CONF_AREA,
    CONF_CIRCUITS,
    CONF_DEPTH,
    CONF_DEPTH_INNER,
    CONF_DEPTH_MARGIN,
    CONF_FORECAST_DAYS,
    CONF_ID,
    CONF_MODE,
    CONF_NAME,
    CONF_ROLE,
    CONF_SWITCH,
    CONF_TEST_MINUTES,
    CONF_WEATHER_ENTITY,
    CONF_ZONES,
    DEFAULT_AREA,
    DEFAULT_DEPTH,
    MODE_INDEPENDENT,
    MODE_OVERLAP,
    ROLE_EDGE,
    ROLE_PRIMARY,
    ROLE_SIMPLE,
)

_LOGGER = logging.getLogger(__name__)

# Cheile vechi (v1), topologie fixă.
_OLD_A1 = "zone_a_circuit1"
_OLD_A2 = "zone_a_circuit2"
_OLD_B_MID = "zone_b_mid"
_OLD_B_EDGE = "zone_b_edge"


def _cid() -> str:
    return uuid.uuid4().hex[:8]


async def async_migrate_entry(hass: HomeAssistant, entry: ConfigEntry) -> bool:
    """v1 (topologie fixă în data) → v2 (zone dinamice în options)."""
    if entry.version >= 2:
        return True

    data = dict(entry.data)
    zones = []

    if _OLD_A1 in data or _OLD_A2 in data:
        circuits = []
        for old_key, name in ((_OLD_A1, "Circuit 1"), (_OLD_A2, "Circuit 2")):
            if data.get(old_key):
                circuits.append(
                    {
                        CONF_ID: _cid(),
                        CONF_NAME: name,
                        CONF_SWITCH: data[old_key],
                        CONF_AREA: DEFAULT_AREA,
                        CONF_ROLE: ROLE_SIMPLE,
                        CONF_DEPTH: DEFAULT_DEPTH,
                    }
                )
        zones.append(
            {CONF_ID: _cid(), CONF_NAME: "Zona A", CONF_MODE: MODE_INDEPENDENT, CONF_CIRCUITS: circuits}
        )

    if data.get(_OLD_B_MID) or data.get(_OLD_B_EDGE):
        circuits = []
        if data.get(_OLD_B_MID):
            circuits.append(
                {
                    CONF_ID: _cid(),
                    CONF_NAME: "Mijloc",
                    CONF_SWITCH: data[_OLD_B_MID],
                    CONF_AREA: DEFAULT_AREA,
                    CONF_ROLE: ROLE_PRIMARY,
                    CONF_DEPTH_INNER: DEFAULT_DEPTH,
                    CONF_DEPTH_MARGIN: DEFAULT_DEPTH,
                }
            )
        if data.get(_OLD_B_EDGE):
            circuits.append(
                {
                    CONF_ID: _cid(),
                    CONF_NAME: "Margine",
                    CONF_SWITCH: data[_OLD_B_EDGE],
                    CONF_AREA: DEFAULT_AREA,
                    CONF_ROLE: ROLE_EDGE,
                    CONF_DEPTH: DEFAULT_DEPTH,
                }
            )
        zones.append(
            {CONF_ID: _cid(), CONF_NAME: "Zona B", CONF_MODE: MODE_OVERLAP, CONF_CIRCUITS: circuits}
        )

    # Păstrăm doar setările generale în data.
    new_data = {
        key: data[key]
        for key in (CONF_WEATHER_ENTITY, CONF_TEST_MINUTES, CONF_FORECAST_DAYS)
        if key in data
    }
    new_options = {**dict(entry.options), CONF_ZONES: zones}

    hass.config_entries.async_update_entry(
        entry, data=new_data, options=new_options, version=2
    )
    _LOGGER.info("ZoneFlow: migrat la v2 cu %d zone", len(zones))
    return True
