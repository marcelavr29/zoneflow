"""Config flow pentru integrarea ZoneFlow."""

from __future__ import annotations

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
    CONF_FORECAST_DAYS,
    CONF_TEST_MINUTES,
    CONF_WEATHER_ENTITY,
    CONF_ZONE_A_C1,
    CONF_ZONE_A_C2,
    CONF_ZONE_B_EDGE,
    CONF_ZONE_B_MID,
    DEFAULT_FORECAST_DAYS,
    DEFAULT_TEST_MINUTES,
    DOMAIN,
)

_SWITCH_SELECTOR = selector.EntitySelector(
    selector.EntitySelectorConfig(domain="switch")
)
_WEATHER_SELECTOR = selector.EntitySelector(
    selector.EntitySelectorConfig(domain="weather")
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
    """Configurarea inițială: setări generale + topologia circuitelor."""

    VERSION = 1

    def __init__(self) -> None:
        self._data: dict[str, Any] = {}

    async def async_step_user(
        self, user_input: dict[str, Any] | None = None
    ) -> ConfigFlowResult:
        if user_input is not None:
            self._data.update(user_input)
            return await self.async_step_zone_a()
        return self.async_show_form(
            step_id="user", data_schema=_general_schema(self._data)
        )

    async def async_step_zone_a(
        self, user_input: dict[str, Any] | None = None
    ) -> ConfigFlowResult:
        if user_input is not None:
            self._data.update(user_input)
            return await self.async_step_zone_b()
        schema = vol.Schema(
            {
                vol.Required(CONF_ZONE_A_C1): _SWITCH_SELECTOR,
                vol.Required(CONF_ZONE_A_C2): _SWITCH_SELECTOR,
            }
        )
        return self.async_show_form(step_id="zone_a", data_schema=schema)

    async def async_step_zone_b(
        self, user_input: dict[str, Any] | None = None
    ) -> ConfigFlowResult:
        if user_input is not None:
            self._data.update(user_input)
            return self.async_create_entry(title="ZoneFlow", data=self._data)
        schema = vol.Schema(
            {
                vol.Required(CONF_ZONE_B_MID): _SWITCH_SELECTOR,
                vol.Required(CONF_ZONE_B_EDGE): _SWITCH_SELECTOR,
            }
        )
        return self.async_show_form(step_id="zone_b", data_schema=schema)

    @staticmethod
    @callback
    def async_get_options_flow(config_entry: ConfigEntry) -> OptionsFlow:
        return ZoneFlowOptionsFlow()


class ZoneFlowOptionsFlow(OptionsFlow):
    """Permite ajustarea setărilor generale (weather, durată test, orizont)."""

    async def async_step_init(
        self, user_input: dict[str, Any] | None = None
    ) -> ConfigFlowResult:
        entry = self.config_entry
        if user_input is not None:
            data = {**entry.data, **user_input}
            self.hass.config_entries.async_update_entry(entry, data=data)
            return self.async_create_entry(title="", data={})
        return self.async_show_form(
            step_id="init", data_schema=_general_schema(dict(entry.data))
        )
