import sys
import types
import importlib
import pytest
from unittest.mock import AsyncMock
from datetime import datetime, timedelta

fake_update_coordinator = types.ModuleType("homeassistant.helpers.update_coordinator")


class FakeDataUpdateCoordinator:
    def __init__(self, hass, logger, name, update_interval):
        self.hass = hass
        self.logger = logger
        self.name = name
        self.update_interval = update_interval

    def async_request_refresh(self):
        pass


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


@pytest.mark.asyncio
async def test_fresh_install_first_update(hass):
    token, supply, tax = "token", "123456789", "987654321"
    coord = DeddieDataUpdateCoordinator(
        hass, token, supply, tax, timedelta(hours=1), skip_initial_refresh=True
    )
    result = await coord._async_update_data()
    assert result["total_kwh"] == 0.0
    assert result["latest_date"] is None
    assert result["last_fetch"] == coordinator_module.dt_util.now().isoformat()
    assert hass.loop.call_later.call_count == 1
    assert hass.loop.call_later.call_args[0][0] == 1


@pytest.mark.asyncio
async def test_fresh_install_second_update(monkeypatch, hass):
    monkeypatch.setattr(
        coordinator_module, "load_last_total", AsyncMock(return_value=42.5)
    )
    monkeypatch.setattr(
        coordinator_module,
        "load_last_update",
        AsyncMock(return_value=datetime(2024, 12, 31)),
    )
    coord = DeddieDataUpdateCoordinator(
        hass, "token", "supply", "tax", timedelta(hours=1), skip_initial_refresh=True
    )
    await coord._async_update_data()
    result = await coord._async_update_data()
    assert result["total_kwh"] == 42.5
    assert result["latest_date"] == "2024-12-31"
    assert result["last_fetch"] == coordinator_module.dt_util.now().isoformat()


@pytest.mark.asyncio
async def test_fresh_not_first(monkeypatch, hass):
    monkeypatch.setattr(
        coordinator_module, "load_last_total", AsyncMock(return_value=10.0)
    )
    monkeypatch.setattr(
        coordinator_module,
        "load_last_update",
        AsyncMock(return_value=datetime(2024, 12, 30)),
    )
    coord = DeddieDataUpdateCoordinator(
        hass, "token", "supply", "tax", timedelta(hours=1), skip_initial_refresh=False
    )
    result = await coord._async_update_data()
    assert result["total_kwh"] == 10.0
    assert result["latest_date"] == "2024-12-30"
    assert hass.loop.call_later.call_count == 1


@pytest.mark.asyncio
async def test_periodic_update_fetch_since(monkeypatch, hass, fixed_now):
    last = fixed_now - timedelta(days=3)
    monkeypatch.setattr(
        coordinator_module, "load_last_update", AsyncMock(return_value=last)
    )
    monkeypatch.setattr(
        coordinator_module, "load_last_total", AsyncMock(return_value=5.5)
    )
    fetch = AsyncMock()
    batch = AsyncMock()
    monkeypatch.setattr(coordinator_module, "fetch_since", fetch)
    monkeypatch.setattr(coordinator_module, "batch_fetch", batch)
    coord = DeddieDataUpdateCoordinator(
        hass, "token", "s", "t", timedelta(hours=1), skip_initial_refresh=False
    )
    coord._first_update_done = True
    result = await coord._async_update_data()
    fetch.assert_awaited_once()
    assert result["total_kwh"] == 5.5
    assert result["latest_date"] == last.date().isoformat()


@pytest.mark.asyncio
async def test_periodic_update_batch_fetch(monkeypatch, hass, fixed_now):
    last = fixed_now - timedelta(days=10)
    monkeypatch.setattr(
        coordinator_module, "load_last_update", AsyncMock(return_value=last)
    )
    monkeypatch.setattr(
        coordinator_module, "load_last_total", AsyncMock(return_value=7.0)
    )
    fetch = AsyncMock()
    batch = AsyncMock()
    monkeypatch.setattr(coordinator_module, "fetch_since", fetch)
    monkeypatch.setattr(coordinator_module, "batch_fetch", batch)
    coord = DeddieDataUpdateCoordinator(
        hass, "token", "s", "t", timedelta(hours=1), skip_initial_refresh=False
    )
    coord._first_update_done = True
    result = await coord._async_update_data()
    batch.assert_awaited_once()
    assert result["total_kwh"] == 7.0
    assert result["latest_date"] == last.date().isoformat()


@pytest.mark.asyncio
async def test_two_successive_not_first(monkeypatch, hass):
    """
    Successive calls with skip_initial_refresh=False: first schedules, second periodic.
    """
    monkeypatch.setattr(
        coordinator_module, "load_last_total", AsyncMock(return_value=3.3)
    )
    monkeypatch.setattr(
        coordinator_module,
        "load_last_update",
        AsyncMock(return_value=datetime(2025, 1, 1)),
    )
    monkeypatch.setattr(coordinator_module, "fetch_since", AsyncMock())
    monkeypatch.setattr(coordinator_module, "batch_fetch", AsyncMock())
    coord = DeddieDataUpdateCoordinator(
        hass, "tok", "sup", "tax", timedelta(hours=1), skip_initial_refresh=False
    )
    # First call
    await coord._async_update_data()
    assert coord._first_update_done is True
    # Second call should go to periodic
    await coord._async_update_data()
    # fetch_since or batch_fetch called at least once
    assert (
        coordinator_module.fetch_since.called or coordinator_module.batch_fetch.called
    )


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
        hass, "tok", "sup", "tax", timedelta(hours=1), skip_initial_refresh=True
    )
    # first update
    await coord._async_update_data()
    # second update via initial_jump branch
    result = await coord._async_update_data()
    assert result["total_kwh"] == 0.0
    assert result["latest_date"] is None


@pytest.mark.asyncio
async def test_batch_fetch_exception_wrapped(monkeypatch, hass):
    """
    Exception in batch_fetch should raise UpdateFailed.
    """
    last = datetime(2024, 12, 1)
    monkeypatch.setattr(
        coordinator_module, "load_last_update", AsyncMock(return_value=last)
    )
    monkeypatch.setattr(
        coordinator_module, "load_last_total", AsyncMock(return_value=1.1)
    )

    async def bad():
        raise Exception("fail")

    monkeypatch.setattr(
        coordinator_module, "batch_fetch", AsyncMock(side_effect=Exception("fail"))
    )
    coord = DeddieDataUpdateCoordinator(
        hass, "tok", "sup", "tax", timedelta(hours=1), skip_initial_refresh=False
    )
    coord._first_update_done = True
    with pytest.raises(UpdateFailed):
        await coord._async_update_data()


@pytest.mark.asyncio
async def test_fetch_since_exception_wrapped(monkeypatch, hass):
    """
    Exception in fetch_since should raise UpdateFailed.
    """
    last = datetime.now() - timedelta(days=1)
    monkeypatch.setattr(
        coordinator_module, "load_last_update", AsyncMock(return_value=last)
    )
    monkeypatch.setattr(
        coordinator_module, "load_last_total", AsyncMock(return_value=1.2)
    )
    monkeypatch.setattr(
        coordinator_module, "fetch_since", AsyncMock(side_effect=Exception("fail2"))
    )
    coord = DeddieDataUpdateCoordinator(
        hass, "tok", "sup", "tax", timedelta(hours=1), skip_initial_refresh=False
    )
    coord._first_update_done = True
    with pytest.raises(UpdateFailed):
        await coord._async_update_data()


def test_schedule_refresh(hass):
    coord = DeddieDataUpdateCoordinator(
        hass, "tok", "sup", "tax", timedelta(hours=1), skip_initial_refresh=False
    )
    coord.schedule_refresh()
    assert hass.loop.call_later.called
    assert hass.loop.call_later.call_args[0][0] == 1


@pytest.mark.asyncio
async def test_boundary_seven_days_fetch_since(monkeypatch, hass, fixed_now):
    """
    Αν το gap ακριβώς 7 ημερών, πρέπει να καλέσει fetch_since (όχι batch_fetch).
    """
    seven_days_ago = fixed_now - timedelta(days=7)
    monkeypatch.setattr(
        coordinator_module, "load_last_update", AsyncMock(return_value=seven_days_ago)
    )
    monkeypatch.setattr(
        coordinator_module, "load_last_total", AsyncMock(return_value=1.0)
    )
    fetch = AsyncMock()
    batch = AsyncMock()
    monkeypatch.setattr(coordinator_module, "fetch_since", fetch)
    monkeypatch.setattr(coordinator_module, "batch_fetch", batch)

    coord = DeddieDataUpdateCoordinator(
        hass, "tok", "s", "t", timedelta(hours=1), skip_initial_refresh=False
    )
    coord._first_update_done = True

    result = await coord._async_update_data()

    fetch.assert_awaited_once()
    batch.assert_not_called()
    assert result["total_kwh"] == 1.0


@pytest.mark.asyncio
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

    # Coordinator χωρίς skip, αλλά με flags ώστε να μπει απευθείας στο periodic
    coord = DeddieDataUpdateCoordinator(
        hass,
        token="tok",
        supply="sup",
        tax="tax",
        update_interval=timedelta(hours=1),
        skip_initial_refresh=False,
    )
    coord._first_update_done = True
    coord._initial_jump_done = True

    # Καλούμε το periodic update
    result = await coord._async_update_data()

    # Έλεγχος ότι πήρε το fetch_since branch
    fetch.assert_awaited_once()
    batch.assert_not_called()
    assert result["total_kwh"] == 2.0


@pytest.mark.asyncio
async def test_load_last_total_exception_raises_UpdateFailed(monkeypatch, hass):
    """
    Αν load_last_total αποτύχει με Exception, πρέπει να μετατραπεί σε UpdateFailed.
    """
    monkeypatch.setattr(
        coordinator_module,
        "load_last_total",
        AsyncMock(side_effect=Exception("io error")),
    )
    # Για να πάει στην periodic branch, ορίζουμε first_update_done=True
    coord = DeddieDataUpdateCoordinator(
        hass, "tok", "s", "t", timedelta(hours=1), skip_initial_refresh=False
    )
    coord._first_update_done = True

    with pytest.raises(UpdateFailed):
        await coord._async_update_data()
