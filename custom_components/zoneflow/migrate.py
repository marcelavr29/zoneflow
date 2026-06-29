"""Migrarea intrărilor de config către schema curentă (v3: porțiuni + grupuri)."""

from __future__ import annotations

import logging
import uuid

from homeassistant.config_entries import ConfigEntry
from homeassistant.core import HomeAssistant

from .const import (
    CONF_AREA,
    CONF_FORECAST_DAYS,
    CONF_GROUPS,
    CONF_ID,
    CONF_NAME,
    CONF_RATES,
    CONF_SECTIONS,
    CONF_SWITCHES,
    CONF_TEST_MINUTES,
    CONF_WEATHER_ENTITY,
    CONF_ZONES,
    DEFAULT_AREA,
    DEFAULT_DEPTH,
)

_LOGGER = logging.getLogger(__name__)

# Chei vechi v1 (topologie fixă în entry.data).
_OLD_A1, _OLD_A2 = "zone_a_circuit1", "zone_a_circuit2"
_OLD_B_MID, _OLD_B_EDGE = "zone_b_mid", "zone_b_edge"


def _cid() -> str:
    return uuid.uuid4().hex[:8]


def _section(name: str, area: float = DEFAULT_AREA) -> dict:
    return {CONF_ID: _cid(), CONF_NAME: name, CONF_AREA: area}


def _group(name: str, switch: str, rates: dict) -> dict:
    return {CONF_ID: _cid(), CONF_NAME: name, CONF_SWITCHES: [switch], CONF_RATES: rates}


def _zone_from_simple_circuit(name: str, switch: str) -> tuple[dict, dict]:
    """Circuit fără suprapunere → o porțiune + un grup cu o supapă."""
    section = _section(name)
    group = _group(name, switch, {section[CONF_ID]: DEFAULT_DEPTH})
    return section, group


def _migrate_v2_zone(zone: dict) -> dict:
    """Zonă v2 (circuits + mode/role) → zonă v3 (sections + groups)."""
    name = zone.get("name", "Zonă")
    circuits = zone.get("circuits", [])
    sections: list[dict] = []
    groups: list[dict] = []

    if zone.get("mode") == "overlap":
        primary = next((c for c in circuits if c.get("role") == "primary"), None)
        edges = [c for c in circuits if c.get("role") == "edge"]
        interior = _section("Interior", float(primary.get("area", DEFAULT_AREA)) if primary else DEFAULT_AREA)
        sections.append(interior)
        primary_rates = {interior[CONF_ID]: float(primary.get("depth_inner", DEFAULT_DEPTH))} if primary else {}
        for edge in edges:
            margin = _section(edge.get("name", "Margine"), float(edge.get("area", DEFAULT_AREA)))
            sections.append(margin)
            if primary:
                primary_rates[margin[CONF_ID]] = float(primary.get("depth_margin", DEFAULT_DEPTH))
            groups.append(
                _group(edge.get("name", "Margine"), edge.get("switch", ""),
                       {margin[CONF_ID]: float(edge.get("depth", DEFAULT_DEPTH))})
            )
        if primary:
            groups.insert(0, _group(primary.get("name", "Primar"), primary.get("switch", ""), primary_rates))
    else:
        for circuit in circuits:
            section = _section(circuit.get("name", "Circuit"), float(circuit.get("area", DEFAULT_AREA)))
            sections.append(section)
            groups.append(
                _group(circuit.get("name", "Circuit"), circuit.get("switch", ""),
                       {section[CONF_ID]: float(circuit.get("depth", DEFAULT_DEPTH))})
            )

    return {CONF_ID: zone.get("id", _cid()), CONF_NAME: name, CONF_SECTIONS: sections, CONF_GROUPS: groups}


def _zones_from_v1(data: dict) -> list[dict]:
    zones: list[dict] = []
    if data.get(_OLD_A1) or data.get(_OLD_A2):
        sections, groups = [], []
        for old_key, name in ((_OLD_A1, "Circuit 1"), (_OLD_A2, "Circuit 2")):
            if data.get(old_key):
                s, g = _zone_from_simple_circuit(name, data[old_key])
                sections.append(s)
                groups.append(g)
        zones.append({CONF_ID: _cid(), CONF_NAME: "Zona A", CONF_SECTIONS: sections, CONF_GROUPS: groups})

    if data.get(_OLD_B_MID) or data.get(_OLD_B_EDGE):
        interior = _section("Interior")
        margine = _section("Margine")
        sections = [interior, margine]
        groups = []
        if data.get(_OLD_B_MID):
            groups.append(_group("Mijloc", data[_OLD_B_MID],
                                 {interior[CONF_ID]: DEFAULT_DEPTH, margine[CONF_ID]: DEFAULT_DEPTH}))
        if data.get(_OLD_B_EDGE):
            groups.append(_group("Margine", data[_OLD_B_EDGE], {margine[CONF_ID]: DEFAULT_DEPTH}))
        zones.append({CONF_ID: _cid(), CONF_NAME: "Zona B", CONF_SECTIONS: sections, CONF_GROUPS: groups})
    return zones


async def async_migrate_entry(hass: HomeAssistant, entry: ConfigEntry) -> bool:
    """Migrează la schema v3 din v1 (data fixă) sau v2 (zone cu circuite/roluri)."""
    if entry.version >= 3:
        return True

    data = dict(entry.data)
    if entry.version == 1:
        zones = _zones_from_v1(data)
    else:  # version == 2
        zones = [_migrate_v2_zone(z) for z in entry.options.get(CONF_ZONES, [])]

    new_data = {
        key: data[key]
        for key in (CONF_WEATHER_ENTITY, CONF_TEST_MINUTES, CONF_FORECAST_DAYS)
        if key in data
    }
    new_options = {**dict(entry.options), CONF_ZONES: zones}
    hass.config_entries.async_update_entry(
        entry, data=new_data, options=new_options, version=3
    )
    _LOGGER.info("ZoneFlow: migrat la v3 cu %d zone", len(zones))
    return True
