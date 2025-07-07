import sys
import types
import importlib
import pytest
from unittest.mock import AsyncMock
from datetime import datetime, timedelta
from deddie_metering.const import (
    DEFAULT_PV_THRESHOLD,
    ATTR_CONSUMPTION,
    ATTR_PRODUCTION,
    ATTR_INJECTION,
)

fake_update_coordinator = types.ModuleType("homeassistant.helpers.update_coordinator")


class FakeDataUpdateCoordinator:
    def __init__(self, hass, logger, name, update_interval):
        self.hass = hass
        self.logger = logger
        self.name = name
        self.update_interval = update_interval


setattr(
    fake_update_coordinator,
    "DataUpdateCoordinator",
    FakeDataUpdateCoordinator,  # type: ignore[attr-defined]
)
fake_update_coordinator.UpdateFailed = Exception  # type: ignore[attr-defined]
sys.modules["homeassistant.helpers.update_coordinator"] = fake_update_coordinator
sys.modules.pop("deddie_metering.coordinator", None)

coordinator_module = importlib.import_module("deddie_metering.coordinator")
DeddieDataUpdateCoordinator = coordinator_module.DeddieDataUpdateCoordinator
UpdateFailed = coordinator_module.UpdateFailed


@pytest.fixture(autouse=True)
def fixed_now(monkeypatch):
    fixed = datetime(2025, 1, 1, 12, 0, 0)
    monkeypatch.setattr(coordinator_module.dt_util, "now", lambda: fixed)
    return fixed


@pytest.fixture(autouse=True)
def stub_detect_pv(monkeypatch):
    monkeypatch.setattr(
        "deddie_metering.coordinator.detect_pv",
        AsyncMock(return_value=False),
        raising=True,
    )


@pytest.mark.asyncio
async def test_migrated_first_update(hass):
    token, supply, tax = "token", "123456789", "987654321"
    coord = DeddieDataUpdateCoordinator(
        hass,
        token,
        supply,
        tax,
        timedelta(hours=1),
        choose_step_flag="A1",
        has_pv=False,
        entry="entry_id1",
    )
    result = await coord._async_update_data()
    key = coordinator_module.ATTR_PRODUCTION
    assert result[key] == 0.0
    assert result[f"latest_date_{key}"] is None
    assert result[f"last_fetch_{key}"] == coordinator_module.dt_util.now().isoformat()
    assert hass.loop.call_later.call_count == 1
    assert hass.loop.call_later.call_args[0][0] == 1


@pytest.mark.asyncio
async def test_update_failed(hass):
    token, supply, tax = "token", "123456789", "987654321"
    coord = DeddieDataUpdateCoordinator(
        hass,
        token,
        supply,
        tax,
        timedelta(hours=1),
        choose_step_flag="B1",
        has_pv=False,
        entry="entry_id1",
    )
    assert hass.loop.call_later.call_count == 0
    with pytest.raises(UpdateFailed):
        await coord._async_update_data()


@pytest.mark.asyncio
async def test_skip_initial_refresh_true_missing_persistence(monkeypatch, hass):
    """
    skip_initial_refresh=True but no persisted data returns 0 and None.
    """
    monkeypatch.setattr(
        coordinator_module, "load_last_total", AsyncMock(return_value=None)
    )
    monkeypatch.setattr(
        coordinator_module, "load_last_update", AsyncMock(return_value=None)
    )
    coord = DeddieDataUpdateCoordinator(
        hass,
        "tok",
        "sup",
        "tax",
        timedelta(hours=1),
        choose_step_flag="A2",
        has_pv=False,
        entry="entry_id1",
    )
    # first update
    await coord._async_update_data()
    # second update via initial_jump branch
    result = await coord._async_update_data()
    key = coordinator_module.ATTR_CONSUMPTION
    assert result[key] == 0.0
    assert result[f"latest_date_{key}"] is None


@pytest.mark.asyncio
async def test_periodic_after_initial_jump(monkeypatch, hass, fixed_now):
    """
    Σενάριο: periodic update αμέσως μετά από initial flags.
    """
    # Προετοιμασία persistence helpers
    last = fixed_now - timedelta(days=1)
    monkeypatch.setattr(
        coordinator_module, "load_last_update", AsyncMock(return_value=last)
    )
    monkeypatch.setattr(
        coordinator_module, "load_last_total", AsyncMock(return_value=2.0)
    )

    # Mocks για fetch_since / batch_fetch
    fetch = AsyncMock()
    batch = AsyncMock()
    monkeypatch.setattr(coordinator_module, "fetch_since", fetch)
    monkeypatch.setattr(coordinator_module, "batch_fetch", batch)

    # Coordinator με flags ώστε να μπει απευθείας στο periodic
    coord = DeddieDataUpdateCoordinator(
        hass,
        token="tok",
        supply="sup",
        tax="tax",
        update_interval=timedelta(hours=1),
        choose_step_flag="D",
        has_pv=False,
        entry="entry_id1",
    )
    result = await coord._async_update_data()
    fetch.assert_awaited_once()
    batch.assert_not_called()
    key = coordinator_module.ATTR_CONSUMPTION
    assert result[key] == 2.0


@pytest.mark.asyncio
async def test_fresh_not_first_with_pv(hass, monkeypatch):
    """
    Fresh-not-first (skip_initial_refresh=False) & has_pv=True:
    διαβάζει persisted και schedule_refresh κληθεί.
    """
    coord = DeddieDataUpdateCoordinator(
        hass,
        token="tok",
        supply="sup",
        tax="tax",
        update_interval=timedelta(hours=1),
        choose_step_flag="C",
        has_pv=True,
        entry="entry_id1",
    )
    last_u = [datetime(2025, 1, 1), datetime(2025, 1, 2), datetime(2025, 1, 3)]
    totals = [10.0, 20.0, 30.0]
    monkeypatch.setattr(
        coordinator_module, "load_last_update", AsyncMock(side_effect=last_u)
    )
    monkeypatch.setattr(
        coordinator_module, "load_last_total", AsyncMock(side_effect=totals)
    )

    data = await coord._async_update_data()
    assert data[ATTR_CONSUMPTION] == totals[0]
    assert data[f"latest_date_{ATTR_CONSUMPTION}"] == last_u[0].date().isoformat()
    assert data[ATTR_PRODUCTION] == totals[1]
    assert data[ATTR_INJECTION] == totals[2]
    # schedule_refresh κλήθηκε τουλάχιστον μια φορά
    assert hass.loop.call_later.call_count >= 1


@pytest.mark.asyncio
async def test_periodic_has_pv_small_gap(hass, monkeypatch):
    """
    Periodic με gap <=365 ημέρες & has_pv=True: κληθεί fetch_since, όχι batch_fetch.
    """
    coord = DeddieDataUpdateCoordinator(
        hass,
        token="tok",
        supply="sup",
        tax="tax",
        update_interval=timedelta(hours=1),
        choose_step_flag="D",
        has_pv=True,
        entry="entry_id1",
    )
    coord._first_update_done = True
    last = coordinator_module.dt_util.now() - timedelta(days=1)
    loader = AsyncMock(side_effect=[last] * 6)
    monkeypatch.setattr(coordinator_module, "load_last_update", loader)
    monkeypatch.setattr(
        coordinator_module, "load_last_total", AsyncMock(side_effect=[5.5, 6.6, 7.7])
    )
    fetch = AsyncMock()
    batch = AsyncMock()
    monkeypatch.setattr(coordinator_module, "fetch_since", fetch)
    monkeypatch.setattr(coordinator_module, "batch_fetch", batch)

    data = await coord._async_update_data()
    assert fetch.await_count == 3
    assert batch.await_count == 0
    # Επιστρέφει τις τελευταίες τιμές
    assert data[ATTR_CONSUMPTION] == 5.5
    assert data[ATTR_PRODUCTION] == 6.6
    assert data[ATTR_INJECTION] == 7.7


@pytest.mark.asyncio
async def test_periodic_has_pv_big_gap(hass, monkeypatch):
    """
    Periodic με gap >365 ημέρες & has_pv=True: κληθεί batch_fetch, όχι fetch_since.
    """
    coord = DeddieDataUpdateCoordinator(
        hass,
        token="tok",
        supply="sup",
        tax="tax",
        update_interval=timedelta(hours=1),
        choose_step_flag="D",
        has_pv=True,
        entry="entry_id1",
    )
    coord._first_update_done = True
    last = coordinator_module.dt_util.now() - timedelta(days=370)
    loader = AsyncMock(side_effect=[last] * 6)
    monkeypatch.setattr(coordinator_module, "load_last_update", loader)
    monkeypatch.setattr(
        coordinator_module, "load_last_total", AsyncMock(side_effect=[5.5, 6.6, 7.7])
    )
    fetch = AsyncMock()
    batch = AsyncMock()
    monkeypatch.setattr(coordinator_module, "fetch_since", fetch)
    monkeypatch.setattr(coordinator_module, "batch_fetch", batch)

    data = await coord._async_update_data()
    assert batch.await_count == 3
    assert fetch.await_count == 0
    assert data[ATTR_CONSUMPTION] == 5.5
    assert data[ATTR_PRODUCTION] == 6.6
    assert data[ATTR_INJECTION] == 7.7


@pytest.mark.asyncio
async def test_pv_threshold_notification(hass, monkeypatch, fixed_now):
    """
    Όταν το διάστημα χωρίς παραγωγή > DEFAULT_PV_THRESHOLD και has_pv=True,
    πρέπει να κληθεί pn.async_create.
    """
    # 1) Ορίζουμε το load_last_update να επιστρέφει ημερομηνία
    #    DEFAULT_PV_THRESHOLD+1 ημέρες πριν, ώστε να ξεπερνά το όριο
    last_dt = fixed_now - timedelta(days=DEFAULT_PV_THRESHOLD + 1)
    monkeypatch.setattr(
        coordinator_module,
        "load_last_update",
        AsyncMock(return_value=last_dt),
    )

    # 2) Stub για τα υπόλοιπα persistence/fetch, δε μας απασχολούν τα δεδομένα
    monkeypatch.setattr(
        coordinator_module, "load_last_total", AsyncMock(return_value=0.0)
    )
    monkeypatch.setattr(coordinator_module, "fetch_since", AsyncMock())
    monkeypatch.setattr(coordinator_module, "batch_fetch", AsyncMock())

    # 3) Stub persistent_notification.async_create:
    #    επιστρέφει coroutine, καταγράφει args
    import asyncio

    call_args = []

    def fake_pn_create(hass_arg, message, *, title=None, notification_id=None):
        # Καταγράφουμε όσα περνάει η κλήση
        call_args.append((hass_arg, message, notification_id))

        # Επιστρέφουμε μια dummy coroutine για να την αναγνωρίσει ο coordinator
        async def dummy():
            return None

        return dummy()

    monkeypatch.setattr(coordinator_module.pn, "async_create", fake_pn_create)

    # Stub στο hass.async_create_task για να συλλέγει coroutines αντί να τα εκτελεί
    created = []

    def fake_async_create_task(coro):
        created.append(coro)
        # προγραμματίζουμε την εκτέλεση ώστε να μην έχουμε warning
        asyncio.get_event_loop().create_task(coro)

    hass.async_create_task = fake_async_create_task

    # 4) Δημιουργία coordinator και forcing στην περιοδική ενημέρωση
    coord = DeddieDataUpdateCoordinator(
        hass,
        token="tok",
        supply="sup",
        tax="tax",
        update_interval=timedelta(hours=1),
        choose_step_flag="D",
        has_pv=True,
        entry="entry_id1",
    )
    coord._first_update_done = True

    # 5) Εκτέλεση του update
    await coord._async_update_data()

    # 6) Έλεγχος ότι το fake_async_create κλήθηκε
    assert len(call_args) == 1

    # 7) Έλεγχος ότι προγραμματίστηκε το coroutine μέσω hass.async_create_task
    assert len(created) == 1, "αναμενόταν ένα coroutine να προγραμματιστεί"

    # 8) Έλεγχος παραμέτρων κλήσης
    h, msg, nid = call_args[0]
    assert h is hass
    # Το μήνυμα πρέπει να περιέχει warning για έλλειψη παραγωγής
    assert "Δεν ανιχνεύθηκε παραγωγή" in msg
    assert nid == f"deddie_metering_pv_warning_{coord._supply}"
