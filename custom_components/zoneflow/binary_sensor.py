"""Binary sensor: indică dacă o sesiune de udare este în curs."""

from __future__ import annotations

from homeassistant.components.binary_sensor import (
    BinarySensorDeviceClass,
    BinarySensorEntity,
)
from homeassistant.core import HomeAssistant, callback
from homeassistant.helpers.entity_platform import AddEntitiesCallback

from . import ZoneFlowConfigEntry
from .coordinator import ZoneFlowCoordinator
from .entity import ZoneFlowEntity


async def async_setup_entry(
    hass: HomeAssistant,
    entry: ZoneFlowConfigEntry,
    async_add_entities: AddEntitiesCallback,
) -> None:
    async_add_entities([ZoneFlowActiveSensor(entry.runtime_data)])


class ZoneFlowActiveSensor(ZoneFlowEntity, BinarySensorEntity):
    """ON cât timp rulează un ciclu de udare."""

    _attr_device_class = BinarySensorDeviceClass.RUNNING
    _attr_icon = "mdi:sprinkler-variant"

    def __init__(self, coordinator: ZoneFlowCoordinator) -> None:
        super().__init__(coordinator)
        self._attr_unique_id = f"{coordinator.entry.entry_id}_watering_active"
        self._attr_name = "Udare în curs"

    @property
    def is_on(self) -> bool:
        return self.coordinator.is_watering

    async def async_added_to_hass(self) -> None:
        await super().async_added_to_hass()
        self.async_on_remove(
            self.coordinator.async_add_listener(self._handle_update)
        )

    @callback
    def _handle_update(self) -> None:
        self.async_write_ha_state()
