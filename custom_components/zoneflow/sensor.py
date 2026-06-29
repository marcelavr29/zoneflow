"""Senzori: media temperaturii, ținta, timpii de rulare, litri, următoarea udare."""

from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass

from homeassistant.components.sensor import (
    SensorDeviceClass,
    SensorEntity,
    SensorStateClass,
)
from homeassistant.const import UnitOfTemperature, UnitOfTime, UnitOfVolume
from homeassistant.core import HomeAssistant
from homeassistant.helpers.entity_platform import AddEntitiesCallback
from homeassistant.helpers.update_coordinator import CoordinatorEntity

from . import ZoneFlowConfigEntry
from .const import CIRCUIT_KEYS, CIRCUIT_NAMES
from .coordinator import ZoneFlowCoordinator
from .entity import ZoneFlowEntity


@dataclass(frozen=True, kw_only=True)
class ZoneFlowSensorDef:
    key: str
    name: str
    value_fn: Callable[[dict], object]
    unit: str | None = None
    device_class: SensorDeviceClass | None = None
    state_class: SensorStateClass | None = None
    icon: str | None = None
    suggested_precision: int | None = None


def _runtime(key: str) -> Callable[[dict], object]:
    def _fn(data: dict) -> object:
        val = data.get("runtimes", {}).get(key)
        return round(val, 1) if val is not None else None

    return _fn


def _build_defs() -> list[ZoneFlowSensorDef]:
    defs: list[ZoneFlowSensorDef] = [
        ZoneFlowSensorDef(
            key="avg_temp",
            name="Media temperaturii (săptămână)",
            value_fn=lambda d: d.get("avg_temp"),
            unit=UnitOfTemperature.CELSIUS,
            device_class=SensorDeviceClass.TEMPERATURE,
            state_class=SensorStateClass.MEASUREMENT,
            suggested_precision=1,
        ),
        ZoneFlowSensorDef(
            key="target_mm",
            name="Țintă apă",
            value_fn=lambda d: d.get("target_mm"),
            unit="L/m²",
            icon="mdi:water",
            state_class=SensorStateClass.MEASUREMENT,
            suggested_precision=1,
        ),
        ZoneFlowSensorDef(
            key="liters",
            name="Apă pe sesiune",
            value_fn=lambda d: d.get("liters"),
            unit=UnitOfVolume.LITERS,
            icon="mdi:water-pump",
            state_class=SensorStateClass.MEASUREMENT,
            suggested_precision=0,
        ),
        ZoneFlowSensorDef(
            key="next_run",
            name="Următoarea udare",
            value_fn=lambda d: d.get("next_run"),
            device_class=SensorDeviceClass.TIMESTAMP,
            icon="mdi:calendar-clock",
        ),
    ]

    for key in CIRCUIT_KEYS:
        defs.append(
            ZoneFlowSensorDef(
                key=f"runtime_{key}",
                name=f"Durată · {CIRCUIT_NAMES[key]}",
                value_fn=_runtime(key),
                unit=UnitOfTime.MINUTES,
                icon="mdi:timer-sand",
                suggested_precision=1,
            )
        )
    return defs


async def async_setup_entry(
    hass: HomeAssistant,
    entry: ZoneFlowConfigEntry,
    async_add_entities: AddEntitiesCallback,
) -> None:
    coordinator = entry.runtime_data
    async_add_entities(
        ZoneFlowSensor(coordinator, definition) for definition in _build_defs()
    )


class ZoneFlowSensor(ZoneFlowEntity, CoordinatorEntity[ZoneFlowCoordinator], SensorEntity):
    """Senzor derivat din datele coordinatorului."""

    def __init__(
        self, coordinator: ZoneFlowCoordinator, definition: ZoneFlowSensorDef
    ) -> None:
        CoordinatorEntity.__init__(self, coordinator)
        ZoneFlowEntity.__init__(self, coordinator)
        self._def = definition
        self._attr_unique_id = f"{coordinator.entry.entry_id}_{definition.key}"
        self._attr_name = definition.name
        self._attr_native_unit_of_measurement = definition.unit
        self._attr_device_class = definition.device_class
        self._attr_state_class = definition.state_class
        self._attr_icon = definition.icon
        if definition.suggested_precision is not None:
            self._attr_suggested_display_precision = definition.suggested_precision

    @property
    def native_value(self) -> object:
        if self.coordinator.data is None:
            return None
        return self._def.value_fn(self.coordinator.data)
