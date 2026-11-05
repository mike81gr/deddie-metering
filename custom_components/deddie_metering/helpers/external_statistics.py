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
    "async_get_base_sum",
    "async_has_rows",
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


async def async_get_base_sum(hass, statistic_id: str, first_start: datetime) -> float:
    """Sum of the latest row before `first_start`; 0.0 when none exists.

    Looks at the previous hour first (the normal, contiguous case), then at the
    whole statistic, so a long gap never yields a wrong base of 0. Database
    errors propagate: the caller must not write when the base is unknown.
    """
    for window_start in (first_start - timedelta(hours=1), first_start - _FULL_HISTORY):
        rows = await _rows(hass, statistic_id, window_start, first_start)
        if rows:
            return float(rows[-1]["sum"])
    return 0.0


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
