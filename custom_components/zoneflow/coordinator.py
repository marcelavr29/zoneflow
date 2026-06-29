"""Coordinatorul integrării: prognoză, calcule, programare și execuția udării."""

from __future__ import annotations

import asyncio
import datetime as dt
import logging

from homeassistant.config_entries import ConfigEntry
from homeassistant.core import CALLBACK_TYPE, HomeAssistant, callback
from homeassistant.helpers.event import async_track_time_change
from homeassistant.helpers.update_coordinator import DataUpdateCoordinator
from homeassistant.util import dt as dt_util

from . import calc
from .const import (
    CIRCUIT_CONF,
    CIRCUIT_KEYS,
    CONF_FORECAST_DAYS,
    CONF_TEST_MINUTES,
    CONF_WEATHER_ENTITY,
    DEFAULT_FORECAST_DAYS,
    DEFAULT_TEST_MINUTES,
    DOMAIN,
    VAL_AREA,
    VAL_DEPTH_B_EDGE_MARGIN,
    VAL_DEPTH_B_MID_INNER,
    VAL_DEPTH_B_MID_MARGIN,
    VAL_DEPTH_SIMPLE,
    VAL_DAY,
    VAL_ENABLED,
    VAL_FACTOR,
    VAL_START_TIME,
    WEEKDAYS,
)

_LOGGER = logging.getLogger(__name__)

UPDATE_INTERVAL = dt.timedelta(hours=1)


class ZoneFlowCoordinator(DataUpdateCoordinator):
    """Ține starea sistemului de irigație și execută ciclurile de udare."""

    def __init__(self, hass: HomeAssistant, entry: ConfigEntry) -> None:
        super().__init__(hass, _LOGGER, name=DOMAIN, update_interval=UPDATE_INTERVAL)
        self.entry = entry
        self.weather_entity: str = entry.data[CONF_WEATHER_ENTITY]
        self.test_minutes: float = float(
            entry.data.get(CONF_TEST_MINUTES, DEFAULT_TEST_MINUTES)
        )
        self.forecast_days: int = int(
            entry.data.get(CONF_FORECAST_DAYS, DEFAULT_FORECAST_DAYS)
        )

        # cheie circuit -> entity_id-ul switch-ului care îl controlează
        self.circuits: dict[str, str] = {
            key: entry.data[CIRCUIT_CONF[key]] for key in CIRCUIT_KEYS
        }

        # Valori reglabile, populate de entitățile number/time/switch.
        self.values: dict[str, object] = {}
        self.avg_temp: float | None = None

        self.is_watering = False
        self._watering_task: asyncio.Task | None = None
        self._unsub_time: CALLBACK_TYPE | None = None

    # ------------------------------------------------------------------ utils
    def get_float(self, key: str, default: float = 0.0) -> float:
        val = self.values.get(key)
        try:
            return float(val) if val is not None else default
        except (TypeError, ValueError):
            return default

    def get_bool(self, key: str, default: bool = False) -> bool:
        val = self.values.get(key)
        return bool(val) if val is not None else default

    @callback
    def set_value(self, key: str, value: object) -> None:
        """Apelat de entitățile de reglaj când valoarea se schimbă."""
        self.values[key] = value
        if key == VAL_START_TIME or key == VAL_ENABLED or key in VAL_DAY.values():
            self._reschedule()
        self.recompute()

    # ------------------------------------------------------------- prognoză
    async def _fetch_avg_temp(self) -> float | None:
        """Media temperaturii din prognoza zilnică a entității weather."""
        try:
            resp = await self.hass.services.async_call(
                "weather",
                "get_forecasts",
                {"entity_id": self.weather_entity, "type": "daily"},
                blocking=True,
                return_response=True,
            )
        except Exception as err:  # noqa: BLE001 - degradăm grațios la fallback
            _LOGGER.warning("Nu pot obține prognoza (%s); folosesc temperatura curentă", err)
            return self._current_temp_fallback()

        forecasts = (resp or {}).get(self.weather_entity, {}).get("forecast", [])
        temps = [f.get("temperature") for f in forecasts[: self.forecast_days]]
        avg = calc.weekly_avg(temps)
        if avg is None:
            return self._current_temp_fallback()
        return avg

    def _current_temp_fallback(self) -> float | None:
        state = self.hass.states.get(self.weather_entity)
        if state is not None:
            temp = state.attributes.get("temperature")
            if temp is not None:
                try:
                    return float(temp)
                except (TypeError, ValueError):
                    return None
        return None

    async def _async_update_data(self) -> dict:
        self.avg_temp = await self._fetch_avg_temp()
        return self._build_data()

    # --------------------------------------------------------------- calcule
    def compute_runtimes(self) -> dict[str, float]:
        """Timpii de rulare [minute] pentru fiecare circuit, din ținta curentă."""
        target = self._target()
        runtimes = {key: 0.0 for key in CIRCUIT_KEYS}
        if target is None:
            return runtimes

        for key, depth_key in VAL_DEPTH_SIMPLE.items():
            runtimes[key] = calc.runtime_simple(
                target, self.get_float(depth_key), self.test_minutes
            )

        t_mid, t_edge = calc.runtimes_overlap(
            target,
            self.get_float(VAL_DEPTH_B_MID_INNER),
            self.get_float(VAL_DEPTH_B_MID_MARGIN),
            self.get_float(VAL_DEPTH_B_EDGE_MARGIN),
            self.test_minutes,
        )
        runtimes["b_mid"] = t_mid
        runtimes["b_edge"] = t_edge
        return runtimes

    def _target(self) -> float | None:
        return calc.target_mm(self.avg_temp, self.get_float(VAL_FACTOR, 1.0))

    def _session_liters(self, target: float | None, runtimes: dict[str, float]) -> float:
        if target is None:
            return 0.0
        liters = 0.0
        # Circuitele simple + circuitul mijloc livrează ținta peste suprafața lor.
        for key in ("a1", "a2", "b_mid"):
            liters += target * self.get_float(VAL_AREA[key])
        # Circuitul margine adaugă apă suplimentară doar pe jumătatea-margine.
        liters += (
            calc.precip_rate(self.get_float(VAL_DEPTH_B_EDGE_MARGIN), self.test_minutes)
            * runtimes.get("b_edge", 0.0)
            * self.get_float(VAL_AREA["b_edge"])
        )
        return liters

    def _build_data(self) -> dict:
        target = self._target()
        runtimes = self.compute_runtimes()
        return {
            "avg_temp": self.avg_temp,
            "target_mm": target,
            "runtimes": runtimes,
            "liters": self._session_liters(target, runtimes),
            "next_run": self._next_run(),
        }

    @callback
    def recompute(self) -> None:
        """Recalculează și împinge datele către senzori (fără reluarea prognozei)."""
        if self.hass is None:
            return
        self.async_set_updated_data(self._build_data())

    # ------------------------------------------------------------ programare
    def _start_time(self) -> dt.time | None:
        val = self.values.get(VAL_START_TIME)
        return val if isinstance(val, dt.time) else None

    @callback
    def _reschedule(self) -> None:
        if self._unsub_time is not None:
            self._unsub_time()
            self._unsub_time = None
        start = self._start_time()
        if start is None:
            return
        self._unsub_time = async_track_time_change(
            self.hass, self._scheduled_fire, hour=start.hour, minute=start.minute, second=0
        )

    @callback
    def _scheduled_fire(self, now: dt.datetime) -> None:
        if not self.get_bool(VAL_ENABLED, True):
            return
        weekday_key = WEEKDAYS[now.weekday()]
        if not self.get_bool(VAL_DAY[weekday_key], False):
            return
        _LOGGER.info("Pornire programată a irigației (%s)", weekday_key)
        self.start_watering()

    def _next_run(self) -> dt.datetime | None:
        start = self._start_time()
        if start is None or not self.get_bool(VAL_ENABLED, True):
            return None
        active = [i for i, key in enumerate(WEEKDAYS) if self.get_bool(VAL_DAY[key], False)]
        if not active:
            return None
        now = dt_util.now()
        for offset in range(0, 8):
            cand_date = (now + dt.timedelta(days=offset)).date()
            if cand_date.weekday() not in active:
                continue
            cand = dt.datetime.combine(cand_date, start, tzinfo=now.tzinfo)
            if cand > now:
                return cand
        return None

    # -------------------------------------------------------------- execuție
    @callback
    def start_watering(self) -> None:
        """Pornește un ciclu secvențial dacă nu rulează deja unul."""
        if self.is_watering:
            _LOGGER.warning("Udare deja în curs; ignor cererea de pornire")
            return
        self._watering_task = self.hass.async_create_task(self._run_cycle())

    async def async_stop_watering(self) -> None:
        if self._watering_task is not None and not self._watering_task.done():
            self._watering_task.cancel()
        await self.async_all_off()

    async def _run_cycle(self) -> None:
        runtimes = self.compute_runtimes()
        self.is_watering = True
        self.async_update_listeners()
        try:
            for key in CIRCUIT_KEYS:
                minutes = runtimes.get(key, 0.0)
                if minutes <= 0:
                    continue
                await self._run_circuit(self.circuits[key], minutes)
        except asyncio.CancelledError:
            _LOGGER.info("Ciclu de udare anulat")
            raise
        finally:
            await self.async_all_off()
            self.is_watering = False
            self._watering_task = None
            self.async_update_listeners()

    async def _run_circuit(self, switch_entity: str, minutes: float) -> None:
        _LOGGER.info("Pornesc %s pentru %.1f min", switch_entity, minutes)
        await self.hass.services.async_call(
            "switch", "turn_on", {"entity_id": switch_entity}, blocking=True
        )
        try:
            await asyncio.sleep(minutes * 60)
        finally:
            # Oprim circuitul chiar dacă ciclul a fost anulat în timpul așteptării.
            await self.hass.services.async_call(
                "switch", "turn_off", {"entity_id": switch_entity}, blocking=True
            )

    async def async_all_off(self) -> None:
        """Oprește toate supapele (siguranță)."""
        for entity_id in self.circuits.values():
            try:
                await self.hass.services.async_call(
                    "switch", "turn_off", {"entity_id": entity_id}, blocking=True
                )
            except Exception as err:  # noqa: BLE001
                _LOGGER.debug("Nu pot opri %s: %s", entity_id, err)

    @callback
    def async_shutdown_schedule(self) -> None:
        if self._unsub_time is not None:
            self._unsub_time()
            self._unsub_time = None
