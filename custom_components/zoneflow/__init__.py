"""Integrarea ZoneFlow pentru Home Assistant."""

from __future__ import annotations

from homeassistant.config_entries import ConfigEntry
from homeassistant.core import HomeAssistant, ServiceCall
from homeassistant.helpers import entity_registry as er

from .const import (
    CONF_GROUPS,
    CONF_ID,
    CONF_ZONES,
    DOMAIN,
    PLATFORMS,
    SERVICE_RUN_NOW,
    SERVICE_STOP,
)
from .coordinator import ZoneFlowCoordinator
from .migrate import async_migrate_entry  # noqa: F401  (expus pentru HA)
from .panel import async_register_panel, async_remove_panel
from .websocket import async_register as async_register_ws

type ZoneFlowConfigEntry = ConfigEntry[ZoneFlowCoordinator]


async def async_setup_entry(hass: HomeAssistant, entry: ZoneFlowConfigEntry) -> bool:
    """Configurează o intrare a integrării."""
    coordinator = ZoneFlowCoordinator(hass, entry)
    entry.runtime_data = coordinator

    _async_cleanup_orphans(hass, entry)

    # Încarcă data ultimei udări (baza intervalului între udări).
    await coordinator.async_load_store()

    # Siguranță: la pornire ne asigurăm că toate supapele sunt închise
    # (în caz că HA a fost repornit în mijlocul unui ciclu).
    await coordinator.async_all_off()

    # Prima preluare a prognozei; nu blocăm setup-ul dacă weather nu e gata încă.
    await coordinator.async_config_entry_first_refresh()

    await hass.config_entries.async_forward_entry_setups(entry, PLATFORMS)

    _async_register_services(hass)
    async_register_ws(hass)
    await async_register_panel(hass)
    entry.async_on_unload(entry.add_update_listener(_async_reload_entry))

    return True


def _async_cleanup_orphans(hass: HomeAssistant, entry: ZoneFlowConfigEntry) -> None:
    """Șterge senzorii de durată ai grupurilor care nu mai există în configurație."""
    valid_ids = {
        group.get(CONF_ID)
        for zone in entry.options.get(CONF_ZONES, [])
        for group in zone.get(CONF_GROUPS, [])
    }
    registry = er.async_get(hass)
    prefix = f"{entry.entry_id}_"
    for reg_entry in er.async_entries_for_config_entry(registry, entry.entry_id):
        uid = reg_entry.unique_id
        if not uid.startswith(prefix):
            continue
        suffix = uid[len(prefix) :]
        # Switch-urile vechi de zi (model înlocuit de interval).
        if suffix.startswith("day_"):
            registry.async_remove(reg_entry.entity_id)
            continue
        # Senzori de durată ai grupurilor care nu mai există.
        if suffix.endswith("_runtime"):
            group_id = suffix[: -len("_runtime")]
            if group_id and group_id not in valid_ids:
                registry.async_remove(reg_entry.entity_id)


async def async_unload_entry(hass: HomeAssistant, entry: ZoneFlowConfigEntry) -> bool:
    """Descarcă o intrare."""
    coordinator = entry.runtime_data
    coordinator.async_shutdown_schedule()
    await coordinator.async_stop_watering()
    # NU scoatem panoul aici: `async_unload_entry` rulează și la fiecare reload (ex. după
    # salvarea unei zone), iar eliminarea panoului vizibil ar redirecționa către dashboard.
    # Panoul se scoate doar la ștergerea integrării — vezi `async_remove_entry`.
    return await hass.config_entries.async_unload_platforms(entry, PLATFORMS)


async def async_remove_entry(hass: HomeAssistant, entry: ZoneFlowConfigEntry) -> None:
    """Apelat DOAR la ștergerea integrării (nu la reload): scoatem panoul."""
    remaining = [
        e for e in hass.config_entries.async_entries(DOMAIN) if e.entry_id != entry.entry_id
    ]
    if not remaining:
        async_remove_panel(hass)
        store = hass.data.get(DOMAIN, {})
        store.pop("panel_registered", None)
        store.pop("ws_registered", None)


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
