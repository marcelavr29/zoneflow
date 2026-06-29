"""Config flow ZoneFlow.

Setup-ul inițial și options flow-ul gestionează DOAR setările generale. Zonele (porțiuni +
grupuri) se configurează din panoul „ZoneFlow" din bara laterală.
"""

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
    CONF_ZONES,
    DEFAULT_FORECAST_DAYS,
    DEFAULT_TEST_MINUTES,
    DOMAIN,
)


def _general_schema(defaults: dict[str, Any]) -> vol.Schema:
    return vol.Schema(
        {
            vol.Required(
                CONF_WEATHER_ENTITY, default=defaults.get(CONF_WEATHER_ENTITY)
            ): selector.EntitySelector(selector.EntitySelectorConfig(domain="weather")),
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
    """Setup inițial: doar setări generale. Zonele se adaugă din panoul ZoneFlow."""

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
    """Doar setări generale; restul se face în panoul din bara laterală."""

    async def async_step_init(
        self, user_input: dict[str, Any] | None = None
    ) -> ConfigFlowResult:
        if user_input is not None:
            self.hass.config_entries.async_update_entry(
                self.config_entry, data={**self.config_entry.data, **user_input}
            )
            return self.async_create_entry(title="", data=self.config_entry.options)
        return self.async_show_form(
            step_id="init", data_schema=_general_schema(dict(self.config_entry.data))
        )
