"""Butoane: pornire manuală acum / oprire de urgență."""

from __future__ import annotations

from homeassistant.components.button import ButtonEntity
from homeassistant.core import HomeAssistant
from homeassistant.helpers.entity_platform import AddEntitiesCallback

from . import ZoneFlowConfigEntry
from .coordinator import ZoneFlowCoordinator
from .entity import ZoneFlowEntity


async def async_setup_entry(
    hass: HomeAssistant,
    entry: ZoneFlowConfigEntry,
    async_add_entities: AddEntitiesCallback,
) -> None:
    coordinator = entry.runtime_data
    async_add_entities(
        [
            ZoneFlowRunNowButton(coordinator),
            ZoneFlowStopButton(coordinator),
            ZoneFlowScheduleDueButton(coordinator),
        ]
    )


class ZoneFlowRunNowButton(ZoneFlowEntity, ButtonEntity):
    """Pornește imediat un ciclu de udare cu timpii curenți."""

    _attr_icon = "mdi:play"

    def __init__(self, coordinator: ZoneFlowCoordinator) -> None:
        super().__init__(coordinator)
        self._attr_unique_id = f"{coordinator.entry.entry_id}_run_now"
        self._attr_name = "Udă acum"

    async def async_press(self) -> None:
        self.coordinator.start_watering()


class ZoneFlowStopButton(ZoneFlowEntity, ButtonEntity):
    """Oprește ciclul în curs și închide toate supapele."""

    _attr_icon = "mdi:stop"

    def __init__(self, coordinator: ZoneFlowCoordinator) -> None:
        super().__init__(coordinator)
        self._attr_unique_id = f"{coordinator.entry.entry_id}_stop"
        self._attr_name = "Oprește udarea"

    async def async_press(self) -> None:
        await self.coordinator.async_stop_watering()


class ZoneFlowScheduleDueButton(ZoneFlowEntity, ButtonEntity):
    """Face următoarea udare scadentă → udă automat la următoarea oră programată."""

    _attr_icon = "mdi:calendar-arrow-right"

    def __init__(self, coordinator: ZoneFlowCoordinator) -> None:
        super().__init__(coordinator)
        self._attr_unique_id = f"{coordinator.entry.entry_id}_schedule_due"
        self._attr_name = "Programează la următoarea oră"

    async def async_press(self) -> None:
        self.coordinator.mark_due()
