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
    CONF_FACTOR_PCT,
    CONF_FORECAST_DAYS,
    CONF_GROUPS,
    CONF_ID,
    CONF_MAX_CYCLE,
    CONF_NAME,
    CONF_RAIN_SENSOR,
    CONF_RATE,
    CONF_SOAK,
    CONF_SWITCHES,
    CONF_TEST_MINUTES,
    CONF_WEATHER_ENTITY,
    CONF_ZONES,
    DEFAULT_AREA,
    DEFAULT_FACTOR_PCT,
    DEFAULT_FORECAST_DAYS,
    DEFAULT_INTERVAL_DAYS,
    DEFAULT_MAX_CYCLE_MIN,
    DEFAULT_SOAK_MIN,
    DEFAULT_TARGET_MM,
    DEFAULT_TEST_MINUTES,
    DOMAIN,
    RAIN_LEDGER_CREDIT_HOURS,
    RAIN_LEDGER_TRIM_HOURS,
    RAIN_WINDOW_HOURS,
    VAL_AUTO_INTERVAL,
    VAL_ENABLED,
    VAL_FACTOR,
    VAL_INTERVAL,
    VAL_MAX_CYCLE,
    VAL_NOTIFY,
    VAL_RAIN_COMP,
    VAL_SOAK,
    VAL_START_TIME,
    VAL_TARGET_MM,
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

        # Cache în memorie (supraviețuiește reload-ului intrării, NU și restartului HA) —
        # ca media temperaturii/ploaia/ultima udare să nu apară „—" imediat după un reload
        # (ex. la salvarea unei zone), până se reface prima interogare.
        self._cache: dict = hass.data.setdefault(DOMAIN, {}).setdefault(
            f"cache_{entry.entry_id}", {}
        )

        # Valori reglabile live (factor / enable / oră / interval / compensare ploaie).
        self.values: dict[str, object] = {}
        self.avg_temp: float | None = self._cache.get("avg_temp")
        self.rain_mm: float = self._cache.get("rain_mm", 0.0)

        self.is_watering = False
        self._progress: dict | None = None  # starea live a udării în curs
        self._watering_task: asyncio.Task | None = None
        self._unsub_time: CALLBACK_TYPE | None = None

        # Data ultimei udări reale (persistată) — baza intervalului între udări.
        self.last_run: dt.date | None = self._cache.get("last_run")
        self._store: Store = Store(hass, 1, f"{DOMAIN}_{entry.entry_id}")

        # Registrul ploii căzute: {bucket_orar_iso: mm}. Alimentat orar din nowcast
        # (prognoza orei imediat următoare) sau, dacă e configurat, din delta unui
        # senzor cumulativ de ploaie. Golit la fiecare sesiune (udare/reset pe ploaie).
        self.rain_sensor: str | None = entry.data.get(CONF_RAIN_SENSOR) or None
        self._rain_ledger: dict[str, float] = self._cache.get("rain_ledger", {})
        self._rain_sensor_prev: float | None = self._cache.get("rain_sensor_prev")

        # Istoric sesiuni + statistici (persistate).
        self._history_store: Store = Store(hass, 1, f"{DOMAIN}_history_{entry.entry_id}")
        self._history: list[dict] = self._cache.get("history", [])
        self.total_liters: float = self._cache.get("total_liters", 0.0)
        self.skip_count: int = self._cache.get("skip_count", 0)
        self.last_duration: float = self._cache.get("last_duration", 0.0)
        self._skip_next: bool = self._cache.get("skip_next", False)

    async def async_load_history(self) -> None:
        data = await self._history_store.async_load() or {}
        self._history = data.get("records", [])
        self.total_liters = data.get("total_liters", 0.0)
        self.skip_count = data.get("skip_count", 0)
        self._skip_next = data.get("skip_next", False)
        self.last_duration = next(
            (r.get("minutes", 0.0) for r in reversed(self._history) if r.get("type") == "run"),
            0.0,
        )
        self._cache_history()

    def _cache_history(self) -> None:
        self._cache["history"] = self._history
        self._cache["total_liters"] = self.total_liters
        self._cache["skip_count"] = self.skip_count
        self._cache["last_duration"] = self.last_duration
        self._cache["skip_next"] = self._skip_next

    async def _save_history(self) -> None:
        self._cache_history()
        await self._history_store.async_save(
            {
                "records": self._history[-200:],
                "total_liters": self.total_liters,
                "skip_count": self.skip_count,
                "skip_next": self._skip_next,
            }
        )

    def _record(self, record: dict) -> None:
        """Adaugă o sesiune în istoric, actualizează statisticile și persistă."""
        record["ts"] = dt_util.now().isoformat()
        self._history.append(record)
        self._history = self._history[-200:]
        if record.get("type") == "run":
            self.total_liters += float(record.get("liters", 0.0))
            self.last_duration = float(record.get("minutes", 0.0))
        elif record.get("type") == "skip":
            self.skip_count += 1
        if self.hass is not None:
            self.hass.async_create_task(self._save_history())
            self.recompute()

    def history(self) -> dict:
        """Agregări pentru tab-ul Rapoarte (totaluri pe perioade + defalcare pe zonă)."""
        now = dt_util.now()
        runs = [r for r in self._history if r.get("type") == "run"]

        def _since(days: int) -> float:
            cutoff = now - dt.timedelta(days=days)
            total = 0.0
            for r in runs:
                ts = dt_util.parse_datetime(r.get("ts", ""))
                if ts and ts >= cutoff:
                    total += float(r.get("liters", 0.0))
            return round(total, 1)

        by_zone: dict[str, dict] = {}
        cutoff = now - dt.timedelta(days=30)
        for r in runs:
            ts = dt_util.parse_datetime(r.get("ts", ""))
            if not ts or ts < cutoff:
                continue
            for z in r.get("zones", []):
                d = by_zone.setdefault(z.get("name", "?"), {"liters": 0.0, "minutes": 0.0})
                d["liters"] += float(z.get("liters", 0.0))
                d["minutes"] += float(z.get("minutes", 0.0))
        return {
            "records": list(reversed(self._history[-50:])),
            "totals": {
                "today": _since(1),
                "week": _since(7),
                "month": _since(30),
                "count": len(runs),
                "skipped": self.skip_count,
            },
            "by_zone": [
                {"name": k, "liters": round(v["liters"], 1), "minutes": round(v["minutes"], 1)}
                for k, v in sorted(by_zone.items())
            ],
        }

    async def async_load_store(self) -> None:
        """Încarcă `last_run` + registrul de ploaie; la prima instalare ancorează la azi."""
        data = await self._store.async_load() or {}
        stored = data.get("last_run")
        if stored:
            try:
                self.last_run = dt.date.fromisoformat(stored)
            except ValueError:
                self.last_run = None
        self._rain_ledger = data.get("rain_ledger", self._rain_ledger)
        self._rain_sensor_prev = data.get("rain_sensor_prev", self._rain_sensor_prev)
        if self.last_run is None:
            self.last_run = dt_util.now().date()
            await self._save_last_run()
        self._cache["last_run"] = self.last_run
        self._cache["rain_ledger"] = self._rain_ledger

    async def _save_last_run(self) -> None:
        self._cache["last_run"] = self.last_run
        self._cache["rain_ledger"] = self._rain_ledger
        self._cache["rain_sensor_prev"] = self._rain_sensor_prev
        await self._store.async_save(
            {
                "last_run": self.last_run.isoformat() if self.last_run else None,
                "rain_ledger": self._rain_ledger,
                "rain_sensor_prev": self._rain_sensor_prev,
            }
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
            max_cycle, soak = self._cycle_settings(zone)
            for group in zone.get(CONF_GROUPS, []):
                ordered.append(
                    {
                        **group,
                        "zone_name": zone.get(CONF_NAME, ""),
                        "display_name": f"{zone.get(CONF_NAME, '')} · {group.get(CONF_NAME, '')}",
                        "_max_cycle": max_cycle,
                        "_soak": soak,
                    }
                )
        return ordered

    def _cycle_settings(self, zone: dict) -> tuple[float, float]:
        """(max_cycle, soak) pentru o zonă — override din zonă sau fallback la global."""
        g_max = self.get_float(VAL_MAX_CYCLE, DEFAULT_MAX_CYCLE_MIN)
        g_soak = self.get_float(VAL_SOAK, DEFAULT_SOAK_MIN)
        z_max = zone.get(CONF_MAX_CYCLE)
        z_soak = zone.get(CONF_SOAK)
        return (
            _num(z_max, g_max) if z_max not in (None, "") else g_max,
            _num(z_soak, g_soak) if z_soak not in (None, "") else g_soak,
        )

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
        if key in (VAL_START_TIME, VAL_ENABLED):
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

    def _rain_from_forecast(self, forecasts: list[dict]) -> float:
        """Ploaia prevăzută (mm, ponderată cu probabilitatea) pe următoarele ore."""
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

    # ---------------------------------------------------- registrul ploii căzute
    def fallen_mm(self) -> float:
        """Ploaia căzută (mm) în fereastra de credit — de la ultima sesiune încoace."""
        cutoff = dt_util.utcnow() - dt.timedelta(hours=RAIN_LEDGER_CREDIT_HOURS)
        total = 0.0
        for bucket, mm in self._rain_ledger.items():
            ts = dt_util.parse_datetime(bucket)
            if ts is not None and dt_util.as_utc(ts) >= cutoff:
                total += _num(mm, 0.0)
        return round(total, 1)

    async def _sample_rain(self, forecasts: list[dict]) -> None:
        """Eșantion orar în registru: nowcast (ora următoare) sau delta senzorului de ploaie.

        Bucket-ul e ora curentă trunchiată → idempotent la refresh-uri repetate/reload-uri.
        """
        now = dt_util.utcnow()
        bucket = now.replace(minute=0, second=0, microsecond=0).isoformat()

        if self.rain_sensor:
            state = self.hass.states.get(self.rain_sensor)
            try:
                value = float(state.state) if state else None
            except (TypeError, ValueError):
                value = None
            if value is not None:
                if self._rain_sensor_prev is not None:
                    delta = max(0.0, value - self._rain_sensor_prev)  # robust la resetări
                    if delta > 0:
                        self._rain_ledger[bucket] = self._rain_ledger.get(bucket, 0.0) + delta
                self._rain_sensor_prev = value
        elif forecasts:
            # Nowcast: precipitația prognozată pentru ora imediat următoare ≈ ce cade acum.
            first = forecasts[0]
            mm = _num(first.get("precipitation"), 0.0)
            if mm > 0:
                self._rain_ledger[bucket] = mm  # overwrite: idempotent în aceeași oră

        # Trim bucket-uri vechi.
        trim_cutoff = now - dt.timedelta(hours=RAIN_LEDGER_TRIM_HOURS)
        self._rain_ledger = {
            b: v
            for b, v in self._rain_ledger.items()
            if (ts := dt_util.parse_datetime(b)) is not None and dt_util.as_utc(ts) >= trim_cutoff
        }

        # Ploaie plină = sesiune: solul a primit ținta → resetăm ceasul intervalului.
        gross = self._gross_target()
        fallen = self.fallen_mm()
        if gross and gross > 0 and fallen >= gross:
            self.last_run = dt_util.now().date()
            self._rain_ledger = {}
            self._record({"type": "rain", "mm": fallen})
            self._notify(
                "ZoneFlow — ploaia a udat",
                f"Au căzut ~{fallen:.0f} mm — contează ca udare; următoarea în {self._interval()} zile.",
            )
            _LOGGER.info("Ploaie %.1f mm ≥ țintă %.1f — contează ca sesiune", fallen, gross)
        await self._save_last_run()

    async def _async_update_data(self) -> dict:
        self.avg_temp = await self._fetch_avg_temp()
        hourly = await self._get_forecast("hourly")
        self.rain_mm = self._rain_from_forecast(hourly)
        await self._sample_rain(hourly)
        # Salvăm în cache ca un reload ulterior să nu pornească cu valori goale.
        if self.avg_temp is not None:
            self._cache["avg_temp"] = self.avg_temp
        self._cache["rain_mm"] = self.rain_mm
        return self._build_data()

    # --------------------------------------------------------------- calcule
    def _zone_target(self, zone: dict) -> float:
        """Ținta efectivă a unei zone (L/m²) = global × factor_zonă − ploaie, ≥ 0."""
        gross = self._gross_target()
        if gross is None:
            return 0.0
        factor_pct = _num(zone.get(CONF_FACTOR_PCT), DEFAULT_FACTOR_PCT) / 100.0
        return max(0.0, gross * factor_pct - self._rain())

    def compute_runtimes(self) -> dict[str, float]:
        """Timpii de rulare [minute] per grup = țintă_zonă / rata grupului (metoda caserolei)."""
        runtimes: dict[str, float] = {}
        for zone in self.zones:
            zone_target = self._zone_target(zone)
            for group in zone.get(CONF_GROUPS, []):
                rate = _num(group.get(CONF_RATE), 0.0)
                runtimes[group.get(CONF_ID)] = calc.runtime_simple(
                    zone_target, rate, self.test_minutes
                )
        return runtimes

    def _gross_target(self) -> float | None:
        """Cantitatea fixă pe sesiune (L/m²), scalată de factorul global. Nu depinde de temp."""
        return self.get_float(VAL_TARGET_MM, DEFAULT_TARGET_MM) * self.get_float(VAL_FACTOR, 1.0)

    def _rain(self) -> float:
        """Ploaia luată în calcul: prognoza 24h + creditul căzut (0 dacă compensarea e oprită).

        Ferestrele sunt disjuncte în timp (viitor vs. trecut), deci nu se dublează; creditul
        se golește la fiecare sesiune, deci acoperă doar ploaia de după ultima udare.
        """
        if not self.get_bool(VAL_RAIN_COMP, True):
            return 0.0
        return self.rain_mm + self.fallen_mm()

    def _effective_target(self) -> float | None:
        """Ținta globală după ploaie (pentru afișare; per zonă se aplică și factorul zonei)."""
        return calc.effective_target(self._gross_target(), self._rain())

    def _session_liters(self) -> float:
        """Litri pe sesiune ≈ Σ pe zone (țintă_zonă × suprafața zonei)."""
        return sum(
            self._zone_target(zone) * _num(zone.get(CONF_AREA), DEFAULT_AREA)
            for zone in self.zones
        )

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
            "rain_fallen_mm": self.fallen_mm(),
            "will_skip": will_skip,
            "runtimes": runtimes,
            "liters": self._session_liters(),
            "next_run": self._next_run(),
            "last_run": self.last_run.isoformat() if self.last_run else None,
            "interval_days": self._interval(),
            "auto_interval": self.get_bool(VAL_AUTO_INTERVAL, True),
            "watering": {"active": self.is_watering, "current": self._progress},
            "skip_next": self._skip_next,
            "total_liters": round(self.total_liters, 1),
            "skip_count": self.skip_count,
            "last_duration": round(self.last_duration, 1),
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
        """Intervalul efectiv: AUTO din temperatură, sau manual dacă Auto e oprit."""
        if self.get_bool(VAL_AUTO_INTERVAL, True):
            return calc.interval_from_temp(self.avg_temp)
        return max(1, int(self.get_float(VAL_INTERVAL, DEFAULT_INTERVAL_DAYS)))

    @callback
    def _scheduled_fire(self, now: dt.datetime) -> None:
        if not self.get_bool(VAL_ENABLED, True):
            return
        if self.last_run is None:
            self.last_run = now.date()
        if (now.date() - self.last_run).days >= self._interval():
            if self._skip_next:
                # Sărim manual peste această sesiune și reamânăm cu un interval.
                self._skip_next = False
                self.last_run = now.date()
                self.hass.async_create_task(self._save_last_run())
                self._record({"type": "skip", "reason": "manual"})
                self._notify("ZoneFlow — udare sărită", "Ai sărit manual peste această udare.", kind="skip")
                self.recompute()
                return
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

    @callback
    def mark_due(self) -> None:
        """Face următoarea udare programată „scadentă" (ex. prima udare la noapte).

        Setează `last_run` cu un interval în urmă, astfel încât la următoarea oră programată
        condiția `(azi − last_run) >= interval` să fie îndeplinită → udă automat la ora setată.
        """
        self.last_run = dt_util.now().date() - dt.timedelta(days=self._interval())
        if self.hass is not None:
            self.hass.async_create_task(self._save_last_run())
            self.recompute()
        _LOGGER.info("Programare forțată: udare scadentă la următoarea oră (%s)", self.last_run)

    # -------------------------------------------------------------- progres / extra
    @callback
    def _set_progress(
        self, label: str, phase: str, seconds: float, cycle: int, cycles: int, upcoming: list[str]
    ) -> None:
        end = dt_util.now() + dt.timedelta(seconds=seconds)
        self._progress = {
            "label": label,
            "phase": phase,
            "ends_at": end.isoformat(),
            "cycle": cycle,
            "cycles": cycles,
            "upcoming": upcoming,
        }
        self.async_update_listeners()
        self.recompute()

    def _notify(self, title: str, message: str, kind: str = "info") -> None:
        """Notificare: clopoțelul din UI (mereu) + push prin serviciul notify configurat.

        `kind` separă notification_id-urile (start/finish/skip…), ca să nu se suprascrie.
        """
        if not self.get_bool(VAL_NOTIFY, True) or self.hass is None:
            return
        self.hass.async_create_task(
            self.hass.services.async_call(
                "persistent_notification",
                "create",
                {
                    "title": title,
                    "message": message,
                    "notification_id": f"{DOMAIN}_{self.entry.entry_id}_{kind}",
                },
                blocking=False,
            )
        )
        service = self.entry.data.get(CONF_NOTIFY_SERVICE)
        if service:
            self.hass.async_create_task(
                self.hass.services.async_call(
                    "notify", service, {"title": title, "message": message}, blocking=False
                )
            )

    @callback
    def postpone(self) -> None:
        """Amână următoarea udare cu o zi (ex. testul cu șurubelnița: solul e încă umed).

        Noua scadență = max(scadența curentă, azi) + 1 zi; apăsat de N ori → +N zile.
        """
        today = dt_util.now().date()
        if self.last_run is None:
            self.last_run = today
        due = max(self.last_run + dt.timedelta(days=self._interval()), today)
        new_due = due + dt.timedelta(days=1)
        self.last_run = new_due - dt.timedelta(days=self._interval())
        if self.hass is not None:
            self.hass.async_create_task(self._save_last_run())
            self.recompute()
        self._notify(
            "ZoneFlow — udare amânată",
            f"Udarea a fost amânată până pe {new_due.strftime('%d.%m')}.",
            kind="postpone",
        )
        _LOGGER.info("Udare amânată cu o zi → scadentă la %s", new_due)

    @callback
    def skip_next(self) -> None:
        """Comută „sări peste următoarea udare programată"."""
        self._skip_next = not self._skip_next
        if self.hass is not None:
            self.hass.async_create_task(self._save_history())
            self.recompute()

    @callback
    def test_zone(self, zone_id: str, minutes: float) -> None:
        if self.is_watering:
            _LOGGER.warning("Udare în curs; ignor testul de zonă")
            return
        self._watering_task = self.hass.async_create_task(self._run_test(zone_id, minutes))

    def _record_run(self, runtimes: dict[str, float]) -> None:
        zones_rec: list[dict] = []
        total_min = 0.0
        for zone in self.zones:
            zmin = sum(
                runtimes.get(g.get(CONF_ID), 0.0) for g in zone.get(CONF_GROUPS, [])
            )
            if zmin <= 0:
                continue
            zliters = self._zone_target(zone) * _num(zone.get(CONF_AREA), DEFAULT_AREA)
            zones_rec.append(
                {"name": zone.get(CONF_NAME, ""), "liters": round(zliters, 1), "minutes": round(zmin, 1)}
            )
            total_min += zmin
        self._record(
            {
                "type": "run",
                "liters": round(self._session_liters(), 1),
                "minutes": round(total_min, 1),
                "zones": zones_rec,
            }
        )

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
        groups = [
            g
            for g in self.groups_in_order()
            if runtimes.get(g.get(CONF_ID), 0.0) > 0
            and [s for s in g.get(CONF_SWITCHES, []) if s]
        ]
        if not groups:
            _LOGGER.info("Sar peste udare: nimic de udat (ploaie ≥ țintă sau țintă 0)")
            self._record({"type": "skip", "reason": "ploaie", "rain": round(self._rain(), 1)})
            self._notify("ZoneFlow — udare sărită", f"Plouă destul ({self._rain():.0f} mm) — sesiune sărită.", kind="skip")
            return
        self.is_watering = True
        watered = False
        self.async_update_listeners()
        self._notify("ZoneFlow — start udare", "A început udarea.", kind="start")
        try:
            for idx, group in enumerate(groups):
                minutes = runtimes.get(group.get(CONF_ID), 0.0)
                switches = [s for s in group.get(CONF_SWITCHES, []) if s]
                upcoming = [g.get("display_name", "") for g in groups[idx + 1 :]]
                await self._run_group(
                    switches, minutes, group.get("_max_cycle"), group.get("_soak"),
                    label=group.get("display_name", ""), upcoming=upcoming,
                )
                watered = True
        except asyncio.CancelledError:
            _LOGGER.info("Ciclu de udare anulat")
            raise
        finally:
            await self.async_all_off()
            self.is_watering = False
            self._progress = None
            self._watering_task = None
            if watered:
                self.last_run = dt_util.now().date()
                # Creditul de ploaie a fost aplicat acestei sesiuni → îl golim.
                self._rain_ledger = {}
                self.hass.async_create_task(self._save_last_run())
                liters = self._session_liters()
                self._record_run(runtimes)
                self._notify("ZoneFlow — udare terminată", f"Gata. ~{liters:.0f} L livrați.", kind="finish")
            self.async_update_listeners()
            self.recompute()

    async def _run_test(self, zone_id: str, minutes: float) -> None:
        zone = next((z for z in self.zones if z.get(CONF_ID) == zone_id), None)
        groups = [
            g for g in (zone or {}).get(CONF_GROUPS, []) if [s for s in g.get(CONF_SWITCHES, []) if s]
        ]
        if not zone or not groups or minutes <= 0:
            return
        self.is_watering = True
        self.async_update_listeners()
        self._notify("ZoneFlow — test zonă", f"Test {zone.get(CONF_NAME)} · {minutes:.0f} min.", kind="test")
        try:
            for idx, group in enumerate(groups):
                switches = [s for s in group.get(CONF_SWITCHES, []) if s]
                upcoming = [f"{zone.get(CONF_NAME)} · {g.get(CONF_NAME)}" for g in groups[idx + 1 :]]
                label = f"TEST · {zone.get(CONF_NAME)} · {group.get(CONF_NAME)}"
                await self._run_group(switches, minutes, 0, 0, label=label, upcoming=upcoming)
        except asyncio.CancelledError:
            raise
        finally:
            await self.async_all_off()
            self.is_watering = False
            self._progress = None
            self._watering_task = None
            self.async_update_listeners()
            self.recompute()

    async def _run_group(
        self,
        switches: list[str],
        minutes: float,
        max_cycle: float | None = None,
        soak: float | None = None,
        label: str = "",
        upcoming: list[str] | None = None,
    ) -> None:
        """Rulează grupul (toate supapele simultan), eventual în reprize (cycle & soak)."""
        if max_cycle is None:
            max_cycle = self.get_float(VAL_MAX_CYCLE, DEFAULT_MAX_CYCLE_MIN)
        if soak is None:
            soak = self.get_float(VAL_SOAK, DEFAULT_SOAK_MIN)
        cycles = calc.split_cycles(minutes, max_cycle)
        n = len(cycles)
        for idx, cycle_min in enumerate(cycles):
            self._set_progress(label, "udare", cycle_min * 60, idx + 1, n, upcoming or [])
            await self._run_once(switches, cycle_min)
            if idx < n - 1 and soak > 0:
                _LOGGER.info("Pauză de infiltrare %.0f min", soak)
                self._set_progress(label, "soak", soak * 60, idx + 1, n, upcoming or [])
                await asyncio.sleep(soak * 60)

    async def _run_once(self, switches: list[str], minutes: float) -> None:
        """O singură repriză: pornește supapele simultan, așteaptă, le oprește."""
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
