"""Entități number: suprafețe, valori caserole, factor de corecție."""

from __future__ import annotations

from dataclasses import dataclass

from homeassistant.components.number import NumberEntity, NumberMode, RestoreNumber
from homeassistant.const import UnitOfArea, UnitOfLength
from homeassistant.core import HomeAssistant
from homeassistant.helpers.entity_platform import AddEntitiesCallback

from . import ZoneFlowConfigEntry
from .const import (
    CIRCUIT_KEYS,
    CIRCUIT_NAMES,
    VAL_AREA,
    VAL_DEPTH_B_EDGE_MARGIN,
    VAL_DEPTH_B_MID_INNER,
    VAL_DEPTH_B_MID_MARGIN,
    VAL_DEPTH_SIMPLE,
    VAL_FACTOR,
)
from .coordinator import ZoneFlowCoordinator
from .entity import ZoneFlowEntity


@dataclass(frozen=True, kw_only=True)
class ZoneFlowNumberDef:
    """Descrie un parametru reglabil expus ca entitate number."""

    value_key: str
    name: str
    unit: str | None
    minimum: float
    maximum: float
    step: float
    default: float
    icon: str | None = None


def _build_defs() -> list[ZoneFlowNumberDef]:
    defs: list[ZoneFlowNumberDef] = []

    # Suprafețe per circuit (m²).
    for key in CIRCUIT_KEYS:
        defs.append(
            ZoneFlowNumberDef(
                value_key=VAL_AREA[key],
                name=f"Suprafață · {CIRCUIT_NAMES[key]}",
                unit=UnitOfArea.SQUARE_METERS,
                minimum=0,
                maximum=1000,
                step=0.5,
                default=0.0,
                icon="mdi:ruler-square",
            )
        )

    # Caserole circuite simple (mm / test).
    for key, vkey in VAL_DEPTH_SIMPLE.items():
        defs.append(
            ZoneFlowNumberDef(
                value_key=vkey,
                name=f"Caserolă · {CIRCUIT_NAMES[key]}",
                unit=UnitOfLength.MILLIMETERS,
                minimum=0,
                maximum=200,
                step=0.1,
                default=10.0,
                icon="mdi:cup-water",
            )
        )

    # Caserole zona cu suprapunere, pe poziții.
    defs.extend(
        [
            ZoneFlowNumberDef(
                value_key=VAL_DEPTH_B_MID_INNER,
                name="Caserolă · mijloc (interior)",
                unit=UnitOfLength.MILLIMETERS,
                minimum=0,
                maximum=200,
                step=0.1,
                default=10.0,
                icon="mdi:cup-water",
            ),
            ZoneFlowNumberDef(
                value_key=VAL_DEPTH_B_MID_MARGIN,
                name="Caserolă · mijloc (margine)",
                unit=UnitOfLength.MILLIMETERS,
                minimum=0,
                maximum=200,
                step=0.1,
                default=6.0,
                icon="mdi:cup-water",
            ),
            ZoneFlowNumberDef(
                value_key=VAL_DEPTH_B_EDGE_MARGIN,
                name="Caserolă · margine",
                unit=UnitOfLength.MILLIMETERS,
                minimum=0,
                maximum=200,
                step=0.1,
                default=8.0,
                icon="mdi:cup-water",
            ),
            ZoneFlowNumberDef(
                value_key=VAL_FACTOR,
                name="Factor corecție",
                unit=None,
                minimum=0,
                maximum=3,
                step=0.05,
                default=1.0,
                icon="mdi:tune",
            ),
        ]
    )
    return defs


async def async_setup_entry(
    hass: HomeAssistant,
    entry: ZoneFlowConfigEntry,
    async_add_entities: AddEntitiesCallback,
) -> None:
    coordinator = entry.runtime_data
    async_add_entities(
        ZoneFlowNumber(coordinator, definition) for definition in _build_defs()
    )


class ZoneFlowNumber(ZoneFlowEntity, RestoreNumber, NumberEntity):
    """Parametru reglabil, persistent, care alimentează calculele coordinatorului."""

    _attr_mode = NumberMode.BOX

    def __init__(
        self, coordinator: ZoneFlowCoordinator, definition: ZoneFlowNumberDef
    ) -> None:
        super().__init__(coordinator)
        self._def = definition
        self._attr_unique_id = f"{coordinator.entry.entry_id}_{definition.value_key}"
        self._attr_name = definition.name
        self._attr_native_unit_of_measurement = definition.unit
        self._attr_native_min_value = definition.minimum
        self._attr_native_max_value = definition.maximum
        self._attr_native_step = definition.step
        self._attr_icon = definition.icon
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
