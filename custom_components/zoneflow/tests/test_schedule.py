"""Integritatea programării: separarea last_run (udare reală) de next_due (override absolut).

Verifică bug-urile care au corupt programarea userului (2026-07-07): postpone/mark_due
suprascriau last_run cu o dată sintetică, cu derapaj de temperatură; și regresia pentru
bug-ul de import (CONF_NOTIFY_SERVICE) care făcea _notify să arunce NameError.
"""

import asyncio
import datetime as dt
import os
import sys
from types import SimpleNamespace

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "..", ".."))

from custom_components.zoneflow.coordinator import ZoneFlowCoordinator  # noqa: E402
from custom_components.zoneflow.const import (  # noqa: E402
    CONF_NOTIFY_SERVICE,
    VAL_AUTO_INTERVAL,
    VAL_ENABLED,
    VAL_INTERVAL,
    VAL_NOTIFY,
    VAL_START_TIME,
)
from homeassistant.util import dt as dt_util  # noqa: E402


def _swallow(coro):
    """Închide o corutină programată sincron (fără event loop) fără s-o ruleze."""
    try:
        coro.close()
    except Exception:  # noqa: BLE001
        pass
    return None


def make_sched(last_run=None, next_due=None, avg_temp=20.0, auto=True, interval=3, enabled=True):
    """Coordinator minimal pentru logica SINCRONĂ de programare (fără HA real)."""
    c = object.__new__(ZoneFlowCoordinator)
    c.avg_temp = avg_temp
    c.values = {
        VAL_ENABLED: enabled,
        VAL_AUTO_INTERVAL: auto,
        VAL_INTERVAL: interval,
        VAL_START_TIME: dt.time(3, 0),
        VAL_NOTIFY: False,
    }
    c.last_run = last_run
    c.next_due = next_due
    c._skip_next = False
    c.records = []
    c.fired = []
    c.hass = SimpleNamespace(async_create_task=_swallow)
    c._notify = lambda *a, **k: None
    c._record = lambda rec: c.records.append(rec)
    c.recompute = lambda: None
    c.start_watering = lambda: c.fired.append(True)

    async def _noop():
        return None

    c._save_last_run = _noop
    return c


# --------------------------------------------------------- temperatură / derapaj

def test_postpone_is_temperature_invariant():
    today = dt_util.now().date()
    c = make_sched(last_run=today - dt.timedelta(days=1), avg_temp=26.0)  # interval 3
    before = c._effective_due()
    c.postpone()
    nd = c.next_due
    assert nd == max(before, today) + dt.timedelta(days=1)
    assert c.last_run == today - dt.timedelta(days=1)  # NEatins (era bug-ul principal)
    # temperatura scade → interval devine 7, dar override-ul e absolut → nu derapează
    c.avg_temp = 20.0
    assert c._effective_due() == nd
    assert c.next_due == nd
    assert any(r.get("type") == "postpone" for r in c.records)


def test_display_and_fire_never_diverge():
    today = dt_util.now().date()
    fixed = today + dt.timedelta(days=5)
    c = make_sched(last_run=today, next_due=fixed, avg_temp=26.0)
    assert c._next_run().date() == fixed
    c.avg_temp = 5.0  # interval 14 acum — nu trebuie să miște nimic
    assert c._next_run().date() == fixed
    assert c._effective_due() == fixed


def test_postpone_stacks_exactly_one_day_each():
    today = dt_util.now().date()
    c = make_sched(last_run=today, next_due=None, avg_temp=20.0)  # interval 7
    base = c._effective_due()
    c.postpone(); a = c.next_due
    c.avg_temp = 30.0  # interval 3
    c.postpone(); b = c.next_due
    c.avg_temp = 5.0   # interval 14
    c.postpone(); z = c.next_due
    assert a == max(base, today) + dt.timedelta(days=1)
    assert b == a + dt.timedelta(days=1)
    assert z == b + dt.timedelta(days=1)
    assert z == base + dt.timedelta(days=3)  # exact +3, în ciuda schimbărilor de temperatură


# --------------------------------------------------------- last_run rămâne real

def test_mark_due_keeps_last_run_real():
    today = dt_util.now().date()
    real = today - dt.timedelta(days=10)
    c = make_sched(last_run=real, avg_temp=20.0)
    c.mark_due()
    assert c.next_due == today
    assert c.last_run == real  # „Ultima udare" NU mai minte
    assert any(r.get("type") == "mark_due" for r in c.records)


# --------------------------------------------------------- combinații de stări

def test_skip_fire_then_postpone():
    today = dt_util.now().date()
    c = make_sched(last_run=today - dt.timedelta(days=10), avg_temp=26.0)  # interval 3, restant
    c._skip_next = True
    now = dt_util.now()
    c._scheduled_fire(now)
    assert c.next_due == now.date() + dt.timedelta(days=3)  # skip amână un interval, absolut
    assert c._skip_next is False
    assert c.last_run == today - dt.timedelta(days=10)  # NEatins
    assert not c.fired
    c.postpone()
    assert c.next_due == now.date() + dt.timedelta(days=4)  # +1 peste skip


def test_mark_due_then_postpone():
    today = dt_util.now().date()
    c = make_sched(last_run=today - dt.timedelta(days=1), avg_temp=20.0)
    c.mark_due()
    c.postpone()
    assert c.next_due == today + dt.timedelta(days=1)


def test_future_next_due_blocks_early_fire():
    """Cheia anti-pierdere: last_run foarte vechi, dar override viitor → NU udă devreme."""
    today = dt_util.now().date()
    c = make_sched(last_run=today - dt.timedelta(days=30), next_due=today + dt.timedelta(days=2), avg_temp=26.0)
    c._scheduled_fire(dt_util.now())
    assert not c.fired


def test_fires_when_due_via_override():
    today = dt_util.now().date()
    c = make_sched(last_run=today - dt.timedelta(days=30), next_due=today, avg_temp=26.0)
    c._scheduled_fire(dt_util.now())
    assert c.fired


# --------------------------------------------------------- persistență / migrare

class FakeStore:
    def __init__(self, saved=None):
        self.saved = saved

    async def async_load(self):
        return self.saved

    async def async_save(self, data):
        self.saved = data


def make_store_coord(saved=None):
    c = object.__new__(ZoneFlowCoordinator)
    c._store = FakeStore(saved)
    c._cache = {}
    c.last_run = None
    c.next_due = None
    c._rain_ledger = {}
    c._rain_sensor_prev = None
    return c


def test_next_due_store_roundtrip():
    async def main():
        today = dt_util.now().date()
        c = make_store_coord()
        c.last_run = today
        c.next_due = today + dt.timedelta(days=3)
        await c._save_last_run()
        assert c._store.saved["next_due"] == (today + dt.timedelta(days=3)).isoformat()
        c2 = make_store_coord(saved=c._store.saved)
        await c2.async_load_store()
        assert c2.next_due == today + dt.timedelta(days=3)
        assert c2.last_run == today
        # cache-ul ține OBIECTE date, nu string-uri (altfel _effective_due crapă la reload)
        assert isinstance(c2._cache["next_due"], dt.date)

    asyncio.run(main())


def test_first_install_does_not_anchor_next_due():
    async def main():
        c = make_store_coord(saved=None)
        await c.async_load_store()
        assert c.last_run == dt_util.now().date()  # ancorat
        assert c.next_due is None  # NU ancorat

    asyncio.run(main())


def test_absent_next_due_key_self_heals():
    async def main():
        c = make_store_coord(saved={"last_run": dt_util.now().date().isoformat()})
        await c.async_load_store()
        assert c.next_due is None  # upgrade de la v0.11 → cheia lipsește → None

    asyncio.run(main())


def test_corrupt_next_due_self_heals():
    async def main():
        c = make_store_coord(saved={"last_run": dt_util.now().date().isoformat(), "next_due": "nu-e-data"})
        await c.async_load_store()
        assert c.next_due is None  # dată invalidă → None, fără crash

    asyncio.run(main())


# --------------------------------------------------------- REGRESIE: _notify nu mai crapă

def test_notify_does_not_crash_with_service_configured():
    """Regresia incidentului: CONF_NOTIFY_SERVICE lipsea din import → NameError la FIECARE
    _notify → udarea bloca. Acum trebuie să meargă și să trimită push-ul."""

    async def main():
        calls = []

        class Svc:
            async def async_call(self, domain, service, data, blocking=False, **k):
                calls.append((domain, service))

        class Hass:
            def __init__(self):
                self.services = Svc()

            def async_create_task(self, coro):
                return asyncio.get_running_loop().create_task(coro)

        c = object.__new__(ZoneFlowCoordinator)
        c.hass = Hass()
        c.entry = SimpleNamespace(entry_id="e", data={CONF_NOTIFY_SERVICE: "mobile_app_test"})
        c.values = {VAL_NOTIFY: True}
        c._notify("Titlu", "Mesaj", kind="start")  # NU trebuie să arunce
        await asyncio.sleep(0.02)
        assert ("persistent_notification", "create") in calls  # clopoțel
        assert ("notify", "mobile_app_test") in calls  # push real pe telefon

    asyncio.run(main())
