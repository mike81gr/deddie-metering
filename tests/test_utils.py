import pytest
import asyncio
from datetime import datetime, timedelta
from unittest.mock import MagicMock, AsyncMock
from homeassistant.util import dt as dt_util
from deddie_metering.helpers.utils import (
    process_and_insert,
    fetch_since,
    batch_fetch,
    run_initial_batches,
)
from deddie_metering.const import ATTR_CONSUMPTION, ATTR_PRODUCTION, ATTR_INJECTION
import deddie_metering.helpers.utils as utils


@pytest.fixture(autouse=True)
def freeze_time(monkeypatch):
    # Freeze now for predictability
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

    hass.async_add_executor_job = fake_add_executor_job

    class Loop:
        def call_later(self, delay, callback):
            # Immediately run
            result = callback()
            if asyncio.iscoroutine(result):
                asyncio.get_event_loop().create_task(result)

    hass.loop = Loop()

    async def fake_create_task(coro):
        return await coro

    hass.async_create_task = fake_create_task
    return hass


@pytest.mark.asyncio
async def test_fetch_since_empty_curves(monkeypatch, fake_hass):
    monkeypatch.setattr(utils, "get_data_from_api", AsyncMock(return_value=[]))
    flags = {"update": False, "total": False}

    monkeypatch.setattr(utils, "save_last_update", flags["update"] is True)
    monkeypatch.setattr(utils, "save_last_total", flags["total"] is True)
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
    monkeypatch.setattr(
        utils,
        "get_data_from_api",
        AsyncMock(side_effect=Exception("err")),
    )
    save_update = AsyncMock()
    save_total = AsyncMock()
    monkeypatch.setattr(utils, "save_last_update", save_update)
    monkeypatch.setattr(utils, "save_last_total", save_total)
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
    assert not save_update.called
    assert not save_total.called


@pytest.mark.asyncio
async def test_fetch_since_success(monkeypatch, fake_hass):
    curves = [{"meterDate": "21/04/2025 01:00", "consumption": "5"}]
    last_valid = datetime(2025, 4, 21, 1, 0)
    total = 15.0
    monkeypatch.setattr(utils, "get_data_from_api", AsyncMock(return_value=curves))
    monkeypatch.setattr(
        utils,
        "process_and_insert",
        AsyncMock(return_value=(1, total, last_valid)),
    )
    saved = {"update": last_valid, "total": total}

    async def fake_save_update(h, s, dt, key=None):
        saved["update"] = dt

    async def fake_save_total(h, s, t, key=None):
        saved["total"] = t

    monkeypatch.setattr(utils, "save_last_update", fake_save_update)
    monkeypatch.setattr(utils, "save_last_total", fake_save_total)
    await fetch_since(
        fake_hass,
        "tok",
        "sup",
        "tax",
        datetime(2025, 4, 21),
        last_valid,
        "ctx",
        60,
    )
    assert saved["update"] == last_valid
    assert saved["total"] == total

    # Δοκιμή για παραγωγή (ATTR_PRODUCTION)
    saved.clear()
    await fetch_since(
        fake_hass,
        "tok",
        "sup",
        "tax",
        datetime(2025, 4, 21),
        last_valid,
        "ctx",
        60,
        class_type=ATTR_PRODUCTION,
    )
    assert saved["update"] == last_valid
    assert saved["total"] == total

    # Δοκιμή για έγχυση (ATTR_INJECTION)
    saved.clear()
    await fetch_since(
        fake_hass,
        "tok",
        "sup",
        "tax",
        datetime(2025, 4, 21),
        last_valid,
        "ctx",
        60,
        class_type=ATTR_INJECTION,
    )
    assert saved["update"] == last_valid
    assert saved["total"] == total


@pytest.mark.asyncio
async def test_batch_fetch_api_error_handled(monkeypatch, fake_hass):
    async def raise_err(*args, **kwargs):
        raise Exception("Boom")

    monkeypatch.setattr(utils, "get_data_from_api", raise_err)
    monkeypatch.setattr(utils, "load_last_total", AsyncMock(return_value=None))
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
    monkeypatch.setattr(utils, "get_data_from_api", AsyncMock(return_value=curves))
    monkeypatch.setattr(
        utils,
        "process_and_insert",
        AsyncMock(return_value=(1, new_total, last_valid)),
    )
    saved = {"update": None, "total": None}

    async def fake_save_update(h, s, dt, key=None):
        saved["update"] = dt

    async def fake_save_total(h, s, t, key=None):
        saved["total"] = t

    monkeypatch.setattr(utils, "save_last_update", fake_save_update)
    monkeypatch.setattr(utils, "save_last_total", fake_save_total)
    monkeypatch.setattr(utils, "load_last_total", AsyncMock(return_value=10.0))
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

    # Δοκιμή για παραγωγή (ATTR_PRODUCTION)
    saved.clear()
    await batch_fetch(
        fake_hass,
        "tok",
        "sup",
        "tax",
        datetime(2025, 4, 1),
        datetime(2025, 4, 2),
        "ctx",
        60,
        class_type=ATTR_PRODUCTION,
    )
    assert saved["update"] == last_valid
    assert saved["total"] == new_total

    # Δοκιμή για έγχυση (ATTR_INJECTION)
    saved.clear()
    await batch_fetch(
        fake_hass,
        "tok",
        "sup",
        "tax",
        datetime(2025, 4, 1),
        datetime(2025, 4, 2),
        "ctx",
        60,
        class_type=ATTR_INJECTION,
    )
    assert saved["update"] == last_valid
    assert saved["total"] == new_total


@pytest.mark.asyncio
async def test_run_initial_batches_end_time(monkeypatch, fake_hass):
    initial = datetime(2025, 2, 2)
    expected_end = dt_util.now()
    mock_batch = AsyncMock()
    monkeypatch.setattr(utils, "batch_fetch", mock_batch)
    await run_initial_batches(fake_hass, "tok", "sup", "tax", initial, False, True)
    mock_batch.assert_awaited_once()
    args = mock_batch.await_args.args
    # unpack including class_type
    _, _, _, _, arg_start, arg_end, label, delay, ctype = args
    assert arg_start == initial
    assert arg_end == expected_end
    assert label == "Αρχική λήψη κατανάλωσης"
    assert delay == 60
    assert ctype == ATTR_CONSUMPTION


@pytest.mark.asyncio
async def test_run_initial_batches_with_pv(monkeypatch, fake_hass):
    """
    When has_pv=True, batch_fetch is called for production and injection.
    """

    initial = datetime(2025, 1, 1)

    mock_batch = AsyncMock()
    monkeypatch.setattr(utils, "batch_fetch", mock_batch)

    # call with has_pv=True
    await run_initial_batches(fake_hass, "tok", "sup", "tax", initial, True, False)

    # should be called two times
    assert mock_batch.await_count == 2

    # check each call's context_label and class_type
    calls = mock_batch.await_args_list
    labels = [c.args[6] for c in calls]
    types_ = [c.args[8] for c in calls]

    assert labels == [
        "Αρχική λήψη παραγωγής",
        "Αρχική λήψη έγχυσης",
    ]
    assert types_ == [
        ATTR_PRODUCTION,
        ATTR_INJECTION,
    ]


@pytest.mark.asyncio
async def test_batch_fetch_no_records(monkeypatch, fake_hass):
    """If get_data_from_api returns [], nothing is imported or scheduled."""

    monkeypatch.setattr(utils, "get_data_from_api", AsyncMock(return_value=[]))
    pi = AsyncMock()
    su = AsyncMock()
    st = AsyncMock()
    ru = AsyncMock()
    monkeypatch.setattr(utils, "process_and_insert", pi)
    monkeypatch.setattr(utils, "save_last_update", su)
    monkeypatch.setattr(utils, "save_last_total", st)
    monkeypatch.setattr(utils, "run_update_future_statistics", ru)

    await batch_fetch(
        fake_hass,
        "tok",
        "sup",
        "tax",
        datetime(2025, 4, 1),
        datetime(2025, 4, 2),
        "CTX",
        30,
    )

    pi.assert_not_awaited()
    su.assert_not_awaited()
    st.assert_not_awaited()
    ru.assert_not_awaited()


@pytest.mark.asyncio
async def test_process_and_insert_production_and_injection(monkeypatch, fake_hass):
    """
    Ensure that, when only ‘consumption’ records exist, production/injection branches
    return nothing.
    """
    supply = "XYZ"
    base = datetime(2025, 5, 1, 0, 0)
    # build 24 valid records
    records = [
        {
            "meterDate": (base + timedelta(hours=i)).strftime("%d/%m/%Y %H:%M"),
            "consumption": str(i + 1),
        }
        for i in range(24)
    ]

    got = []

    monkeypatch.setattr(
        utils,
        "async_import_statistics",
        lambda _h, m, dl: got.append((m.statistic_id, m.name, len(dl))),
    )

    # Production branch (no ‘production’ data in these records)
    count_prod, total_prod, last_prod = await process_and_insert(
        fake_hass, records, supply, 0.0, ATTR_PRODUCTION
    )
    assert count_prod == 0
    assert total_prod == 0.0
    assert last_prod is None
    assert got == []

    # Injection branch (no ‘injection’ data in these records)
    count_inj, total_inj, last_inj = await process_and_insert(
        fake_hass, records, supply, 0.0, ATTR_INJECTION
    )
    assert count_inj == 0
    assert total_inj == 0.0
    assert last_inj is None
    assert got == []


@pytest.mark.asyncio
async def test_process_and_insert_grouping_error(caplog, fake_hass):
    """
    Malformed meterDate should be caught in grouping stage and skipped.
    """
    caplog.set_level("INFO")
    bad_rec = {"meterDate": "bad-date", "consumption": "1"}
    overall_count, total_consumption, last_valid = await process_and_insert(
        fake_hass, [bad_rec], "SUPPLY", 0.0, ATTR_CONSUMPTION
    )
    assert overall_count == 0
    assert total_consumption == 0.0
    assert last_valid is None
    assert "Αδυναμία ομαδοποίησης record" in caplog.text


@pytest.mark.asyncio
async def test_process_and_insert_bad_consumption_inner(monkeypatch, fake_hass):
    """
    A non-numeric consumption value should be skipped in processing, but other
    records imported.
    """
    base = datetime(2025, 5, 1, 1, 0)
    records = [
        {
            "meterDate": (base + timedelta(hours=i)).strftime("%d/%m/%Y %H:%M"),
            # First record malformed, others valid '1'
            "consumption": ("bad" if i == 0 else "1"),
        }
        for i in range(24)
    ]
    captured = []

    async def dummy_import(_h, metadata, data_list):
        captured.extend(data_list)

    monkeypatch.setattr(utils, "async_import_statistics", dummy_import)
    overall_count, total_consumption, last_valid = await process_and_insert(
        fake_hass, records, "SUPPLY", 0.0, "consumption"
    )
    # All 24 records attempted, with one skipped in inner exception
    assert overall_count == 24
    assert len(captured) == 23
    # Total consumption equals 23 * 1.0
    assert total_consumption == 23.0
    # Last valid meterDate corresponds to final record
    assert last_valid == base + timedelta(hours=23)


@pytest.mark.asyncio
async def test_batch_fetch_first_date_parse_error(monkeypatch, fake_hass, caplog):
    """
    If the first record’s meterDate is malformed, batch_fetch should log
    the parsing error but still continue and eventually call process_and_insert.
    """
    caplog.set_level("INFO")
    # Prepare one malformed record so the first‐date parse fails,
    # then process_and_insert returns a last_valid so loop exits.
    bad_records = [{"meterDate": "not‐a‐date", "consumption": "1"}]
    monkeypatch.setattr(utils, "get_data_from_api", AsyncMock(return_value=bad_records))
    # Fake process_and_insert so we get out of the loop
    fake_last = datetime(2025, 3, 2, 1, 0)
    monkeypatch.setattr(
        utils, "process_and_insert", AsyncMock(return_value=(1, 1.0, fake_last))
    )
    # Stub save_last_* so no errors
    monkeypatch.setattr(utils, "save_last_update", AsyncMock())
    monkeypatch.setattr(utils, "save_last_total", AsyncMock())

    # Run a single‐day batch
    start = datetime(2025, 3, 1)
    end = start + timedelta(days=1)
    await utils.batch_fetch(fake_hass, "tok", "sup", "tax", start, end, "CTX", 0)

    # The malformed‐date exception should have been logged
    assert "Αδυναμία επεξεργασίας της πρώτης meterDate" in caplog.text


@pytest.mark.asyncio
async def test_fetch_since_first_date_parse_error(monkeypatch, fake_hass, caplog):
    """
    If fetch_since gets a malformed meterDate on the first record,
    it should log that parsing error but still call save_last_* afterwards.
    """
    caplog.set_level("INFO")
    # Make get_data_from_api return one bad record
    bad = [{"meterDate": "bad", "consumption": "1"}]
    monkeypatch.setattr(utils, "get_data_from_api", AsyncMock(return_value=bad))
    # process_and_insert will return a valid last_valid, so fetch_since continues
    last_valid = datetime(2025, 4, 1, 0, 0)
    monkeypatch.setattr(
        utils,
        "process_and_insert",
        AsyncMock(return_value=(1, 2.0, last_valid)),
    )
    # Stub out save_last_update and save_last_total
    saved = {"u": None, "t": None}

    async def fake_save_update(h, s, dt, key=None):
        saved["u"] = dt

    async def fake_save_total(h, s, t, key=None):
        saved["t"] = t

    monkeypatch.setattr(utils, "save_last_update", fake_save_update)
    monkeypatch.setattr(utils, "save_last_total", fake_save_total)

    # Run fetch_since
    start = datetime(2025, 4, 1)
    end = start + timedelta(days=1)
    await utils.fetch_since(fake_hass, "tok", "sup", "tax", start, end, "CTX", 0)

    # Should have logged the parsing failure
    assert "Αδυναμία επεξεργασίας της πρώτης " in caplog.text
    # And still saved the last_valid date and total
    assert saved["u"] == last_valid
    assert saved["t"] == 2.0


@pytest.mark.asyncio
async def test_process_and_insert_display_names(monkeypatch, fake_hass):
    """
    Ensure display_name is generated correctly for all class_type cases.
    """
    supply = "XYZ"
    base = datetime(2025, 5, 1, 1, 0)
    records = [
        {
            "meterDate": (base + timedelta(hours=i)).strftime("%d/%m/%Y %H:%M"),
            "consumption": "1",
        }
        for i in range(24)
    ]

    captured = []

    # Override το StatisticMetaData με dummy version
    class DummyMeta:
        def __init__(self, statistic_id, name, **kwargs):
            self.statistic_id = statistic_id
            self.name = name
            self.unit_of_measurement = kwargs.get("unit_of_measurement")
            self.has_mean = kwargs.get("has_mean", False)
            self.has_sum = kwargs.get("has_sum", True)

    monkeypatch.setattr(
        utils,
        "StatisticMetaData",
        DummyMeta,
    )

    async def dummy_import_statistics(hass, metadata, stats):
        captured.append((metadata.statistic_id, metadata.name, len(stats)))

    monkeypatch.setattr(utils, "async_import_statistics", dummy_import_statistics)

    # Κατανάλωση
    await process_and_insert(fake_hass, records, supply, 0.0, "consumption")
    # Παραγωγή
    await process_and_insert(fake_hass, records, supply, 0.0, "production")
    # Έγχυση
    await process_and_insert(fake_hass, records, supply, 0.0, "injection")

    # Έλεγχος
    assert len(captured) == 3
    names = [c[1] for c in captured]
    assert f"Κατανάλωση ΔΕΔΔΗΕ {supply}" in names
    assert f"Παραγωγή ΔΕΔΔΗΕ {supply}" in names
    assert f"Έγχυση ΔΕΔΔΗΕ {supply}" in names
