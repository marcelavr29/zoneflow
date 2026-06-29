"""Entitate number: factorul de corecție (singura valoare reglabilă live din această platformă)."""

from __future__ import annotations

from homeassistant.components.number import NumberEntity, NumberMode, RestoreNumber
from homeassistant.const import EntityCategory
from homeassistant.core import HomeAssistant
from homeassistant.helpers.entity_platform import AddEntitiesCallback

from . import ZoneFlowConfigEntry
from .const import VAL_FACTOR
from .coordinator import ZoneFlowCoordinator
from .entity import ZoneFlowEntity


async def async_setup_entry(
    hass: HomeAssistant,
    entry: ZoneFlowConfigEntry,
    async_add_entities: AddEntitiesCallback,
) -> None:
    async_add_entities([ZoneFlowFactor(entry.runtime_data)])


class ZoneFlowFactor(ZoneFlowEntity, RestoreNumber, NumberEntity):
    """Factor de scalare a țintei (target = media_temp × factor)."""

    _attr_mode = NumberMode.BOX
    _attr_native_min_value = 0
    _attr_native_max_value = 3
    _attr_native_step = 0.05
    _attr_icon = "mdi:tune"
    _attr_entity_category = EntityCategory.CONFIG

    def __init__(self, coordinator: ZoneFlowCoordinator) -> None:
        super().__init__(coordinator)
        self._attr_unique_id = f"{coordinator.entry.entry_id}_{VAL_FACTOR}"
        self._attr_name = "Factor corecție"
        self._attr_native_value = 1.0

    async def async_added_to_hass(self) -> None:
        await super().async_added_to_hass()
        restored = await self.async_get_last_number_data()
        if restored is not None and restored.native_value is not None:
            self._attr_native_value = restored.native_value
        self.coordinator.set_value(VAL_FACTOR, self._attr_native_value)

    async def async_set_native_value(self, value: float) -> None:
        self._attr_native_value = value
        self.coordinator.set_value(VAL_FACTOR, value)
        self.async_write_ha_state()
