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
        for s in stats:
            self.rows[s["start"]] = s["sum"]


@pytest.fixture
def recorder(monkeypatch):
    rec = FakeRecorder()
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
        count, total, last = await process_and_insert(
            MagicMock(),
            _day_records(datetime(2026, 11, 1)),
            SUPPLY,
            42.0,
            "consumption",
        )
    assert (count, total, last) == (0, 42.0, None)
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
