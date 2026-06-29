"""Bază comună pentru entitățile integrării (device info)."""

from __future__ import annotations

from homeassistant.helpers.device_registry import DeviceInfo
from homeassistant.helpers.entity import Entity

from .const import DOMAIN
from .coordinator import ZoneFlowCoordinator


class ZoneFlowEntity(Entity):
    """Atașează entitatea la un singur dispozitiv „ZoneFlow"."""

    _attr_has_entity_name = True
    _attr_should_poll = False

    def __init__(self, coordinator: ZoneFlowCoordinator) -> None:
        self.coordinator = coordinator
        self._attr_device_info = DeviceInfo(
            identifiers={(DOMAIN, coordinator.entry.entry_id)},
            name="ZoneFlow",
            manufacturer="tbfapps",
            model="Controler irigație pe temperatură",
        )
