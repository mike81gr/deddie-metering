import pytest
import asyncio
from datetime import datetime, timedelta
from unittest.mock import MagicMock, AsyncMock
from homeassistant.util import dt as dt_util
from deddie_metering.utils import (
    process_and_insert,
    fetch_since,
    batch_fetch,
    run_initial_batches,
)


@pytest.fixture(autouse=True)
def freeze_time(monkeypatch):
    # Freeze dt_util.now and dt_util.as_local for predictability
    fixed = datetime(2025, 4, 22, 12, 0, 0)
    monkeypatch.setattr(dt_util, "now", lambda: fixed)
    monkeypatch.setattr(dt_util, "as_local", lambda x: x)


@pytest.fixture
def fake_hass():
    # Fake hass with sync executor and loop
    hass = MagicMock()

    async def fake_add_executor_job(func, *args):
        result = func(*args)
        if asyncio.iscoroutine(result):
            return await result
        return result

    hass.async_add_executor_job = fake_add_executor_job

    class Loop:
        def call_later(self, delay, callback):
            # Immediately run
            result = callback()
            if asyncio.iscoroutine(result):
                asyncio.get_event_loop().create_task(result)

    hass.loop = Loop()

    # Stub async_create_task so that create_task(coro) actually runs coro
    async def fake_create_task(coro):
        return await coro

    hass.async_create_task = fake_create_task
    return hass


# ------------------ process_and_insert tests ------------------


@pytest.mark.asyncio
async def test_process_and_insert_full_day(monkeypatch, fake_hass):
    supply = "123"
    base = datetime(2025, 4, 21, 1, 0)
    records = [
        {
            "meterDate": (base + timedelta(hours=i)).strftime("%d/%m/%Y %H:%M"),
            "consumption": str(i + 1),
        }
        for i in range(24)
    ]
    captured = []

    async def dummy_import(_hass, metadata, data_list):
        captured.extend(data_list)

    monkeypatch.setattr("deddie_metering.utils.async_import_statistics", dummy_import)
    overall_count, total_consumption, last_valid = await process_and_insert(
        fake_hass, records, supply, total_consumption=0.0
    )
    assert overall_count == 24
    assert total_consumption == 300.0
    assert last_valid == base + timedelta(hours=23)
    assert len(captured) == 24


@pytest.mark.asyncio
async def test_process_and_insert_partial_day(monkeypatch, fake_hass):
    supply = "123"
    base = datetime(2025, 4, 21, 1, 0)
    records = [
        {
            "meterDate": (base + timedelta(hours=i)).strftime("%d/%m/%Y %H:%M"),
            "consumption": str(i + 1),
        }
        for i in range(23)
    ]
    monkeypatch.setattr(
        "deddie_metering.utils.async_import_statistics",
        lambda *_: (_ for _ in ()).throw(AssertionError("Should not import stats")),
    )
    overall_count, total_consumption, last_valid = await process_and_insert(
        fake_hass, records, supply, total_consumption=0.0
    )
    assert overall_count == 0
    assert total_consumption == 0.0
    assert last_valid is None


@pytest.mark.asyncio
async def test_mixed_two_days(monkeypatch, fake_hass):
    supply = "123"
    base1 = datetime(2025, 4, 20, 1, 0)
    recs1 = [
        {
            "meterDate": (base1 + timedelta(hours=i)).strftime("%d/%m/%Y %H:%M"),
            "consumption": "1",
        }
        for i in range(24)
    ]
    base2 = datetime(2025, 4, 21, 1, 0)
    recs2 = [
        {
            "meterDate": (base2 + timedelta(hours=i)).strftime("%d/%m/%Y %H:%M"),
            "consumption": "2",
        }
        for i in range(23)
    ]
    records = recs1 + recs2
    captured = []

    async def dummy_import(_hass, metadata, data_list):
        captured.extend(data_list)

    monkeypatch.setattr("deddie_metering.utils.async_import_statistics", dummy_import)
    overall_count, total_consumption, last_valid = await process_and_insert(
        fake_hass, records, supply, total_consumption=0.0
    )
    assert overall_count == 24
    assert total_consumption == 24.0
    assert last_valid == base1 + timedelta(hours=23)
    assert len(captured) == 24


@pytest.mark.asyncio
async def test_invalid_consumption_within_full_day(monkeypatch, fake_hass):
    supply = "123"
    base = datetime(2025, 4, 22, 1, 0)
    records = []
    for i in range(24):
        dt_str = (base + timedelta(hours=i)).strftime("%d/%m/%Y %H:%M")
        cons = "" if i == 5 else str(i + 1)
        records.append({"meterDate": dt_str, "consumption": cons})
    monkeypatch.setattr(
        "deddie_metering.utils.async_import_statistics",
        lambda *_: (_ for _ in ()).throw(AssertionError("Should not import")),
    )
    overall_count, total_consumption, last_valid = await process_and_insert(
        fake_hass, records, supply, total_consumption=0.0
    )
    assert overall_count == 0
    assert total_consumption == 0.0
    assert last_valid is None


@pytest.mark.asyncio
async def test_process_and_insert_malformed_date(monkeypatch, fake_hass):
    supply = "123"
    base = datetime(2025, 4, 21, 1, 0)
    records = []
    for i in range(24):
        dt_str = (
            "invalid-date"
            if i == 5
            else (base + timedelta(hours=i)).strftime("%d/%m/%Y %H:%M")
        )
        records.append({"meterDate": dt_str, "consumption": "1"})
    monkeypatch.setattr(
        "deddie_metering.utils.async_import_statistics",
        lambda *_: (_ for _ in ()).throw(AssertionError("Should not import")),
    )
    overall_count, total_consumption, last_valid = await process_and_insert(
        fake_hass, records, supply, total_consumption=0.0
    )
    assert overall_count == 0
    assert total_consumption == 0.0
    assert last_valid is None


@pytest.mark.asyncio
async def test_process_and_insert_two_full_days(monkeypatch, fake_hass):
    supply = "123"
    # Ξεκινάμε στις 01:00 για κάθε ημέρα
    day1 = datetime(2025, 4, 20, 1, 0)
    day2 = datetime(2025, 4, 21, 1, 0)

    records = []
    for base in (day1, day2):
        for i in range(24):
            dt = (base + timedelta(hours=i)).strftime("%d/%m/%Y %H:%M")
            records.append({"meterDate": dt, "consumption": "1"})

    captured = []

    async def dummy_import(_h, m, data_list):
        captured.extend(data_list)

    # Αντικαθιστούμε σωστά το async_import_statistics
    monkeypatch.setattr("deddie_metering.utils.async_import_statistics", dummy_import)

    overall_count, total_consumption, last_valid = await process_and_insert(
        fake_hass, records, supply, total_consumption=0.0
    )

    # Τώρα θα είναι δύο πλήρεις ημέρες ⇒ 48 εγγραφές
    assert overall_count == 48
    assert total_consumption == 48.0
    # Τελευταίο timestamp: day2 + 23 ώρες
    assert last_valid == day2 + timedelta(hours=23)
    assert len(captured) == 48


# ------------------ fetch_since tests ------------------


@pytest.mark.asyncio
async def test_fetch_since_empty_curves(monkeypatch, fake_hass):
    monkeypatch.setattr(
        "deddie_metering.utils.get_data_from_api", AsyncMock(return_value=[])
    )
    flags = {"update": False, "total": False}

    async def fake_save_update(h, s, dt):
        flags["update"] = True

    async def fake_save_total(h, s, t):
        flags["total"] = True

    monkeypatch.setattr("deddie_metering.utils.save_last_update", fake_save_update)
    monkeypatch.setattr("deddie_metering.utils.save_last_total", fake_save_total)
    await fetch_since(
        fake_hass,
        "tok",
        "sup",
        "tax",
        dt_util.now() - timedelta(days=1),
        dt_util.now(),
        "ctx",
        0,
    )
    assert not any(flags.values())


@pytest.mark.asyncio
async def test_fetch_since_exception_handled(monkeypatch, fake_hass):
    """
    Should handle exceptions in get_data_from_api without raising.
    """
    monkeypatch.setattr(
        "deddie_metering.utils.get_data_from_api",
        AsyncMock(side_effect=Exception("err")),
    )
    save_update = AsyncMock()
    save_total = AsyncMock()
    monkeypatch.setattr("deddie_metering.utils.save_last_update", save_update)
    monkeypatch.setattr("deddie_metering.utils.save_last_total", save_total)
    # Should not raise
    await fetch_since(
        fake_hass,
        "tok",
        "sup",
        "tax",
        dt_util.now() - timedelta(days=1),
        dt_util.now(),
        "ctx",
        0,
    )
    # No saves should have occurred
    assert not save_update.called
    assert not save_total.called


@pytest.mark.asyncio
async def test_fetch_since_no_valid(monkeypatch, fake_hass):
    # API επιστρέφει εγγραφές αλλά process_and_insert δεν βρίσκει έγκυρα
    monkeypatch.setattr(
        "deddie_metering.utils.get_data_from_api",
        AsyncMock(return_value=[{"meterDate": "01/01/2025 00:00"}]),
    )
    monkeypatch.setattr(
        "deddie_metering.utils.process_and_insert",
        AsyncMock(return_value=(0, 0.0, None)),
    )
    save_update = AsyncMock()
    save_total = AsyncMock()
    monkeypatch.setattr("deddie_metering.utils.save_last_update", save_update)
    monkeypatch.setattr("deddie_metering.utils.save_last_total", save_total)

    await fetch_since(
        fake_hass,
        "tok",
        "sup",
        "tax",
        dt_util.now() - timedelta(days=1),
        dt_util.now(),
        "ctx",
        stats_delay=10,
    )

    assert not save_update.called
    assert not save_total.called


@pytest.mark.asyncio
async def test_fetch_since_success(monkeypatch, fake_hass):
    curves = [{"meterDate": "21/04/2025 01:00", "consumption": "5"}]
    last_valid = datetime(2025, 4, 21, 1, 0)
    total = 15.0
    monkeypatch.setattr(
        "deddie_metering.utils.get_data_from_api", AsyncMock(return_value=curves)
    )
    monkeypatch.setattr(
        "deddie_metering.utils.process_and_insert",
        AsyncMock(return_value=(1, total, last_valid)),
    )
    saved = {"update": last_valid, "total": total}

    async def fake_save_update(h, s, dt):
        saved["update"] = dt

    async def fake_save_total(h, s, t):
        saved["total"] = t

    monkeypatch.setattr("deddie_metering.utils.save_last_update", fake_save_update)
    monkeypatch.setattr("deddie_metering.utils.save_last_total", fake_save_total)
    await fetch_since(
        fake_hass, "tok", "sup", "tax", datetime(2025, 4, 21), last_valid, "ctx", 60
    )
    assert saved["update"] == last_valid
    assert saved["total"] == total


# ------------------ batch_fetch tests ------------------


@pytest.mark.asyncio
async def test_batch_fetch_api_error_handled(monkeypatch, fake_hass):
    async def raise_err(*args, **kwargs):
        raise Exception("Boom")

    monkeypatch.setattr("deddie_metering.utils.get_data_from_api", raise_err)
    monkeypatch.setattr(
        "deddie_metering.utils.load_last_total", AsyncMock(return_value=None)
    )
    # Should not raise
    await batch_fetch(
        fake_hass,
        "tok",
        "sup",
        "tax",
        datetime(2025, 1, 1),
        datetime(2025, 1, 2),
        "ctx",
        60,
    )


@pytest.mark.asyncio
async def test_batch_fetch_single_batch(monkeypatch, fake_hass):
    curves = [{"meterDate": "01/04/2025 01:00", "consumption": "2"}]
    last_valid = datetime(2025, 4, 1, 1, 0)
    new_total = 20.0
    monkeypatch.setattr(
        "deddie_metering.utils.get_data_from_api", AsyncMock(return_value=curves)
    )
    monkeypatch.setattr(
        "deddie_metering.utils.process_and_insert",
        AsyncMock(return_value=(1, new_total, last_valid)),
    )
    saved = {"update": None, "total": None}

    async def fake_save_update(h, s, dt):
        saved["update"] = dt

    async def fake_save_total(h, s, t):
        saved["total"] = t

    monkeypatch.setattr("deddie_metering.utils.save_last_update", fake_save_update)
    monkeypatch.setattr("deddie_metering.utils.save_last_total", fake_save_total)
    monkeypatch.setattr(
        "deddie_metering.utils.load_last_total", AsyncMock(return_value=10.0)
    )

    await batch_fetch(
        fake_hass,
        "tok",
        "sup",
        "tax",
        datetime(2025, 4, 1),
        datetime(2025, 4, 2),
        "ctx",
        60,
    )
    assert saved["update"] == last_valid
    assert saved["total"] == new_total


@pytest.mark.asyncio
async def test_batch_fetch_multiple_batches(monkeypatch, fake_hass):
    """
    Should split into multiple batches when date range exceeds 364 days.
    """
    calls = []

    async def fake_get(h, token, supply, tax, sdt, edt):
        calls.append((sdt, edt))
        return []

    monkeypatch.setattr("deddie_metering.utils.get_data_from_api", fake_get)
    monkeypatch.setattr(
        "deddie_metering.utils.process_and_insert",
        AsyncMock(return_value=(0, 0.0, None)),
    )
    monkeypatch.setattr("deddie_metering.utils.save_last_update", AsyncMock())
    monkeypatch.setattr("deddie_metering.utils.save_last_total", AsyncMock())
    monkeypatch.setattr(
        "deddie_metering.utils.load_last_total", AsyncMock(return_value=None)
    )

    start = datetime(2025, 1, 1)
    end = start + timedelta(days=400)
    await batch_fetch(fake_hass, "tok", "sup", "tax", start, end, "ctx", 60)

    # Should have two calls: [start → start+364], [start+365 → end]
    assert len(calls) == 2
    first_sdt, first_edt = calls[0]
    second_sdt, second_edt = calls[1]
    assert first_sdt == start
    assert first_edt == start + timedelta(days=364)
    assert second_sdt == first_edt + timedelta(days=1)
    assert second_edt == end


@pytest.mark.asyncio
async def test_batch_fetch_schedules_future_stats(monkeypatch, fake_hass):
    from datetime import datetime, timedelta
    from unittest.mock import AsyncMock

    curves = [{"meterDate": "01/03/2025 01:00", "consumption": "2"}]
    last_valid = datetime(2025, 3, 1, 1, 0)
    new_total = 200.0

    monkeypatch.setattr(
        "deddie_metering.utils.get_data_from_api", AsyncMock(return_value=curves)
    )
    monkeypatch.setattr(
        "deddie_metering.utils.process_and_insert",
        AsyncMock(return_value=(1, new_total, last_valid)),
    )
    monkeypatch.setattr("deddie_metering.utils.save_last_update", AsyncMock())
    monkeypatch.setattr("deddie_metering.utils.save_last_total", AsyncMock())
    monkeypatch.setattr(
        "deddie_metering.utils.load_last_total", AsyncMock(return_value=167.0)
    )

    # Μαϊμού στατιστικά μέλλοντος
    future_stats = AsyncMock()
    monkeypatch.setattr(
        "deddie_metering.utils.run_update_future_statistics", future_stats
    )

    # stats_delay=0 για άμεση εκτέλεση του callback
    await batch_fetch(
        fake_hass,
        "tok",
        "sup",
        "tax",
        datetime(2025, 3, 1),
        datetime(2025, 3, 2),
        "ctx",
        stats_delay=0,
    )

    # αφήνουμε τον loop να τρέξει το scheduled task
    await asyncio.sleep(0)

    expected_start = last_valid - timedelta(hours=1)
    future_stats.assert_awaited_once_with(fake_hass, "sup", expected_start, new_total)


# ------------------ run_initial_batches test ------------------


@pytest.mark.asyncio
async def test_run_initial_batches_proxy(monkeypatch, fake_hass):
    import deddie_metering.utils as utils

    initial = datetime(2025, 1, 1)
    end = dt_util.now()
    mock_batch = AsyncMock()
    monkeypatch.setattr(utils, "batch_fetch", mock_batch)
    await run_initial_batches(fake_hass, "tok", "sup", "tax", initial)
    mock_batch.assert_awaited_once_with(
        fake_hass, "tok", "sup", "tax", initial, end, "Αρχική λήψη", 60
    )


# ------------------ ADDITIONAL NEW TESTS ------------------


@pytest.mark.asyncio
async def test_fetch_since_schedules_future_stats(monkeypatch, fake_hass):
    """
    fetch_since should schedule future statistics when process returns
    a valid last date.
    """
    # Stub persistent load so fetch_since can proceed
    monkeypatch.setattr(
        "deddie_metering.utils.load_last_total", AsyncMock(return_value=0.0)
    )
    curves = [{"meterDate": "21/04/2025 01:00", "consumption": "3"}]
    last_valid = datetime(2025, 4, 21, 1, 0)
    total = 7.0

    monkeypatch.setattr(
        "deddie_metering.utils.get_data_from_api", AsyncMock(return_value=curves)
    )
    monkeypatch.setattr(
        "deddie_metering.utils.process_and_insert",
        AsyncMock(return_value=(1, total, last_valid)),
    )

    save_update = AsyncMock()
    save_total = AsyncMock()
    monkeypatch.setattr("deddie_metering.utils.save_last_update", save_update)
    monkeypatch.setattr("deddie_metering.utils.save_last_total", save_total)

    future_stats = AsyncMock()
    monkeypatch.setattr(
        "deddie_metering.utils.run_update_future_statistics", future_stats
    )

    await fetch_since(
        fake_hass,
        "tok",
        "sup",
        "tax",
        datetime(2025, 4, 21),
        datetime(2025, 4, 22),
        "ctx",
        stats_delay=0,
    )
    # let the loop run the scheduled task
    await asyncio.sleep(0)

    assert save_update.called
    assert save_total.called
    expected_start = last_valid - timedelta(hours=1)
    future_stats.assert_awaited_once_with(fake_hass, "sup", expected_start, total)


@pytest.mark.asyncio
async def test_run_initial_batches_end_time(monkeypatch, fake_hass):
    """run_initial_batches should call batch_fetch with end_dt = dt_util.now()."""
    import deddie_metering.utils as utils

    initial = datetime(2025, 2, 2)
    expected_end = dt_util.now()
    mock_batch = AsyncMock()
    monkeypatch.setattr(utils, "batch_fetch", mock_batch)

    await run_initial_batches(fake_hass, "tok", "sup", "tax", initial)

    mock_batch.assert_awaited_once()
    _, _, _, _, arg_start, arg_end, label, delay = mock_batch.await_args.args
    assert arg_start == initial
    assert arg_end == expected_end
    assert label == "Αρχική λήψη"
    assert delay == 60
