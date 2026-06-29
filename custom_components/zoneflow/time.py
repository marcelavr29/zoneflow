"""Entitate time: ora la care pornește udarea."""

from __future__ import annotations

import datetime as dt

from homeassistant.components.time import TimeEntity
from homeassistant.core import HomeAssistant
from homeassistant.helpers.entity_platform import AddEntitiesCallback
from homeassistant.helpers.restore_state import RestoreEntity

from . import ZoneFlowConfigEntry
from .const import VAL_START_TIME
from .coordinator import ZoneFlowCoordinator
from .entity import ZoneFlowEntity

DEFAULT_TIME = dt.time(6, 0, 0)


async def async_setup_entry(
    hass: HomeAssistant,
    entry: ZoneFlowConfigEntry,
    async_add_entities: AddEntitiesCallback,
) -> None:
    async_add_entities([ZoneFlowStartTime(entry.runtime_data)])


class ZoneFlowStartTime(ZoneFlowEntity, RestoreEntity, TimeEntity):
    """Ora de pornire a ciclului de udare."""

    _attr_icon = "mdi:clock-outline"

    def __init__(self, coordinator: ZoneFlowCoordinator) -> None:
        super().__init__(coordinator)
        self._attr_unique_id = f"{coordinator.entry.entry_id}_{VAL_START_TIME}"
        self._attr_name = "Ora de udare"
        self._attr_native_value = DEFAULT_TIME

    async def async_added_to_hass(self) -> None:
        await super().async_added_to_hass()
        last_state = await self.async_get_last_state()
        if last_state is not None and last_state.state not in (None, "unknown", "unavailable"):
            try:
                parsed = dt.time.fromisoformat(last_state.state)
                self._attr_native_value = parsed
            except ValueError:
                pass
        self.coordinator.set_value(VAL_START_TIME, self._attr_native_value)

    async def async_set_value(self, value: dt.time) -> None:
        self._attr_native_value = value
        self.coordinator.set_value(VAL_START_TIME, value)
        self.async_write_ha_state()
