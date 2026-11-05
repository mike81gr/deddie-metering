import logging
from datetime import datetime, timedelta
from unittest.mock import AsyncMock, MagicMock

import pytest

import deddie_metering.helpers.external_statistics as ext
from deddie_metering.const import ATTR_CONSUMPTION, ATTR_INJECTION, ATTR_PRODUCTION
import deddie_metering.helpers.utils as utils
from deddie_metering.helpers.utils import process_and_insert

SUPPLY = "123456789"
STAT_ID = f"deddie_metering:consumption_{SUPPLY}"


def _day_records(day: datetime, kwh: float = 1.0) -> list[dict]:
    """24 hourly ΔΕΔΔΗΕ records whose meterDate ends each hour of `day`."""
    return [
        {
            "meterDate": (day + timedelta(hours=h + 1)).strftime("%d/%m/%Y %H:%M"),
            "consumption": str(kwh),
        }
        for h in range(24)
    ]


class FakeRecorder:
    """In-memory hourly statistic: {start: sum}. Mimics the two recorder reads."""

    def __init__(self, rows: dict | None = None, fail: bool = False):
        self.rows = dict(rows or {})
        self.fail = fail
        self.written: list = []
        # HA queues imports on the recorder thread; nothing is readable until
        # the queue runs (and during startup it only runs once HA has started).
        self.deferred = False
        self.queue: list = []

    async def async_add_executor_job(self, func, *args):
        if self.fail:
            raise RuntimeError("database is locked")
        return func(*args)

    def statistics_during_period(self, hass, start, end, ids, period, units, types):
        (sid,) = ids
        keys = sorted(k for k in self.rows if k >= start and (end is None or k < end))
        return {sid: [{"start": k, "sum": self.rows[k]} for k in keys]} if keys else {}

    def add_external(self, hass, metadata, stats):
        self.written.append((metadata, list(stats)))
        self.queue.extend(stats)
        if not self.deferred:
            self.commit()

    def commit(self):
        for s in self.queue:
            self.rows[s["start"]] = s["sum"]
        self.queue = []

    async def async_block_till_done(self):
        self.commit()


@pytest.fixture
def recorder(monkeypatch):
    rec = FakeRecorder()
    monkeypatch.setattr(ext, "_PENDING", {})
    monkeypatch.setattr(ext, "get_instance", lambda hass: rec)
    monkeypatch.setattr(ext, "statistics_during_period", rec.statistics_during_period)
    monkeypatch.setattr(ext, "async_add_external_statistics", rec.add_external)
    monkeypatch.setattr(utils, "async_add_external_statistics", rec.add_external)
    monkeypatch.setattr(ext, "StatisticData", dict)
    monkeypatch.setattr(utils, "StatisticData", dict)
    monkeypatch.setattr(ext, "StatisticMetaData", dict)
    return rec


def test_external_statistic_id():
    assert ext.external_statistic_id("consumption", SUPPLY) == STAT_ID


def test_external_metadata(recorder):
    md = ext.external_metadata("production", SUPPLY)
    assert md["source"] == "deddie_metering"
    assert md["statistic_id"] == f"deddie_metering:production_{SUPPLY}"
    assert md["name"] == f"Παραγωγή ΔΕΔΔΗΕ {SUPPLY}"
    assert md["has_sum"] is True
    assert md["unit_class"] == "energy"


@pytest.mark.asyncio
async def test_first_import_starts_from_zero(recorder):
    day = datetime(2026, 11, 1)
    count, total, last = await process_and_insert(
        MagicMock(), _day_records(day), SUPPLY, 999.0, "consumption"
    )
    assert count == 24
    assert total == pytest.approx(24.0)  # base 0, NOT the passed-in 999.0
    assert recorder.rows[day] == pytest.approx(1.0)
    assert recorder.rows[day + timedelta(hours=23)] == pytest.approx(24.0)
    assert recorder.written[0][0]["statistic_id"] == STAT_ID


@pytest.mark.asyncio
async def test_continues_from_previous_hour(recorder):
    day = datetime(2026, 11, 2)
    recorder.rows[day - timedelta(hours=1)] = 100.0
    _, total, _ = await process_and_insert(
        MagicMock(), _day_records(day, 2.0), SUPPLY, 0.0, "consumption"
    )
    assert recorder.rows[day] == pytest.approx(102.0)
    assert total == pytest.approx(148.0)


@pytest.mark.asyncio
async def test_base_falls_back_to_full_history_on_gap(recorder):
    day = datetime(2026, 11, 10)
    recorder.rows[datetime(2025, 1, 1)] = 50.0  # long gap, far before first_start
    _, total, _ = await process_and_insert(
        MagicMock(), _day_records(day), SUPPLY, 0.0, "consumption"
    )
    assert recorder.rows[day] == pytest.approx(51.0)
    assert total == pytest.approx(74.0)


@pytest.mark.asyncio
async def test_reimport_is_idempotent(recorder):
    day = datetime(2026, 11, 3)
    recorder.rows[day - timedelta(hours=1)] = 10.0
    recs = _day_records(day)
    await process_and_insert(MagicMock(), recs, SUPPLY, 0.0, "consumption")
    first = dict(recorder.rows)
    _, total, _ = await process_and_insert(
        MagicMock(), recs, SUPPLY, 0.0, "consumption"
    )
    assert recorder.rows == first
    assert total == pytest.approx(34.0)


@pytest.mark.asyncio
async def test_reimport_before_all_rows_rebases_from_zero(recorder):
    """Options-flow 'earlier initial date' re-import: starts before every row."""
    later = datetime(2026, 11, 5)
    recorder.rows[later] = 5000.0
    earlier = datetime(2026, 11, 4)
    _, total, _ = await process_and_insert(
        MagicMock(), _day_records(earlier), SUPPLY, 0.0, "consumption"
    )
    assert recorder.rows[earlier] == pytest.approx(1.0)
    assert total == pytest.approx(24.0)


@pytest.mark.asyncio
async def test_base_read_failure_writes_nothing(recorder, caplog):
    recorder.fail = True
    with caplog.at_level(logging.ERROR, logger="deddie_metering"):
        with pytest.raises(ext.StatisticsReadError):
            await process_and_insert(
                MagicMock(),
                _day_records(datetime(2026, 11, 1)),
                SUPPLY,
                42.0,
                "consumption",
            )
    assert recorder.written == []
    assert "database is locked" in caplog.text


@pytest.mark.asyncio
async def test_warns_when_rows_exist_after_import(recorder, caplog):
    day = datetime(2026, 10, 1)
    stale = datetime(2026, 11, 1)
    recorder.rows[stale] = 9999.0
    with caplog.at_level(logging.WARNING, logger="deddie_metering"):
        await process_and_insert(
            MagicMock(), _day_records(day), SUPPLY, 0.0, "consumption"
        )
    assert "μεταγενέστερες εγγραφές" in caplog.text
    assert recorder.rows[stale] == 9999.0  # surfaced, not silently shifted


@pytest.mark.asyncio
async def test_has_rows(recorder):
    recorder.rows[datetime(2026, 1, 2)] = 1.0
    assert await ext.async_has_rows(
        MagicMock(), STAT_ID, datetime(2026, 1, 1), datetime(2026, 1, 8)
    )
    assert not await ext.async_has_rows(
        MagicMock(), STAT_ID, datetime(2026, 2, 1), datetime(2026, 2, 8)
    )


@pytest.mark.asyncio
async def test_backfill_runs_when_statistic_empty(monkeypatch, recorder):
    bf = AsyncMock()
    monkeypatch.setattr(utils, "batch_fetch", bf)
    start = datetime(2025, 4, 15)
    await utils.async_ensure_external_statistics(
        MagicMock(), "tok", SUPPLY, "tax", start, has_pv=False
    )
    bf.assert_awaited_once()
    args = bf.await_args.args
    assert args[4] == start and args[-1] == ATTR_CONSUMPTION


@pytest.mark.asyncio
async def test_backfill_runs_again_when_first_week_empty(monkeypatch, recorder):
    """A failed earlier backfill left only recent rows: refill from initial_time."""
    recorder.rows[datetime(2026, 11, 1)] = 10.0
    bf = AsyncMock()
    monkeypatch.setattr(utils, "batch_fetch", bf)
    await utils.async_ensure_external_statistics(
        MagicMock(), "tok", SUPPLY, "tax", datetime(2025, 4, 15), has_pv=False
    )
    bf.assert_awaited_once()


@pytest.mark.asyncio
async def test_backfill_skipped_when_first_week_present(monkeypatch, recorder):
    recorder.rows[datetime(2025, 4, 16)] = 1.0
    bf = AsyncMock()
    monkeypatch.setattr(utils, "batch_fetch", bf)
    await utils.async_ensure_external_statistics(
        MagicMock(), "tok", SUPPLY, "tax", datetime(2025, 4, 15), has_pv=False
    )
    bf.assert_not_awaited()


@pytest.mark.asyncio
async def test_backfill_covers_pv_types(monkeypatch, recorder):
    bf = AsyncMock()
    monkeypatch.setattr(utils, "batch_fetch", bf)
    await utils.async_ensure_external_statistics(
        MagicMock(), "tok", SUPPLY, "tax", datetime(2025, 4, 15), has_pv=True
    )
    types = [c.args[-1] for c in bf.await_args_list]
    assert types == [ATTR_CONSUMPTION, ATTR_PRODUCTION, ATTR_INJECTION]


def _starting_hass():
    """HA during startup: the recorder has not run any queued import yet."""
    hass = MagicMock()
    hass.is_running = False
    return hass


@pytest.mark.asyncio
async def test_startup_second_batch_bases_on_queued_rows(recorder):
    """Batch 2 must continue from batch 1 even though batch 1 is only queued."""
    recorder.deferred = True
    hass = _starting_hass()
    day1, day2 = datetime(2026, 11, 1), datetime(2026, 11, 2)
    await process_and_insert(hass, _day_records(day1), SUPPLY, 0.0, "consumption")
    _, total, _ = await process_and_insert(
        hass, _day_records(day2), SUPPLY, 0.0, "consumption"
    )
    recorder.commit()
    assert recorder.rows[day2] == pytest.approx(25.0)
    assert total == pytest.approx(48.0)


@pytest.mark.asyncio
async def test_queued_row_wins_over_stale_committed_row(recorder):
    """A re-import's queued hour overrides the older committed value."""
    day1, day2 = datetime(2026, 11, 1), datetime(2026, 11, 2)
    recorder.rows[day2 - timedelta(hours=1)] = 5000.0  # stale, from an old run
    recorder.deferred = True
    hass = _starting_hass()
    await process_and_insert(hass, _day_records(day1), SUPPLY, 0.0, "consumption")
    await process_and_insert(hass, _day_records(day2), SUPPLY, 0.0, "consumption")
    recorder.commit()
    assert recorder.rows[day2] == pytest.approx(25.0)


@pytest.mark.asyncio
async def test_running_hass_waits_for_commit_and_clears_overlay(recorder):
    recorder.deferred = True
    hass = MagicMock()
    hass.is_running = True
    day = datetime(2026, 11, 1)
    await process_and_insert(hass, _day_records(day), SUPPLY, 0.0, "consumption")
    assert recorder.rows[day + timedelta(hours=23)] == pytest.approx(24.0)
    assert ext._PENDING.get(STAT_ID, {}) == {}


@pytest.mark.asyncio
async def test_batch_fetch_stops_after_failed_batch(monkeypatch):
    """A failed middle batch must not be skipped over: stop, save the last good."""
    good_dt = datetime(2025, 6, 1)
    api = AsyncMock(side_effect=[["rec"], RuntimeError("HTTP 500"), ["rec"]])
    pi = AsyncMock(return_value=(24, 24.0, good_dt))
    save_update, save_total = AsyncMock(), AsyncMock()
    monkeypatch.setattr(utils, "get_data_from_api", api)
    monkeypatch.setattr(utils, "process_and_insert", pi)
    monkeypatch.setattr(utils, "load_last_total", AsyncMock(return_value=0.0))
    monkeypatch.setattr(utils, "save_last_update", save_update)
    monkeypatch.setattr(utils, "save_last_total", save_total)
    await utils.batch_fetch(
        MagicMock(),
        "tok",
        SUPPLY,
        "tax",
        datetime(2024, 1, 1),
        datetime(2026, 11, 1),
        "CTX",
        ATTR_CONSUMPTION,
    )
    assert api.await_count == 2
    save_update.assert_awaited_once()
    assert save_update.await_args.args[2] == good_dt


@pytest.mark.asyncio
async def test_batch_fetch_stops_on_statistics_read_error(monkeypatch):
    api = AsyncMock(return_value=["rec"])
    pi = AsyncMock(
        side_effect=[
            (24, 24.0, datetime(2025, 6, 1)),
            ext.StatisticsReadError("locked"),
        ]
    )
    monkeypatch.setattr(utils, "get_data_from_api", api)
    monkeypatch.setattr(utils, "process_and_insert", pi)
    monkeypatch.setattr(utils, "load_last_total", AsyncMock(return_value=0.0))
    monkeypatch.setattr(utils, "save_last_update", AsyncMock())
    monkeypatch.setattr(utils, "save_last_total", AsyncMock())
    await utils.batch_fetch(
        MagicMock(),
        "tok",
        SUPPLY,
        "tax",
        datetime(2023, 1, 1),
        datetime(2026, 11, 1),
        "CTX",
        ATTR_CONSUMPTION,
    )
    assert api.await_count == 2


@pytest.mark.asyncio
async def test_fetch_since_statistics_read_error_saves_nothing(monkeypatch):
    monkeypatch.setattr(utils, "get_data_from_api", AsyncMock(return_value=["rec"]))
    monkeypatch.setattr(
        utils, "process_and_insert", AsyncMock(side_effect=ext.StatisticsReadError("x"))
    )
    monkeypatch.setattr(utils, "load_last_total", AsyncMock(return_value=0.0))
    save_update, save_total = AsyncMock(), AsyncMock()
    monkeypatch.setattr(utils, "save_last_update", save_update)
    monkeypatch.setattr(utils, "save_last_total", save_total)
    await utils.fetch_since(
        MagicMock(),
        "tok",
        SUPPLY,
        "tax",
        datetime(2026, 11, 1),
        datetime(2026, 11, 5),
        "CTX",
        ATTR_CONSUMPTION,
    )
    save_update.assert_not_awaited()
    save_total.assert_not_awaited()


@pytest.mark.asyncio
async def test_ensure_survives_db_error(monkeypatch, recorder, caplog):
    """A transient DB error must not fail the config entry; retry next start."""
    recorder.fail = True
    bf = AsyncMock()
    monkeypatch.setattr(utils, "batch_fetch", bf)
    with caplog.at_level(logging.ERROR, logger="deddie_metering"):
        await utils.async_ensure_external_statistics(
            MagicMock(), "tok", SUPPLY, "tax", datetime(2025, 4, 15), has_pv=False
        )
    bf.assert_not_awaited()
    assert "database is locked" in caplog.text
