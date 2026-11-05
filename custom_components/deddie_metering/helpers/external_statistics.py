"""Integration-owned external statistics: deddie_metering:<type_key>_<supply>.

Home Assistant never writes these statistics itself, so the `sum` baseline is
owned by this integration alone. Every import is rebased on the sum of the
row just before the incoming data, which makes imports idempotent and lets a
past range be re-imported to repair it.
"""

import logging
from datetime import datetime, timedelta

from homeassistant.components.recorder import get_instance
from homeassistant.components.recorder.statistics import (
    StatisticData,
    StatisticMeanType,
    StatisticMetaData,
    async_add_external_statistics,
    statistics_during_period,
)
from homeassistant.const import UnitOfEnergy

from ..const import DOMAIN

_LOGGER = logging.getLogger("deddie_metering")

# Rows this process has handed to the recorder but that may not be readable yet:
# HA queues imports on the recorder thread and, during startup, runs that queue
# only after HA has started. {statistic_id: {start: sum}}
_PENDING: dict[str, dict[datetime, float]] = {}


class StatisticsReadError(Exception):
    """The base sum could not be read, so nothing was written."""


_DISPLAY_NAMES = {
    "consumption": "Κατανάλωση ΔΕΔΔΗΕ {supply}",
    "production": "Παραγωγή ΔΕΔΔΗΕ {supply}",
    "injection": "Έγχυση ΔΕΔΔΗΕ {supply}",
}
# Look-back for "search the whole statistic" queries. Relative to first_start
# so the bound keeps first_start's tzinfo (aware in HA, naive in the stubbed tests).
_FULL_HISTORY = timedelta(days=36500)

__all__ = [
    "StatisticData",
    "async_add_external_statistics",
    "StatisticsReadError",
    "async_get_base_sum",
    "async_has_rows",
    "async_track_queued",
    "async_warn_if_rows_after",
    "external_metadata",
    "external_statistic_id",
]


def external_statistic_id(type_key: str, supply: str) -> str:
    """Return the external statistic id for a measurement type and supply."""
    return f"{DOMAIN}:{type_key}_{supply}"


def external_metadata(type_key: str, supply: str) -> StatisticMetaData:
    """Return the metadata of the integration-owned external statistic."""
    return StatisticMetaData(
        source=DOMAIN,
        statistic_id=external_statistic_id(type_key, supply),
        name=_DISPLAY_NAMES[type_key].format(supply=supply),
        unit_of_measurement=UnitOfEnergy.KILO_WATT_HOUR,
        has_sum=True,
        mean_type=StatisticMeanType.NONE,
        unit_class="energy",
    )


async def _rows(hass, statistic_id: str, start: datetime, end: datetime | None):
    """Hourly rows of one statistic in [start, end); end=None means open-ended."""
    result = await get_instance(hass).async_add_executor_job(
        statistics_during_period,
        hass,
        start,
        end,
        {statistic_id},
        "hour",
        None,
        {"sum"},
    )
    return result.get(statistic_id) or []


def _ts(start) -> float:
    """Epoch seconds of a row start (the recorder returns floats, we keep datetimes)."""
    return float(start) if isinstance(start, (int, float)) else start.timestamp()


async def async_get_base_sum(hass, statistic_id: str, first_start: datetime) -> float:
    """Sum of the latest row before `first_start`; 0.0 when none exists.

    Considers both committed rows (previous hour first, then the whole
    statistic, so a long gap never yields a wrong base of 0) and rows this
    process has queued but the recorder may not have written yet. A queued row
    wins over a committed one at the same or an earlier hour, because it is
    newer. Database errors propagate: the caller must not write when the base
    is unknown.
    """
    pending = _PENDING.get(statistic_id, {})
    queued_starts = [start for start in pending if start < first_start]
    queued = max(queued_starts) if queued_starts else None
    committed = None
    for window_start in (first_start - timedelta(hours=1), first_start - _FULL_HISTORY):
        rows = await _rows(hass, statistic_id, window_start, first_start)
        if rows:
            committed = rows[-1]
            break
    if queued is not None and (
        committed is None or _ts(queued) >= _ts(committed["start"])
    ):
        return pending[queued]
    return float(committed["sum"]) if committed is not None else 0.0


async def async_track_queued(hass, statistic_id: str, rows: dict) -> None:
    """Remember rows just handed to the recorder until they are readable.

    Once HA is running, wait for the recorder to write them and forget them.
    During startup the recorder runs its queue only after HA has started, so
    waiting would stall startup; the rows stay in memory and
    `async_get_base_sum` uses them instead.
    """
    _PENDING.setdefault(statistic_id, {}).update(rows)
    if hass.is_running:
        await get_instance(hass).async_block_till_done()
        _PENDING.pop(statistic_id, None)


async def async_has_rows(
    hass, statistic_id: str, start: datetime, end: datetime
) -> bool:
    """True when the statistic has at least one hourly row in [start, end)."""
    return bool(await _rows(hass, statistic_id, start, end))


async def async_warn_if_rows_after(hass, statistic_id: str, after: datetime) -> None:
    """Log a WARNING when rows exist later than `after`: their sums are now stale."""
    later = await _rows(hass, statistic_id, after + timedelta(hours=1), None)
    if later:
        _LOGGER.warning(
            "%s: υπάρχουν %d μεταγενέστερες εγγραφές μετά από %s με πιθανώς "
            "παρωχημένο άθροισμα. Επανεισάγετε έως τα τελευταία δεδομένα.",
            statistic_id,
            len(later),
            after,
        )
