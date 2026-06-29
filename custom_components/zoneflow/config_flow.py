"""Config flow + options flow pentru ZoneFlow (topologie dinamică de zone/circuite)."""

from __future__ import annotations

import copy
import uuid
from typing import Any

import voluptuous as vol

from homeassistant.config_entries import (
    ConfigEntry,
    ConfigFlow,
    ConfigFlowResult,
    OptionsFlow,
)
from homeassistant.core import callback
from homeassistant.helpers import selector

from .const import (
    CONF_AREA,
    CONF_CIRCUITS,
    CONF_DEPTH,
    CONF_DEPTH_INNER,
    CONF_DEPTH_MARGIN,
    CONF_FORECAST_DAYS,
    CONF_ID,
    CONF_MODE,
    CONF_NAME,
    CONF_ROLE,
    CONF_SWITCH,
    CONF_TEST_MINUTES,
    CONF_WEATHER_ENTITY,
    CONF_ZONES,
    DEFAULT_AREA,
    DEFAULT_DEPTH,
    DEFAULT_FORECAST_DAYS,
    DEFAULT_TEST_MINUTES,
    DOMAIN,
    MODE_INDEPENDENT,
    MODE_OVERLAP,
    ROLE_EDGE,
    ROLE_PRIMARY,
    ROLE_SIMPLE,
)

_SWITCH_SELECTOR = selector.EntitySelector(
    selector.EntitySelectorConfig(domain="switch")
)
_WEATHER_SELECTOR = selector.EntitySelector(
    selector.EntitySelectorConfig(domain="weather")
)


def _new_id() -> str:
    return uuid.uuid4().hex[:8]


def _menu(options: list[tuple[str, str]]) -> selector.SelectSelector:
    """Selector tip listă (acțiuni de meniu) cu etichete inline."""
    return selector.SelectSelector(
        selector.SelectSelectorConfig(
            options=[selector.SelectOptionDict(value=v, label=l) for v, l in options],
            mode=selector.SelectSelectorMode.LIST,
        )
    )


def _mode_selector() -> selector.SelectSelector:
    return selector.SelectSelector(
        selector.SelectSelectorConfig(
            options=[
                selector.SelectOptionDict(value=MODE_INDEPENDENT, label="Independentă (fără suprapunere)"),
                selector.SelectOptionDict(value=MODE_OVERLAP, label="Suprapusă (primar + margine)"),
            ],
            mode=selector.SelectSelectorMode.LIST,
        )
    )


def _role_selector() -> selector.SelectSelector:
    return selector.SelectSelector(
        selector.SelectSelectorConfig(
            options=[
                selector.SelectOptionDict(value=ROLE_PRIMARY, label="Primar (acoperă toată zona)"),
                selector.SelectOptionDict(value=ROLE_EDGE, label="Margine (completează o sub-zonă)"),
            ],
            mode=selector.SelectSelectorMode.LIST,
        )
    )


def _depth_number() -> selector.NumberSelector:
    return selector.NumberSelector(
        selector.NumberSelectorConfig(min=0, max=200, step=0.1, unit_of_measurement="mm")
    )


def _area_number() -> selector.NumberSelector:
    return selector.NumberSelector(
        selector.NumberSelectorConfig(min=0, max=10000, step=0.5, unit_of_measurement="m²")
    )


def _general_schema(defaults: dict[str, Any]) -> vol.Schema:
    return vol.Schema(
        {
            vol.Required(
                CONF_WEATHER_ENTITY, default=defaults.get(CONF_WEATHER_ENTITY)
            ): _WEATHER_SELECTOR,
            vol.Required(
                CONF_TEST_MINUTES,
                default=defaults.get(CONF_TEST_MINUTES, DEFAULT_TEST_MINUTES),
            ): selector.NumberSelector(
                selector.NumberSelectorConfig(min=1, max=120, step=1, unit_of_measurement="min")
            ),
            vol.Required(
                CONF_FORECAST_DAYS,
                default=defaults.get(CONF_FORECAST_DAYS, DEFAULT_FORECAST_DAYS),
            ): selector.NumberSelector(
                selector.NumberSelectorConfig(min=1, max=14, step=1, unit_of_measurement="zile")
            ),
        }
    )


class ZoneFlowConfigFlow(ConfigFlow, domain=DOMAIN):
    """Configurarea inițială: doar setări generale. Zonele se adaugă din Configure."""

    VERSION = 2

    async def async_step_user(
        self, user_input: dict[str, Any] | None = None
    ) -> ConfigFlowResult:
        if user_input is not None:
            return self.async_create_entry(
                title="ZoneFlow", data=user_input, options={CONF_ZONES: []}
            )
        return self.async_show_form(step_id="user", data_schema=_general_schema({}))

    @staticmethod
    @callback
    def async_get_options_flow(config_entry: ConfigEntry) -> OptionsFlow:
        return ZoneFlowOptionsFlow()


class ZoneFlowOptionsFlow(OptionsFlow):
    """Meniu de configurare a zonelor și circuitelor."""

    def __init__(self) -> None:
        self._zones: list[dict] = []
        self._zone_id: str | None = None
        self._circuit_id: str | None = None
        self._draft: dict[str, Any] = {}
        self._loaded = False

    # --------------------------------------------------------------- helpers
    def _ensure_loaded(self) -> None:
        if not self._loaded:
            self._zones = copy.deepcopy(self.config_entry.options.get(CONF_ZONES, []))
            self._loaded = True

    def _zone(self) -> dict | None:
        return next((z for z in self._zones if z.get(CONF_ID) == self._zone_id), None)

    def _commit(self) -> ConfigFlowResult:
        return self.async_create_entry(data={CONF_ZONES: self._zones})

    # ------------------------------------------------------------------ init
    async def async_step_init(
        self, user_input: dict[str, Any] | None = None
    ) -> ConfigFlowResult:
        self._ensure_loaded()
        if user_input is not None:
            action = user_input["action"]
            if action == "general":
                return await self.async_step_general()
            if action == "add_zone":
                return await self.async_step_add_zone()
            if action == "edit_zone":
                return await self.async_step_edit_zone()
            return self._commit()  # "finish"

        options = [
            ("general", "⚙️ Setări generale"),
            ("add_zone", "➕ Adaugă zonă"),
        ]
        if self._zones:
            options.append(("edit_zone", "✏️ Editează / șterge zonă"))
        options.append(("finish", "💾 Salvează și ieși"))

        summary = "\n".join(
            f"• {z.get(CONF_NAME)} ({z.get(CONF_MODE)}) — {len(z.get(CONF_CIRCUITS, []))} circuite"
            for z in self._zones
        ) or "(nicio zonă încă)"
        return self.async_show_form(
            step_id="init",
            data_schema=vol.Schema({vol.Required("action"): _menu(options)}),
            description_placeholders={"zones": summary},
        )

    async def async_step_general(
        self, user_input: dict[str, Any] | None = None
    ) -> ConfigFlowResult:
        if user_input is not None:
            data = {**self.config_entry.data, **user_input}
            self.hass.config_entries.async_update_entry(self.config_entry, data=data)
            return await self.async_step_init()
        return self.async_show_form(
            step_id="general", data_schema=_general_schema(dict(self.config_entry.data))
        )

    # ------------------------------------------------------------------ zone
    async def async_step_add_zone(
        self, user_input: dict[str, Any] | None = None
    ) -> ConfigFlowResult:
        if user_input is not None:
            zone = {
                CONF_ID: _new_id(),
                CONF_NAME: user_input[CONF_NAME],
                CONF_MODE: user_input[CONF_MODE],
                CONF_CIRCUITS: [],
            }
            self._zones.append(zone)
            self._zone_id = zone[CONF_ID]
            return await self.async_step_zone_menu()
        schema = vol.Schema(
            {
                vol.Required(CONF_NAME): str,
                vol.Required(CONF_MODE, default=MODE_INDEPENDENT): _mode_selector(),
            }
        )
        return self.async_show_form(step_id="add_zone", data_schema=schema)

    async def async_step_edit_zone(
        self, user_input: dict[str, Any] | None = None
    ) -> ConfigFlowResult:
        if user_input is not None:
            self._zone_id = user_input["zone"]
            return await self.async_step_zone_menu()
        options = [
            selector.SelectOptionDict(value=z[CONF_ID], label=z.get(CONF_NAME, z[CONF_ID]))
            for z in self._zones
        ]
        schema = vol.Schema(
            {
                vol.Required("zone"): selector.SelectSelector(
                    selector.SelectSelectorConfig(options=options)
                )
            }
        )
        return self.async_show_form(step_id="edit_zone", data_schema=schema)

    async def async_step_zone_menu(
        self, user_input: dict[str, Any] | None = None
    ) -> ConfigFlowResult:
        zone = self._zone()
        if zone is None:
            return await self.async_step_init()
        if user_input is not None:
            action = user_input["action"]
            if action == "rename":
                return await self.async_step_rename_zone()
            if action == "add_circuit":
                return await self.async_step_add_circuit()
            if action == "edit_circuit":
                return await self.async_step_edit_circuit()
            if action == "delete_zone":
                self._zones = [z for z in self._zones if z.get(CONF_ID) != self._zone_id]
                self._zone_id = None
                return await self.async_step_init()
            return await self.async_step_init()  # "back"

        options = [
            ("rename", "✏️ Redenumește / schimbă modul"),
            ("add_circuit", "➕ Adaugă circuit"),
        ]
        if zone.get(CONF_CIRCUITS):
            options.append(("edit_circuit", "🔧 Editează / șterge circuit"))
        options.append(("delete_zone", "🗑️ Șterge zona"))
        options.append(("back", "⬅️ Înapoi"))

        circuits = "\n".join(
            f"• {c.get(CONF_NAME)} [{c.get(CONF_ROLE)}] → {c.get(CONF_SWITCH)}"
            for c in zone.get(CONF_CIRCUITS, [])
        ) or "(niciun circuit)"
        return self.async_show_form(
            step_id="zone_menu",
            data_schema=vol.Schema({vol.Required("action"): _menu(options)}),
            description_placeholders={"zone": zone.get(CONF_NAME, ""), "circuits": circuits},
        )

    async def async_step_rename_zone(
        self, user_input: dict[str, Any] | None = None
    ) -> ConfigFlowResult:
        zone = self._zone()
        if zone is None:
            return await self.async_step_init()
        if user_input is not None:
            zone[CONF_NAME] = user_input[CONF_NAME]
            zone[CONF_MODE] = user_input[CONF_MODE]
            return await self.async_step_zone_menu()
        schema = vol.Schema(
            {
                vol.Required(CONF_NAME, default=zone.get(CONF_NAME)): str,
                vol.Required(
                    CONF_MODE, default=zone.get(CONF_MODE, MODE_INDEPENDENT)
                ): _mode_selector(),
            }
        )
        return self.async_show_form(step_id="rename_zone", data_schema=schema)

    # --------------------------------------------------------------- circuit
    async def async_step_add_circuit(
        self, user_input: dict[str, Any] | None = None
    ) -> ConfigFlowResult:
        self._circuit_id = None
        self._draft = {}
        return await self.async_step_circuit_basic()

    async def async_step_edit_circuit(
        self, user_input: dict[str, Any] | None = None
    ) -> ConfigFlowResult:
        zone = self._zone()
        if zone is None:
            return await self.async_step_init()
        if user_input is not None:
            cid = user_input["circuit"]
            if user_input.get("delete"):
                zone[CONF_CIRCUITS] = [
                    c for c in zone.get(CONF_CIRCUITS, []) if c.get(CONF_ID) != cid
                ]
                return await self.async_step_zone_menu()
            self._circuit_id = cid
            self._draft = dict(
                next(c for c in zone[CONF_CIRCUITS] if c.get(CONF_ID) == cid)
            )
            return await self.async_step_circuit_basic()
        options = [
            selector.SelectOptionDict(value=c[CONF_ID], label=c.get(CONF_NAME, c[CONF_ID]))
            for c in zone.get(CONF_CIRCUITS, [])
        ]
        schema = vol.Schema(
            {
                vol.Required("circuit"): selector.SelectSelector(
                    selector.SelectSelectorConfig(options=options)
                ),
                vol.Optional("delete", default=False): selector.BooleanSelector(),
            }
        )
        return self.async_show_form(step_id="edit_circuit", data_schema=schema)

    async def async_step_circuit_basic(
        self, user_input: dict[str, Any] | None = None
    ) -> ConfigFlowResult:
        zone = self._zone()
        if zone is None:
            return await self.async_step_init()
        overlap = zone.get(CONF_MODE) == MODE_OVERLAP
        if user_input is not None:
            self._draft[CONF_NAME] = user_input[CONF_NAME]
            self._draft[CONF_SWITCH] = user_input[CONF_SWITCH]
            self._draft[CONF_AREA] = user_input[CONF_AREA]
            self._draft[CONF_ROLE] = (
                user_input.get(CONF_ROLE, ROLE_SIMPLE) if overlap else ROLE_SIMPLE
            )
            return await self.async_step_circuit_depths()

        fields: dict[Any, Any] = {
            vol.Required(CONF_NAME, default=self._draft.get(CONF_NAME, "")): str,
            vol.Required(CONF_SWITCH, default=self._draft.get(CONF_SWITCH)): _SWITCH_SELECTOR,
            vol.Required(CONF_AREA, default=self._draft.get(CONF_AREA, DEFAULT_AREA)): _area_number(),
        }
        if overlap:
            fields[
                vol.Required(CONF_ROLE, default=self._draft.get(CONF_ROLE, ROLE_PRIMARY))
            ] = _role_selector()
        return self.async_show_form(
            step_id="circuit_basic",
            data_schema=vol.Schema(fields),
            description_placeholders={"zone": zone.get(CONF_NAME, "")},
        )

    async def async_step_circuit_depths(
        self, user_input: dict[str, Any] | None = None
    ) -> ConfigFlowResult:
        zone = self._zone()
        if zone is None:
            return await self.async_step_init()
        role = self._draft.get(CONF_ROLE, ROLE_SIMPLE)

        if user_input is not None:
            errors: dict[str, str] = {}
            if role == ROLE_PRIMARY:
                for c in zone.get(CONF_CIRCUITS, []):
                    if c.get(CONF_ROLE) == ROLE_PRIMARY and c.get(CONF_ID) != self._circuit_id:
                        errors["base"] = "primary_exists"
                self._draft[CONF_DEPTH_INNER] = user_input[CONF_DEPTH_INNER]
                self._draft[CONF_DEPTH_MARGIN] = user_input[CONF_DEPTH_MARGIN]
            else:
                self._draft[CONF_DEPTH] = user_input[CONF_DEPTH]
            if not errors:
                self._save_draft(zone)
                return await self.async_step_zone_menu()
            return self.async_show_form(
                step_id="circuit_depths",
                data_schema=self._depths_schema(role),
                errors=errors,
            )

        return self.async_show_form(
            step_id="circuit_depths", data_schema=self._depths_schema(role)
        )

    def _depths_schema(self, role: str) -> vol.Schema:
        if role == ROLE_PRIMARY:
            return vol.Schema(
                {
                    vol.Required(
                        CONF_DEPTH_INNER,
                        default=self._draft.get(CONF_DEPTH_INNER, DEFAULT_DEPTH),
                    ): _depth_number(),
                    vol.Required(
                        CONF_DEPTH_MARGIN,
                        default=self._draft.get(CONF_DEPTH_MARGIN, DEFAULT_DEPTH),
                    ): _depth_number(),
                }
            )
        return vol.Schema(
            {
                vol.Required(
                    CONF_DEPTH, default=self._draft.get(CONF_DEPTH, DEFAULT_DEPTH)
                ): _depth_number()
            }
        )

    def _save_draft(self, zone: dict) -> None:
        circuits = zone.setdefault(CONF_CIRCUITS, [])
        if self._circuit_id is None:
            self._draft[CONF_ID] = _new_id()
            circuits.append(self._draft)
        else:
            for idx, c in enumerate(circuits):
                if c.get(CONF_ID) == self._circuit_id:
                    self._draft[CONF_ID] = self._circuit_id
                    circuits[idx] = self._draft
                    break
        self._draft = {}
        self._circuit_id = None
