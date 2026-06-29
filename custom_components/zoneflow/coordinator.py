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
    MODE_OVERLAP,
    RAIN_WINDOW_HOURS,
    ROLE_EDGE,
    ROLE_PRIMARY,
    VAL_DAY,
    VAL_ENABLED,
    VAL_FACTOR,
    VAL_RAIN_COMP,
    VAL_START_TIME,
    WEEKDAYS,
)

_LOGGER = logging.getLogger(__name__)

UPDATE_INTERVAL = dt.timedelta(hours=1)


def _num(value: object, default: float) -> float:
    try:
        return float(value) if value is not None else default
    except (TypeError, ValueError):
        return default


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

        # Valori reglabile live (factor / enable / zile / oră / compensare ploaie).
        self.values: dict[str, object] = {}
        self.avg_temp: float | None = None
        self.rain_mm: float = 0.0  # ploaie prevăzută (ponderată) pe fereastra de 24h

        self.is_watering = False
        self._watering_task: asyncio.Task | None = None
        self._unsub_time: CALLBACK_TYPE | None = None

    # --------------------------------------------------------------- topologie
    @property
    def zones(self) -> list[dict]:
        return self.entry.options.get(CONF_ZONES, [])

    def circuits_in_order(self) -> list[dict]:
        """Lista plată de circuite în ordinea de udare, adnotate cu zona.

        În fiecare zonă: primarul rulează primul, apoi circuitele margine, apoi cele simple.
        Fiecare element conține și `zone_name` + `display_name` pentru entități/loguri.
        """
        ordered: list[dict] = []
        for zone in self.zones:
            circuits = list(zone.get(CONF_CIRCUITS, []))
            circuits.sort(key=lambda c: {ROLE_PRIMARY: 0, ROLE_EDGE: 1}.get(c.get(CONF_ROLE), 2))
            for circuit in circuits:
                ordered.append(
                    {
                        **circuit,
                        "zone_name": zone.get(CONF_NAME, ""),
                        "display_name": f"{zone.get(CONF_NAME, '')} · {circuit.get(CONF_NAME, '')}",
                    }
                )
        return ordered

    def switch_for(self, circuit_id: str) -> str | None:
        for circuit in self.circuits_in_order():
            if circuit.get(CONF_ID) == circuit_id:
                return circuit.get(CONF_SWITCH)
        return None

    # ------------------------------------------------------------------ utils
    def get_float(self, key: str, default: float = 0.0) -> float:
        return _num(self.values.get(key), default)

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

    async def _fetch_rain_mm(self) -> float:
        """Ploaia prevăzută (mm, ponderată cu probabilitatea) pe următoarele ore."""
        try:
            resp = await self.hass.services.async_call(
                "weather",
                "get_forecasts",
                {"entity_id": self.weather_entity, "type": "hourly"},
                blocking=True,
                return_response=True,
            )
        except Exception as err:  # noqa: BLE001 - unele entități nu au prognoză orară
            _LOGGER.debug("Fără prognoză orară pentru ploaie (%s)", err)
            return 0.0

        forecasts = (resp or {}).get(self.weather_entity, {}).get("forecast", [])
        now = dt_util.utcnow()
        start = now - dt.timedelta(hours=1)  # includem ora curentă
        horizon = now + dt.timedelta(hours=RAIN_WINDOW_HOURS)
        entries = []
        for item in forecasts:
            when = dt_util.parse_datetime(item.get("datetime", ""))
            if when is None:
                continue
            when = dt_util.as_utc(when)
            if start <= when <= horizon:
                entries.append(
                    (item.get("precipitation"), item.get("precipitation_probability"))
                )
        return calc.weighted_precipitation(entries)

    async def _async_update_data(self) -> dict:
        self.avg_temp = await self._fetch_avg_temp()
        self.rain_mm = await self._fetch_rain_mm()
        return self._build_data()

    # --------------------------------------------------------------- calcule
    def compute_runtimes(self) -> dict[str, float]:
        """Timpii de rulare [minute] per circuit (cheie = id circuit), din ținta efectivă."""
        target = self._effective_target()
        runtimes: dict[str, float] = {}
        if target is None:
            for circuit in self.circuits_in_order():
                runtimes[circuit.get(CONF_ID)] = 0.0
            return runtimes

        for zone in self.zones:
            circuits = zone.get(CONF_CIRCUITS, [])
            if zone.get(CONF_MODE) == MODE_OVERLAP:
                primary = next(
                    (c for c in circuits if c.get(CONF_ROLE) == ROLE_PRIMARY), None
                )
                t_primary = 0.0
                margin_depth = 0.0
                if primary is not None:
                    t_primary = calc.runtime_simple(
                        target, _num(primary.get(CONF_DEPTH_INNER), DEFAULT_DEPTH), self.test_minutes
                    )
                    margin_depth = _num(primary.get(CONF_DEPTH_MARGIN), DEFAULT_DEPTH)
                    runtimes[primary.get(CONF_ID)] = t_primary
                for circuit in circuits:
                    if circuit.get(CONF_ROLE) == ROLE_EDGE:
                        runtimes[circuit.get(CONF_ID)] = calc.runtime_edge(
                            target,
                            t_primary,
                            margin_depth,
                            _num(circuit.get(CONF_DEPTH), DEFAULT_DEPTH),
                            self.test_minutes,
                        )
            else:
                for circuit in circuits:
                    runtimes[circuit.get(CONF_ID)] = calc.runtime_simple(
                        target, _num(circuit.get(CONF_DEPTH), DEFAULT_DEPTH), self.test_minutes
                    )
        return runtimes

    def _gross_target(self) -> float | None:
        """Ținta din temperatură, înainte de scăderea ploii."""
        return calc.target_mm(self.avg_temp, self.get_float(VAL_FACTOR, 1.0))

    def _rain(self) -> float:
        """Ploaia luată în calcul (0 dacă compensarea e dezactivată)."""
        return self.rain_mm if self.get_bool(VAL_RAIN_COMP, True) else 0.0

    def _effective_target(self) -> float | None:
        return calc.effective_target(self._gross_target(), self._rain())

    def _session_liters(self, target: float | None, runtimes: dict[str, float]) -> float:
        if target is None:
            return 0.0
        liters = 0.0
        for zone in self.zones:
            for circuit in zone.get(CONF_CIRCUITS, []):
                area = _num(circuit.get(CONF_AREA), DEFAULT_AREA)
                if circuit.get(CONF_ROLE) == ROLE_EDGE:
                    # Edge-ul adaugă apă suplimentară pe sub-zona lui.
                    liters += (
                        calc.precip_rate(_num(circuit.get(CONF_DEPTH), DEFAULT_DEPTH), self.test_minutes)
                        * runtimes.get(circuit.get(CONF_ID), 0.0)
                        * area
                    )
                else:
                    # Primar / simplu: livrează ținta peste suprafața lui.
                    liters += target * area
        return liters

    def _build_data(self) -> dict:
        gross = self._gross_target()
        effective = self._effective_target()
        runtimes = self.compute_runtimes()
        rain = self._rain()
        will_skip = (
            gross is not None and gross > 0 and effective is not None and effective <= 0
        )
        return {
            "avg_temp": self.avg_temp,
            "target_mm": gross,
            "effective_target_mm": effective,
            "rain_mm": rain,
            "rain_forecast_mm": self.rain_mm,
            "will_skip": will_skip,
            "runtimes": runtimes,
            "liters": self._session_liters(effective, runtimes),
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
        circuits = self.circuits_in_order()
        if not any(runtimes.get(c.get(CONF_ID), 0.0) > 0 for c in circuits):
            _LOGGER.info(
                "Sar peste udare: nimic de udat (ploaie prevăzută %.1f mm ≥ țintă, sau țintă 0)",
                self._rain(),
            )
            return
        self.is_watering = True
        self.async_update_listeners()
        try:
            for circuit in circuits:
                minutes = runtimes.get(circuit.get(CONF_ID), 0.0)
                switch_entity = circuit.get(CONF_SWITCH)
                if minutes <= 0 or not switch_entity:
                    continue
                await self._run_circuit(switch_entity, minutes)
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
        seen: set[str] = set()
        for circuit in self.circuits_in_order():
            switch_entity = circuit.get(CONF_SWITCH)
            if not switch_entity or switch_entity in seen:
                continue
            seen.add(switch_entity)
            try:
                await self.hass.services.async_call(
                    "switch", "turn_off", {"entity_id": switch_entity}, blocking=True
                )
            except Exception as err:  # noqa: BLE001
                _LOGGER.debug("Nu pot opri %s: %s", switch_entity, err)

    @callback
    def async_shutdown_schedule(self) -> None:
        if self._unsub_time is not None:
            self._unsub_time()
            self._unsub_time = None
