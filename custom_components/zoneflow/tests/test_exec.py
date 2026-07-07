"""Teste de fiabilitate pentru execuția udării (incidentul din 2026-07-07).

Simulează cu un `hass` fals defectele reale: integrare de supape blocată (hang),
serviciu care aruncă, supapă care nu pornește, watchdog, oprire manuală.
Invariantul central: `is_watering` NU rămâne niciodată blocat pe True.
"""

import asyncio
import datetime as dt
import os
import sys
import time
from types import SimpleNamespace

# Rulabil din rădăcina repo-ului fără instalare.
sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "..", ".."))

from custom_components.zoneflow.coordinator import ZoneFlowCoordinator  # noqa: E402
from custom_components.zoneflow.const import (  # noqa: E402
    CONF_NOTIFY_SERVICE,
    VAL_FACTOR,
    VAL_MAX_CYCLE,
    VAL_NOTIFY,
    VAL_RAIN_COMP,
    VAL_SOAK,
    VAL_TARGET_MM,
)
from homeassistant.util import dt as dt_util  # noqa: E402


class FakeState:
    def __init__(self, state):
        self.state = state


class FakeStates:
    def __init__(self):
        self._data = {}

    def get(self, entity_id):
        return self._data.get(entity_id)

    def set(self, entity_id, state):
        self._data[entity_id] = FakeState(state)


class FakeServices:
    """Comportament programabil per (domain, service): ok / ok_no_state / hang / raise."""

    def __init__(self, states, modes):
        self.states = states
        self.modes = modes
        self.calls = []

    async def async_call(self, domain, service, data, blocking=False, **kwargs):
        ids = data.get("entity_id", [])
        if isinstance(ids, str):
            ids = [ids]
        self.calls.append((domain, service, tuple(ids)))
        mode = self.modes.get((domain, service), "ok")
        if mode == "hang":
            await asyncio.Event().wait()  # nu se termină niciodată
        if mode == "raise":
            raise RuntimeError("integrarea supapei a murit")
        if domain == "switch" and mode == "ok":
            for eid in ids:
                self.states.set(eid, "on" if service == "turn_on" else "off")
        # ok_no_state: apelul reușește dar starea NU se schimbă (device offline)


class FakeHass:
    def __init__(self, modes=None):
        self.states = FakeStates()
        self.services = FakeServices(self.states, modes or {})

    def async_create_task(self, coro):
        return asyncio.get_running_loop().create_task(coro)


def make_coordinator(hass, runtime_min=0.005):
    """Coordinator minimal, fără __init__-ul HA; țintă mică => durate de sub o secundă."""
    c = object.__new__(ZoneFlowCoordinator)
    c.hass = hass
    c.entry = SimpleNamespace(
        data={},
        entry_id="test",
        options={
            "zones": [
                {
                    "id": "z1",
                    "name": "Zona",
                    "area": 10,
                    "factor_pct": 100,
                    "groups": [
                        {"id": "g1", "name": "G1", "switches": ["switch.a"], "rate": 10},
                        {"id": "g2", "name": "G2", "switches": ["switch.b"], "rate": 10},
                    ],
                }
            ]
        },
    )
    c.test_minutes = 10.0
    # PR = 10/10 = 1 mm/min => runtime = target (minute). Țintă mică => teste rapide.
    c.values = {
        VAL_TARGET_MM: runtime_min,
        VAL_FACTOR: 1.0,
        VAL_RAIN_COMP: False,
        VAL_NOTIFY: False,
        VAL_MAX_CYCLE: 0,
        VAL_SOAK: 0,
    }
    c.avg_temp = 20.0
    c.rain_mm = 0.0
    c._rain_ledger = {}
    c.is_watering = False
    c._progress = None
    c._watering_task = None
    c.last_run = None
    c.next_due = None
    c._history = []
    c.total_liters = 0.0
    c.skip_count = 0
    c.last_duration = 0.0
    c._skip_next = False
    # Timeouts scurte pentru teste.
    c._svc_timeout = 0.1
    c._verify_delays = (0.02,)
    c._watchdog_extra_min = 15.0
    # Stub-uri pentru infrastructura HA (capturăm efectele).
    c.notifications = []
    c.records = []
    c._notify = lambda title, msg, kind="info": c.notifications.append((kind, title, msg))
    c._record = lambda rec: c.records.append(rec)
    c.async_update_listeners = lambda: None
    c.recompute = lambda: None

    async def _noop_save():
        return None

    c._save_last_run = _noop_save
    return c


def test_switch_call_hang_returns_false_quickly():
    async def main():
        hass = FakeHass({("switch", "turn_on"): "hang"})
        c = make_coordinator(hass)
        start = time.monotonic()
        ok = await c._switch_call("turn_on", ["switch.a"])
        elapsed = time.monotonic() - start
        assert ok is False
        assert elapsed < 1.0  # timeout 0.1s, nu infinit

    asyncio.run(main())


def test_turn_on_hang_does_not_stick_status():
    """Scenariul incidentului: turn_on blocat => sesiunea se încheie cu eroare, status curat."""

    async def main():
        hass = FakeHass({("switch", "turn_on"): "hang"})
        c = make_coordinator(hass)
        await c._run_cycle()
        assert c.is_watering is False          # statusul NU rămâne blocat
        assert c._progress is None
        assert c.last_run is None              # nu s-a udat => reîncearcă mâine
        assert any(r.get("type") == "error" for r in c.records)
        assert any(k == "error" for k, _, _ in c.notifications)  # alertă trimisă

    asyncio.run(main())


def test_turn_on_raise_does_not_stick_status():
    async def main():
        hass = FakeHass({("switch", "turn_on"): "raise"})
        c = make_coordinator(hass)
        await c._run_cycle()
        assert c.is_watering is False
        assert any(r.get("type") == "error" for r in c.records)
        # supapele au fost totuși comandate off la final (all_off)
        assert ("switch", "turn_off", ("switch.a", "switch.b")) in hass.services.calls

    asyncio.run(main())


def test_valve_stays_off_fails_fast():
    """turn_on 'reușește' dar starea rămâne off => grup eșuat FĂRĂ să dormim durata întreagă."""

    async def main():
        hass = FakeHass({("switch", "turn_on"): "ok_no_state"})
        c = make_coordinator(hass, runtime_min=10.0)  # 10 minute — nu trebuie să le aștepte
        start = time.monotonic()
        await c._run_cycle()
        elapsed = time.monotonic() - start
        assert elapsed < 3.0                    # a eșuat rapid, nu a "udat" 10 min în gol
        assert c.is_watering is False
        assert c.last_run is None
        assert any(r.get("type") == "error" for r in c.records)

    asyncio.run(main())


def test_partial_failure_continues_and_waters():
    """G1 eșuează (nu pornește), G2 merge => sesiune reușită parțial, failed raportat."""

    async def main():
        hass = FakeHass()
        c = make_coordinator(hass)

        real_call = hass.services.async_call

        async def selective(domain, service, data, blocking=False, **kw):
            ids = data.get("entity_id", [])
            ids = [ids] if isinstance(ids, str) else ids
            if domain == "switch" and service == "turn_on" and "switch.a" in ids:
                hass.services.calls.append((domain, service, tuple(ids)))
                return  # "reușește" dar nu schimbă starea -> verificarea pică
            await real_call(domain, service, data, blocking=blocking, **kw)

        hass.services.async_call = selective
        await c._run_cycle()
        assert c.is_watering is False
        assert c.last_run is not None           # G2 a udat => sesiune contorizată
        runs = [r for r in c.records if r.get("type") == "run"]
        assert runs and runs[0].get("failed") and "G1" in runs[0]["failed"][0]

    asyncio.run(main())


def test_watchdog_terminates_runaway_session():
    async def main():
        hass = FakeHass()
        c = make_coordinator(hass, runtime_min=10.0)  # ar dura 10+10 minute
        c._watchdog_extra_min = 0.002                 # buget total ~minuscul...
        # bugetul include runtime-ul estimat; forțăm bugetul mic suprascriind metoda
        c._session_budget_min = lambda runtimes, groups: 0.01  # ~0.6s
        start = time.monotonic()
        await c._run_cycle()
        elapsed = time.monotonic() - start
        assert elapsed < 5.0
        assert c.is_watering is False
        assert any("watchdog" in " ".join(map(str, r.values())) for r in c.records)

    asyncio.run(main())


def test_stop_clears_status_even_if_valves_hang():
    async def main():
        # turn_off blocat: nici oprirea nu răspunde — statusul tot trebuie curățat IMEDIAT.
        hass = FakeHass({("switch", "turn_off"): "hang"})
        c = make_coordinator(hass, runtime_min=0.05)  # 3s de udare
        c._retry_sleep = 0.02
        task = asyncio.get_running_loop().create_task(c._run_cycle())
        c._watering_task = task
        await asyncio.sleep(0.2)                      # a pornit (turn_on ok)
        assert c.is_watering is True
        stop_task = asyncio.get_running_loop().create_task(c.async_stop_watering())
        await asyncio.sleep(0.05)
        assert c.is_watering is False                 # reset defensiv, fără să aștepte supapele
        await asyncio.wait_for(stop_task, timeout=5.0)  # retries cu timeout, apoi alertă
        assert any(k == "error" for k, _, _ in c.notifications)  # „verifică manual supapa"
        task.cancel()
        try:
            await task
        except (asyncio.CancelledError, Exception):
            pass

    asyncio.run(main())


def test_happy_path_waters_and_records():
    async def main():
        hass = FakeHass()
        c = make_coordinator(hass)
        await c._run_cycle()
        assert c.is_watering is False
        assert c.last_run is not None
        runs = [r for r in c.records if r.get("type") == "run"]
        assert runs and not runs[0].get("failed")
        # ambele grupuri au fost pornite și oprite
        on_calls = [x for x in hass.services.calls if x[1] == "turn_on"]
        assert len(on_calls) == 2

    asyncio.run(main())


def test_watering_succeeds_with_notifications_enabled():
    """REGRESIE incident 2026-07-07: cu notificările ON + serviciu de push configurat,
    _notify arunca NameError (CONF_NOTIFY_SERVICE neimportat) → _run_cycle crăpa înainte de
    orice supapă → status blocat, zero apă. Acum trebuie să ude ȘI să trimită push-ul."""

    async def main():
        hass = FakeHass()
        c = make_coordinator(hass)
        c.values[VAL_NOTIFY] = True
        c.entry.data = {CONF_NOTIFY_SERVICE: "mobile_app_test"}
        # folosește _notify REAL (nu stubul) — reproduce exact scenariul incidentului
        c._notify = ZoneFlowCoordinator._notify.__get__(c, ZoneFlowCoordinator)
        await c._run_cycle()
        await asyncio.sleep(0.05)
        assert c.is_watering is False
        assert c.last_run is not None  # A UDAT (înainte de fix: NameError → nu uda deloc)
        on_calls = [x for x in hass.services.calls if x[1] == "turn_on"]
        assert len(on_calls) == 2
        # ambele canale de notificare au fost folosite (FakeServices ține (domain, service, ids))
        assert any(x[0] == "persistent_notification" and x[1] == "create" for x in hass.services.calls)
        assert any(x[0] == "notify" and x[1] == "mobile_app_test" for x in hass.services.calls)

    asyncio.run(main())


def test_successful_watering_clears_override():
    async def main():
        hass = FakeHass()
        c = make_coordinator(hass)
        c.next_due = dt_util.now().date()  # override activ (ex. de la mark_due/postpone)
        await c._run_cycle()
        assert c.last_run is not None
        assert c.next_due is None  # udare reușită → override consumat

    asyncio.run(main())


def test_failed_watering_keeps_override_for_retry():
    async def main():
        hass = FakeHass({("switch", "turn_on"): "hang"})
        c = make_coordinator(hass)
        keep = dt_util.now().date() + dt.timedelta(days=1)
        c.next_due = keep
        await c._run_cycle()
        assert c.is_watering is False
        assert c.next_due == keep  # eșec → override NEconsumat → reîncearcă
        assert c.last_run is None

    asyncio.run(main())
