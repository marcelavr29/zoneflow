"""Config flow + options flow ZoneFlow (zone → porțiuni + grupuri de supape)."""

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
    CONF_FORECAST_DAYS,
    CONF_GROUPS,
    CONF_ID,
    CONF_NAME,
    CONF_RATES,
    CONF_SECTIONS,
    CONF_SWITCHES,
    CONF_TEST_MINUTES,
    CONF_WEATHER_ENTITY,
    CONF_ZONES,
    DEFAULT_AREA,
    DEFAULT_DEPTH,
    DEFAULT_FORECAST_DAYS,
    DEFAULT_SECTION_NAME,
    DEFAULT_TEST_MINUTES,
    DOMAIN,
)

_SWITCHES_SELECTOR = selector.EntitySelector(
    selector.EntitySelectorConfig(domain="switch", multiple=True)
)
_WEATHER_SELECTOR = selector.EntitySelector(
    selector.EntitySelectorConfig(domain="weather")
)


def _new_id() -> str:
    return uuid.uuid4().hex[:8]


def _menu(options: list[tuple[str, str]]) -> selector.SelectSelector:
    return selector.SelectSelector(
        selector.SelectSelectorConfig(
            options=[selector.SelectOptionDict(value=v, label=l) for v, l in options],
            mode=selector.SelectSelectorMode.LIST,
        )
    )


def _rate_number() -> selector.NumberSelector:
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

    VERSION = 3

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
    """Meniu de configurare a zonelor (porțiuni + grupuri de supape)."""

    def __init__(self) -> None:
        self._zones: list[dict] = []
        self._zone_id: str | None = None
        self._group_id: str | None = None
        self._section_id: str | None = None
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
            return self._commit()

        options = [("general", "⚙️ Setări generale"), ("add_zone", "➕ Adaugă zonă")]
        if self._zones:
            options.append(("edit_zone", "✏️ Editează / șterge zonă"))
        options.append(("finish", "💾 Salvează și ieși"))

        summary = "\n".join(
            f"• {z.get(CONF_NAME)} — {len(z.get(CONF_SECTIONS, []))} porțiuni, "
            f"{len(z.get(CONF_GROUPS, []))} grupuri"
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
                # Porțiune implicită: zonele simple sunt gata imediat.
                CONF_SECTIONS: [
                    {CONF_ID: _new_id(), CONF_NAME: DEFAULT_SECTION_NAME, CONF_AREA: DEFAULT_AREA}
                ],
                CONF_GROUPS: [],
            }
            self._zones.append(zone)
            self._zone_id = zone[CONF_ID]
            return await self.async_step_zone_menu()
        return self.async_show_form(
            step_id="add_zone", data_schema=vol.Schema({vol.Required(CONF_NAME): str})
        )

    async def async_step_edit_zone(
        self, user_input: dict[str, Any] | None = None
    ) -> ConfigFlowResult:
        if user_input is not None:
            self._zone_id = user_input["zone"]
            return await self.async_step_zone_menu()
        return self.async_show_form(
            step_id="edit_zone", data_schema=self._pick_schema("zone", self._zones)
        )

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
            if action == "sections":
                return await self.async_step_sections()
            if action == "add_group":
                return await self.async_step_add_group()
            if action == "edit_group":
                return await self.async_step_edit_group()
            if action == "delete_zone":
                self._zones = [z for z in self._zones if z.get(CONF_ID) != self._zone_id]
                self._zone_id = None
                return await self.async_step_init()
            return await self.async_step_init()

        options = [
            ("rename", "✏️ Redenumește zona"),
            ("sections", "🧩 Gestionează porțiuni"),
            ("add_group", "➕ Adaugă grup (supape)"),
        ]
        if zone.get(CONF_GROUPS):
            options.append(("edit_group", "🔧 Editează / șterge grup"))
        options.append(("delete_zone", "🗑️ Șterge zona"))
        options.append(("back", "⬅️ Înapoi"))

        sect = ", ".join(s.get(CONF_NAME, "") for s in zone.get(CONF_SECTIONS, [])) or "—"
        grp = "\n".join(
            f"• {g.get(CONF_NAME)} → {', '.join(g.get(CONF_SWITCHES, []) or ['(fără supape)'])}"
            for g in zone.get(CONF_GROUPS, [])
        ) or "(niciun grup)"
        return self.async_show_form(
            step_id="zone_menu",
            data_schema=vol.Schema({vol.Required("action"): _menu(options)}),
            description_placeholders={
                "zone": zone.get(CONF_NAME, ""),
                "sections": sect,
                "groups": grp,
            },
        )

    async def async_step_rename_zone(
        self, user_input: dict[str, Any] | None = None
    ) -> ConfigFlowResult:
        zone = self._zone()
        if zone is None:
            return await self.async_step_init()
        if user_input is not None:
            zone[CONF_NAME] = user_input[CONF_NAME]
            return await self.async_step_zone_menu()
        return self.async_show_form(
            step_id="rename_zone",
            data_schema=vol.Schema({vol.Required(CONF_NAME, default=zone.get(CONF_NAME)): str}),
        )

    # -------------------------------------------------------------- porțiuni
    async def async_step_sections(
        self, user_input: dict[str, Any] | None = None
    ) -> ConfigFlowResult:
        zone = self._zone()
        if zone is None:
            return await self.async_step_init()
        if user_input is not None:
            action = user_input["action"]
            if action == "add_section":
                return await self.async_step_add_section()
            if action == "edit_section":
                return await self.async_step_edit_section()
            return await self.async_step_zone_menu()

        options = [("add_section", "➕ Adaugă porțiune")]
        if zone.get(CONF_SECTIONS):
            options.append(("edit_section", "✏️ Editează / șterge porțiune"))
        options.append(("back", "⬅️ Înapoi"))
        listing = "\n".join(
            f"• {s.get(CONF_NAME)} — {s.get(CONF_AREA, 0)} m²" for s in zone.get(CONF_SECTIONS, [])
        ) or "(nicio porțiune)"
        return self.async_show_form(
            step_id="sections",
            data_schema=vol.Schema({vol.Required("action"): _menu(options)}),
            description_placeholders={"sections": listing},
        )

    async def async_step_add_section(
        self, user_input: dict[str, Any] | None = None
    ) -> ConfigFlowResult:
        zone = self._zone()
        if zone is None:
            return await self.async_step_init()
        if user_input is not None:
            zone.setdefault(CONF_SECTIONS, []).append(
                {
                    CONF_ID: _new_id(),
                    CONF_NAME: user_input[CONF_NAME],
                    CONF_AREA: user_input[CONF_AREA],
                }
            )
            return await self.async_step_sections()
        return self.async_show_form(
            step_id="add_section", data_schema=self._section_schema()
        )

    async def async_step_edit_section(
        self, user_input: dict[str, Any] | None = None
    ) -> ConfigFlowResult:
        zone = self._zone()
        if zone is None:
            return await self.async_step_init()
        sections = zone.get(CONF_SECTIONS, [])
        if user_input is not None:
            sid = user_input["section"]
            if user_input.get("delete"):
                zone[CONF_SECTIONS] = [s for s in sections if s.get(CONF_ID) != sid]
                # curăță rata porțiunii din toate grupurile
                for group in zone.get(CONF_GROUPS, []):
                    group.get(CONF_RATES, {}).pop(sid, None)
                return await self.async_step_sections()
            self._section_id = sid
            return await self.async_step_section_form()
        return self.async_show_form(
            step_id="edit_section",
            data_schema=self._pick_schema("section", sections, with_delete=True),
        )

    async def async_step_section_form(
        self, user_input: dict[str, Any] | None = None
    ) -> ConfigFlowResult:
        zone = self._zone()
        if zone is None:
            return await self.async_step_init()
        section = next(
            (s for s in zone.get(CONF_SECTIONS, []) if s.get(CONF_ID) == self._section_id),
            None,
        )
        if section is None:
            return await self.async_step_sections()
        if user_input is not None:
            section[CONF_NAME] = user_input[CONF_NAME]
            section[CONF_AREA] = user_input[CONF_AREA]
            return await self.async_step_sections()
        return self.async_show_form(
            step_id="section_form",
            data_schema=self._section_schema(section.get(CONF_NAME, ""), section.get(CONF_AREA, DEFAULT_AREA)),
        )

    def _section_schema(self, name: str = "", area: float = DEFAULT_AREA) -> vol.Schema:
        return vol.Schema(
            {
                vol.Required(CONF_NAME, default=name): str,
                vol.Required(CONF_AREA, default=area): _area_number(),
            }
        )

    # ---------------------------------------------------------------- grupuri
    async def async_step_add_group(
        self, user_input: dict[str, Any] | None = None
    ) -> ConfigFlowResult:
        self._group_id = None
        self._draft = {}
        return await self.async_step_group_basic()

    async def async_step_edit_group(
        self, user_input: dict[str, Any] | None = None
    ) -> ConfigFlowResult:
        zone = self._zone()
        if zone is None:
            return await self.async_step_init()
        groups = zone.get(CONF_GROUPS, [])
        if user_input is not None:
            gid = user_input["group"]
            if user_input.get("delete"):
                zone[CONF_GROUPS] = [g for g in groups if g.get(CONF_ID) != gid]
                return await self.async_step_zone_menu()
            self._group_id = gid
            self._draft = copy.deepcopy(next(g for g in groups if g.get(CONF_ID) == gid))
            return await self.async_step_group_basic()
        return self.async_show_form(
            step_id="edit_group",
            data_schema=self._pick_schema("group", groups, with_delete=True),
        )

    async def async_step_group_basic(
        self, user_input: dict[str, Any] | None = None
    ) -> ConfigFlowResult:
        zone = self._zone()
        if zone is None:
            return await self.async_step_init()
        if user_input is not None:
            self._draft[CONF_NAME] = user_input[CONF_NAME]
            self._draft[CONF_SWITCHES] = user_input[CONF_SWITCHES]
            return await self.async_step_group_rates()
        schema = vol.Schema(
            {
                vol.Required(CONF_NAME, default=self._draft.get(CONF_NAME, "")): str,
                vol.Required(
                    CONF_SWITCHES, default=self._draft.get(CONF_SWITCHES, [])
                ): _SWITCHES_SELECTOR,
            }
        )
        return self.async_show_form(
            step_id="group_basic",
            data_schema=schema,
            description_placeholders={"zone": zone.get(CONF_NAME, "")},
        )

    async def async_step_group_rates(
        self, user_input: dict[str, Any] | None = None
    ) -> ConfigFlowResult:
        zone = self._zone()
        if zone is None:
            return await self.async_step_init()
        sections = zone.get(CONF_SECTIONS, [])

        if user_input is not None:
            # Câmpurile sunt cheiate după numele porțiunii; mapăm înapoi la id.
            rates = {
                s[CONF_ID]: user_input.get(s[CONF_NAME], 0.0) for s in sections
            }
            self._draft[CONF_RATES] = rates
            self._save_group(zone)
            return await self.async_step_zone_menu()

        old_rates = self._draft.get(CONF_RATES, {})
        fields = {
            vol.Required(
                s[CONF_NAME], default=old_rates.get(s[CONF_ID], DEFAULT_DEPTH)
            ): _rate_number()
            for s in sections
        }
        return self.async_show_form(
            step_id="group_rates",
            data_schema=vol.Schema(fields),
            description_placeholders={"group": self._draft.get(CONF_NAME, "")},
        )

    def _save_group(self, zone: dict) -> None:
        groups = zone.setdefault(CONF_GROUPS, [])
        if self._group_id is None:
            self._draft[CONF_ID] = _new_id()
            groups.append(self._draft)
        else:
            for idx, g in enumerate(groups):
                if g.get(CONF_ID) == self._group_id:
                    self._draft[CONF_ID] = self._group_id
                    groups[idx] = self._draft
                    break
        self._draft = {}
        self._group_id = None

    # ----------------------------------------------------------------- utils
    def _pick_schema(
        self, key: str, items: list[dict], with_delete: bool = False
    ) -> vol.Schema:
        options = [
            selector.SelectOptionDict(value=i[CONF_ID], label=i.get(CONF_NAME, i[CONF_ID]))
            for i in items
        ]
        fields: dict[Any, Any] = {
            vol.Required(key): selector.SelectSelector(
                selector.SelectSelectorConfig(options=options)
            )
        }
        if with_delete:
            fields[vol.Optional("delete", default=False)] = selector.BooleanSelector()
        return vol.Schema(fields)
