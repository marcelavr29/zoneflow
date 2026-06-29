"""Coordinatorul integrării: prognoză, calcule, programare și execuția udării."""

from __future__ import annotations

import asyncio
import datetime as dt
import logging

from homeassistant.config_entries import ConfigEntry
from homeassistant.core import CALLBACK_TYPE, HomeAssistant, callback
from homeassistant.helpers.event import async_track_time_change
from homeassistant.helpers.storage import Store
from homeassistant.helpers.update_coordinator import DataUpdateCoordinator
from homeassistant.util import dt as dt_util

from . import calc
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
    DEFAULT_FORECAST_DAYS,
    DEFAULT_TEST_MINUTES,
    DEFAULT_INTERVAL_DAYS,
    DOMAIN,
    RAIN_WINDOW_HOURS,
    VAL_ENABLED,
    VAL_FACTOR,
    VAL_INTERVAL,
    VAL_RAIN_COMP,
    VAL_START_TIME,
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

        # Valori reglabile live (factor / enable / oră / interval / compensare ploaie).
        self.values: dict[str, object] = {}
        self.avg_temp: float | None = None
        self.rain_mm: float = 0.0  # ploaie prevăzută (ponderată) pe fereastra de 24h

        self.is_watering = False
        self._watering_task: asyncio.Task | None = None
        self._unsub_time: CALLBACK_TYPE | None = None

        # Data ultimei udări reale (persistată) — baza intervalului între udări.
        self.last_run: dt.date | None = None
        self._store: Store = Store(hass, 1, f"{DOMAIN}_{entry.entry_id}")

    async def async_load_store(self) -> None:
        """Încarcă `last_run` din storage; la prima instalare îl ancorează la azi."""
        data = await self._store.async_load()
        stored = (data or {}).get("last_run")
        if stored:
            try:
                self.last_run = dt.date.fromisoformat(stored)
            except ValueError:
                self.last_run = None
        if self.last_run is None:
            self.last_run = dt_util.now().date()
            await self._save_last_run()

    async def _save_last_run(self) -> None:
        await self._store.async_save(
            {"last_run": self.last_run.isoformat() if self.last_run else None}
        )

    # --------------------------------------------------------------- topologie
    @property
    def zones(self) -> list[dict]:
        return self.entry.options.get(CONF_ZONES, [])

    def groups_in_order(self) -> list[dict]:
        """Lista plată de grupuri în ordinea de udare (zone în ordine, grupuri în ordine).

        Fiecare element conține și `zone_name` + `display_name` pentru entități/loguri.
        Grupurile rulează secvențial; supapele dintr-un grup pornesc simultan.
        """
        ordered: list[dict] = []
        for zone in self.zones:
            for group in zone.get(CONF_GROUPS, []):
                ordered.append(
                    {
                        **group,
                        "zone_name": zone.get(CONF_NAME, ""),
                        "display_name": f"{zone.get(CONF_NAME, '')} · {group.get(CONF_NAME, '')}",
                    }
                )
        return ordered

    def all_switches(self) -> list[str]:
        """Toate entity_id-urile de switch din toate grupurile (unice)."""
        seen: list[str] = []
        for group in self.groups_in_order():
            for switch in group.get(CONF_SWITCHES, []):
                if switch and switch not in seen:
                    seen.append(switch)
        return seen

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
        if key in (VAL_START_TIME, VAL_ENABLED, VAL_INTERVAL):
            self._reschedule()
        self.recompute()

    # ------------------------------------------------------------- prognoză
    async def _get_forecast(self, forecast_type: str) -> list[dict]:
        """Lista de prognoză de un anumit tip (daily/twice_daily/hourly) sau [] dacă lipsește."""
        try:
            resp = await self.hass.services.async_call(
                "weather",
                "get_forecasts",
                {"entity_id": self.weather_entity, "type": forecast_type},
                blocking=True,
                return_response=True,
            )
        except Exception as err:  # noqa: BLE001 - tipul poate să nu fie suportat
            _LOGGER.debug("Prognoza '%s' indisponibilă (%s)", forecast_type, err)
            return []
        return (resp or {}).get(self.weather_entity, {}).get("forecast", []) or []

    async def _fetch_avg_temp(self) -> float | None:
        """Media temperaturii din prognoză, încercând mai multe tipuri (entitățile diferă)."""
        limits = {"daily": self.forecast_days, "twice_daily": self.forecast_days * 2, "hourly": self.forecast_days * 24}
        for ftype in ("daily", "twice_daily", "hourly"):
            forecasts = await self._get_forecast(ftype)
            if not forecasts:
                continue
            temps = [f.get("temperature") for f in forecasts[: limits[ftype]]]
            avg = calc.weekly_avg(temps)
            if avg is not None:
                _LOGGER.debug("Media temperaturii din prognoza '%s' = %.1f", ftype, avg)
                return avg
        _LOGGER.warning(
            "Entitatea weather %s nu oferă prognoză cu temperatură; folosesc temperatura curentă",
            self.weather_entity,
        )
        return self._current_temp_fallback()

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
        forecasts = await self._get_forecast("hourly")
        if not forecasts:
            return 0.0
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
        """Timpii de rulare [minute] per grup (cheie = id grup), din ținta efectivă.

        Per zonă rezolvă sistemul porțiuni × grupuri (`calc.solve_runtimes`), astfel încât
        fiecare porțiune să primească ținta.
        """
        target = self._effective_target()
        runtimes: dict[str, float] = {}

        for zone in self.zones:
            sections = zone.get(CONF_SECTIONS, [])
            groups = zone.get(CONF_GROUPS, [])
            for group in groups:
                runtimes[group.get(CONF_ID)] = 0.0
            if not sections or not groups or target is None:
                continue
            # A[porțiune][grup] = rata de precipitație (mm/min) a grupului pe acea porțiune.
            matrix = [
                [
                    calc.precip_rate(
                        _num(group.get(CONF_RATES, {}).get(section.get(CONF_ID)), 0.0),
                        self.test_minutes,
                    )
                    for group in groups
                ]
                for section in sections
            ]
            solved = calc.solve_runtimes(matrix, target)
            for group, minutes in zip(groups, solved):
                runtimes[group.get(CONF_ID)] = minutes
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
        """Litri pe sesiune ≈ ținta × suma suprafețelor tuturor porțiunilor."""
        if target is None:
            return 0.0
        total_area = sum(
            _num(section.get(CONF_AREA), DEFAULT_AREA)
            for zone in self.zones
            for section in zone.get(CONF_SECTIONS, [])
        )
        return target * total_area

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
            "last_run": self.last_run.isoformat() if self.last_run else None,
            "interval_days": self._interval(),
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

    def _interval(self) -> int:
        return max(1, int(self.get_float(VAL_INTERVAL, DEFAULT_INTERVAL_DAYS)))

    @callback
    def _scheduled_fire(self, now: dt.datetime) -> None:
        if not self.get_bool(VAL_ENABLED, True):
            return
        if self.last_run is None:
            self.last_run = now.date()
        if (now.date() - self.last_run).days >= self._interval():
            _LOGGER.info("Pornire programată a irigației (interval atins)")
            self.start_watering()

    def _next_run(self) -> dt.datetime | None:
        start = self._start_time()
        if start is None or not self.get_bool(VAL_ENABLED, True):
            return None
        now = dt_util.now()
        base = self.last_run or now.date()
        due = base + dt.timedelta(days=self._interval())
        d = max(due, now.date())
        cand = dt.datetime.combine(d, start, tzinfo=now.tzinfo)
        if cand <= now:
            cand = dt.datetime.combine(d + dt.timedelta(days=1), start, tzinfo=now.tzinfo)
        return cand

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
        groups = self.groups_in_order()
        if not any(runtimes.get(g.get(CONF_ID), 0.0) > 0 for g in groups):
            _LOGGER.info(
                "Sar peste udare: nimic de udat (ploaie prevăzută %.1f mm ≥ țintă, sau țintă 0)",
                self._rain(),
            )
            return
        self.is_watering = True
        watered = False
        self.async_update_listeners()
        try:
            for group in groups:
                minutes = runtimes.get(group.get(CONF_ID), 0.0)
                switches = [s for s in group.get(CONF_SWITCHES, []) if s]
                if minutes <= 0 or not switches:
                    continue
                await self._run_group(switches, minutes)
                watered = True
        except asyncio.CancelledError:
            _LOGGER.info("Ciclu de udare anulat")
            raise
        finally:
            await self.async_all_off()
            self.is_watering = False
            self._watering_task = None
            if watered:
                # Udare reală → resetăm ceasul intervalului (persistat).
                self.last_run = dt_util.now().date()
                self.hass.async_create_task(self._save_last_run())
            self.async_update_listeners()
            self.recompute()

    async def _run_group(self, switches: list[str], minutes: float) -> None:
        """Pornește toate supapele grupului SIMULTAN, așteaptă, apoi le oprește."""
        _LOGGER.info("Pornesc grupul %s pentru %.1f min", switches, minutes)
        await self.hass.services.async_call(
            "switch", "turn_on", {"entity_id": switches}, blocking=True
        )
        try:
            await asyncio.sleep(minutes * 60)
        finally:
            # Oprim grupul chiar dacă ciclul a fost anulat în timpul așteptării.
            await self.hass.services.async_call(
                "switch", "turn_off", {"entity_id": switches}, blocking=True
            )

    async def async_all_off(self) -> None:
        """Oprește toate supapele (siguranță)."""
        switches = self.all_switches()
        if not switches:
            return
        try:
            await self.hass.services.async_call(
                "switch", "turn_off", {"entity_id": switches}, blocking=True
            )
        except Exception as err:  # noqa: BLE001
            _LOGGER.debug("Nu pot opri supapele %s: %s", switches, err)

    @callback
    def async_shutdown_schedule(self) -> None:
        if self._unsub_time is not None:
            self._unsub_time()
            self._unsub_time = None
