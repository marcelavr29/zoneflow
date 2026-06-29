"""Entități switch: activare sistem + zilele de udare."""

from __future__ import annotations

from typing import Any

from homeassistant.components.switch import SwitchEntity
from homeassistant.core import HomeAssistant
from homeassistant.helpers.entity_platform import AddEntitiesCallback
from homeassistant.helpers.restore_state import RestoreEntity

from . import ZoneFlowConfigEntry
from .const import VAL_DAY, VAL_ENABLED, VAL_RAIN_COMP, WEEKDAY_NAMES, WEEKDAYS
from .coordinator import ZoneFlowCoordinator
from .entity import ZoneFlowEntity


async def async_setup_entry(
    hass: HomeAssistant,
    entry: ZoneFlowConfigEntry,
    async_add_entities: AddEntitiesCallback,
) -> None:
    coordinator = entry.runtime_data
    entities: list[SwitchEntity] = [
        ZoneFlowToggle(
            coordinator,
            value_key=VAL_ENABLED,
            name="Irigație activă",
            default=True,
            icon="mdi:power",
        ),
        ZoneFlowToggle(
            coordinator,
            value_key=VAL_RAIN_COMP,
            name="Compensare ploaie",
            default=True,
            icon="mdi:weather-rainy",
        ),
    ]
    for key in WEEKDAYS:
        entities.append(
            ZoneFlowToggle(
                coordinator,
                value_key=VAL_DAY[key],
                name=f"Udare · {WEEKDAY_NAMES[key]}",
                default=False,
                icon="mdi:calendar-check",
            )
        )
    async_add_entities(entities)


class ZoneFlowToggle(ZoneFlowEntity, RestoreEntity, SwitchEntity):
    """Comutator persistent care alimentează coordinatorul (activare / zi)."""

    def __init__(
        self,
        coordinator: ZoneFlowCoordinator,
        *,
        value_key: str,
        name: str,
        default: bool,
        icon: str | None = None,
    ) -> None:
        super().__init__(coordinator)
        self._value_key = value_key
        self._default = default
        self._attr_unique_id = f"{coordinator.entry.entry_id}_{value_key}"
        self._attr_name = name
        self._attr_icon = icon
        self._attr_is_on = default

    async def async_added_to_hass(self) -> None:
        await super().async_added_to_hass()
        last_state = await self.async_get_last_state()
        if last_state is not None and last_state.state in ("on", "off"):
            self._attr_is_on = last_state.state == "on"
        self.coordinator.set_value(self._value_key, self._attr_is_on)

    async def async_turn_on(self, **kwargs: Any) -> None:
        self._attr_is_on = True
        self.coordinator.set_value(self._value_key, True)
        self.async_write_ha_state()

    async def async_turn_off(self, **kwargs: Any) -> None:
        self._attr_is_on = False
        self.coordinator.set_value(self._value_key, False)
        self.async_write_ha_state()
