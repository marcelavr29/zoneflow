"""Entități number reglabile live: factorul de corecție și intervalul între udări."""

from __future__ import annotations

from dataclasses import dataclass

from homeassistant.components.number import NumberEntity, NumberMode, RestoreNumber
from homeassistant.const import EntityCategory
from homeassistant.core import HomeAssistant
from homeassistant.helpers.entity_platform import AddEntitiesCallback

from . import ZoneFlowConfigEntry
from .const import (
    DEFAULT_INTERVAL_DAYS,
    DEFAULT_MAX_CYCLE_MIN,
    DEFAULT_SOAK_MIN,
    DEFAULT_TARGET_MM,
    VAL_FACTOR,
    VAL_INTERVAL,
    VAL_MAX_CYCLE,
    VAL_SOAK,
    VAL_TARGET_MM,
)
from .coordinator import ZoneFlowCoordinator
from .entity import ZoneFlowEntity


@dataclass(frozen=True, kw_only=True)
class ZoneFlowNumberDef:
    value_key: str
    name: str
    minimum: float
    maximum: float
    step: float
    default: float
    icon: str
    unit: str | None = None


_NUMBERS = [
    ZoneFlowNumberDef(
        value_key=VAL_TARGET_MM,
        name="Țintă apă (L/m²)",
        minimum=5,
        maximum=40,
        step=1,
        default=DEFAULT_TARGET_MM,
        icon="mdi:water",
        unit="L/m²",
    ),
    ZoneFlowNumberDef(
        value_key=VAL_FACTOR,
        name="Ajustare globală",
        minimum=0,
        maximum=3,
        step=0.05,
        default=1.0,
        icon="mdi:tune",
    ),
    ZoneFlowNumberDef(
        value_key=VAL_INTERVAL,
        name="Interval manual",
        minimum=1,
        maximum=60,
        step=1,
        default=DEFAULT_INTERVAL_DAYS,
        icon="mdi:calendar-sync",
        unit="zile",
    ),
    ZoneFlowNumberDef(
        value_key=VAL_MAX_CYCLE,
        name="Minute max/ciclu (cycle & soak)",
        minimum=0,
        maximum=120,
        step=1,
        default=DEFAULT_MAX_CYCLE_MIN,
        icon="mdi:timer-cog",
        unit="min",
    ),
    ZoneFlowNumberDef(
        value_key=VAL_SOAK,
        name="Pauză infiltrare (soak)",
        minimum=0,
        maximum=120,
        step=1,
        default=DEFAULT_SOAK_MIN,
        icon="mdi:timer-sand-paused",
        unit="min",
    ),
]


async def async_setup_entry(
    hass: HomeAssistant,
    entry: ZoneFlowConfigEntry,
    async_add_entities: AddEntitiesCallback,
) -> None:
    coordinator = entry.runtime_data
    async_add_entities(ZoneFlowNumber(coordinator, d) for d in _NUMBERS)


class ZoneFlowNumber(ZoneFlowEntity, RestoreNumber, NumberEntity):
    """Parametru reglabil persistent care alimentează coordinatorul."""

    _attr_mode = NumberMode.BOX
    _attr_entity_category = EntityCategory.CONFIG

    def __init__(self, coordinator: ZoneFlowCoordinator, definition: ZoneFlowNumberDef) -> None:
        super().__init__(coordinator)
        self._def = definition
        self._attr_unique_id = f"{coordinator.entry.entry_id}_{definition.value_key}"
        self._attr_name = definition.name
        self._attr_native_min_value = definition.minimum
        self._attr_native_max_value = definition.maximum
        self._attr_native_step = definition.step
        self._attr_icon = definition.icon
        self._attr_native_unit_of_measurement = definition.unit
        self._attr_native_value = definition.default

    async def async_added_to_hass(self) -> None:
        await super().async_added_to_hass()
        restored = await self.async_get_last_number_data()
        if restored is not None and restored.native_value is not None:
            self._attr_native_value = restored.native_value
        self.coordinator.set_value(self._def.value_key, self._attr_native_value)

    async def async_set_native_value(self, value: float) -> None:
        self._attr_native_value = value
        self.coordinator.set_value(self._def.value_key, value)
        self.async_write_ha_state()
