"""Integrarea ZoneFlow pentru Home Assistant."""

from __future__ import annotations

from homeassistant.config_entries import ConfigEntry
from homeassistant.core import HomeAssistant, ServiceCall

from .const import DOMAIN, PLATFORMS, SERVICE_RUN_NOW, SERVICE_STOP
from .coordinator import ZoneFlowCoordinator

type ZoneFlowConfigEntry = ConfigEntry[ZoneFlowCoordinator]


async def async_setup_entry(hass: HomeAssistant, entry: ZoneFlowConfigEntry) -> bool:
    """Configurează o intrare a integrării."""
    coordinator = ZoneFlowCoordinator(hass, entry)
    entry.runtime_data = coordinator

    # Siguranță: la pornire ne asigurăm că toate supapele sunt închise
    # (în caz că HA a fost repornit în mijlocul unui ciclu).
    await coordinator.async_all_off()

    # Prima preluare a prognozei; nu blocăm setup-ul dacă weather nu e gata încă.
    await coordinator.async_config_entry_first_refresh()

    await hass.config_entries.async_forward_entry_setups(entry, PLATFORMS)

    _async_register_services(hass)
    entry.async_on_unload(entry.add_update_listener(_async_reload_entry))

    return True


async def async_unload_entry(hass: HomeAssistant, entry: ZoneFlowConfigEntry) -> bool:
    """Descarcă o intrare."""
    coordinator = entry.runtime_data
    coordinator.async_shutdown_schedule()
    await coordinator.async_stop_watering()
    return await hass.config_entries.async_unload_platforms(entry, PLATFORMS)


async def _async_reload_entry(hass: HomeAssistant, entry: ZoneFlowConfigEntry) -> None:
    await hass.config_entries.async_reload(entry.entry_id)


def _async_register_services(hass: HomeAssistant) -> None:
    """Înregistrează serviciile globale (idempotent)."""
    if hass.services.has_service(DOMAIN, SERVICE_RUN_NOW):
        return

    async def _handle_run_now(call: ServiceCall) -> None:
        for entry in hass.config_entries.async_entries(DOMAIN):
            coordinator = getattr(entry, "runtime_data", None)
            if coordinator is not None:
                coordinator.start_watering()

    async def _handle_stop(call: ServiceCall) -> None:
        for entry in hass.config_entries.async_entries(DOMAIN):
            coordinator = getattr(entry, "runtime_data", None)
            if coordinator is not None:
                await coordinator.async_stop_watering()

    hass.services.async_register(DOMAIN, SERVICE_RUN_NOW, _handle_run_now)
    hass.services.async_register(DOMAIN, SERVICE_STOP, _handle_stop)
