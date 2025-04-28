import logging
from datetime import datetime
import homeassistant.util.dt as dt_util
from homeassistant.components.recorder import get_instance
from homeassistant.components.recorder.statistics import (
    async_import_statistics,
    StatisticData,
    StatisticMetaData,
)
from homeassistant.const import UnitOfEnergy
from sqlalchemy import text

_LOGGER = logging.getLogger("deddie_metering")


async def _connect(instance, engine):
    """Τυλίγει το engine.connect() μέσα σε async_add_executor_job."""
    return await instance.async_add_executor_job(engine.connect)


async def update_future_statistics(
    hass, supply, last_meter_dt: datetime, last_total: float
) -> int:
    """
    Εντοπίζει και ενημερώνει τις "ασυνεπείς" εγγραφές στον πίνακα statistics
    που ανήκουν στον αισθητήρα (βάσει του metadata_id από τον πίνακα
    statistics_meta), για τις οποίες το start_ts είναι μεγαλύτερο από το timestamp
    του last_meter_dt. Ενημερώνει τα πεδία state και sum ώστε να έχουν την τιμή
    last_total και επιστρέφει τον αριθμό των ενημερωμένων εγγραφών για να υπάρχει
    σωστή απεικόνιση στο Energy dashboard του HA (διορθώνει τις αρνητικές τιμές που
    προκαλούνταν μετά από νέα ενημέρωση API).
    """
    statistic_id = f"sensor.deddie_consumption_{supply}"

    # Εσωτερική async συνάρτηση για λήψη των timestamps
    async def get_future_timestamps() -> list:
        instance = get_instance(hass)
        engine = instance.engine
        try:
            conn = await _connect(instance, engine)
        except Exception as e:
            _LOGGER.error(
                "Παροχή %s: Σφάλμα σύνδεσης στη βάση HA "
                "για έλεγχο δεδομένων του αισθητήρα: %s",
                supply,
                e,
            )
            return []

        try:
            stmt = text(
                "SELECT start_ts FROM statistics WHERE metadata_id IN "
                "(SELECT id FROM statistics_meta WHERE statistic_id = :statistic_id) "
                "AND start_ts > :last_ts"
            )
            result = conn.execute(
                stmt,
                {"statistic_id": statistic_id, "last_ts": last_meter_dt.timestamp()},
            )
            timestamps = [row[0] for row in result.fetchall()]
        finally:
            try:
                if not conn.closed:
                    await instance.async_add_executor_job(conn.close)
            except Exception as e:
                _LOGGER.warning(
                    "Παροχή %s: Σφάλμα στο κλείσιμο της σύνδεσης "
                    "με τη βάση δεδομένων HA: %s",
                    supply,
                    e,
                )
        return timestamps

    future_timestamps = await get_future_timestamps()
    if not future_timestamps:
        _LOGGER.info(
            "Παροχή %s: Δεν βρέθηκαν ασυνεπείς εγγραφές του αισθητήρα "
            "στη βάση δεδομένων HA.",
            supply,
        )
        return 0

    future_starts = [
        dt_util.as_local(datetime.fromtimestamp(ts)) for ts in future_timestamps
    ]
    statistic_data_list = [
        StatisticData(start=start, state=last_total, sum=last_total)
        for start in future_starts
    ]
    metadata = StatisticMetaData(
        statistic_id=statistic_id,
        source="recorder",
        name=f"Κατανάλωση ΔΕΔΔΗΕ {supply}",
        unit_of_measurement=UnitOfEnergy.KILO_WATT_HOUR,
        has_mean=False,
        has_sum=True,
    )
    # Επειδή η async_import_statistics είναι blocking,
    # καλείται μέσα σε async_add_executor_job.
    await hass.async_add_executor_job(
        async_import_statistics, hass, metadata, statistic_data_list
    )
    return len(statistic_data_list)


async def run_update_future_statistics(hass, supply, last_start_dt, total_consumption):
    updated_count = await update_future_statistics(
        hass, supply, last_start_dt, total_consumption
    )
    if updated_count > 0:
        _LOGGER.info(
            "Παροχή %s: Ενημερώθηκαν στη βάση δεδομένων HA %d ασυνεπείς εγγραφές "
            "του αισθητήρα με νέα συνολική κατανάλωση=%.2f KWh.",
            supply,
            updated_count,
            total_consumption,
        )


async def purge_flat_states(
    hass, entity_id: str, supply: str, keep_days: int = 0
) -> None:
    """
    Ασύγχρονη συνάρτηση που χρησιμοποιεί την υπηρεσία recorder.purge_entities.
    Με αυτή τη λειτουργία, μόλις πραγματοποιηθεί μια επιτυχημένη ενημέρωση από
    το API και ενημερωθούν τα long-term δεδομένα, καθαρίζονται τα "flat"
    short-term states που έχουν δημιουργηθεί στο διάστημα μεταξύ των επιτυχημένων
    ενημερώσεων ώστε να υπάρχει σωστή απεικόνιση στο ιστορικό UI του αισθητήρα
    (διορθώνει τις μειωμένες "flat" τιμές που δημιουργούνται στο ιστορικό UI).
    """
    data = {
        "entity_id": [entity_id],
        "keep_days": keep_days,
    }
    try:
        await hass.services.async_call(
            "recorder",
            "purge_entities",
            service_data=data,
            blocking=True,
        )
        _LOGGER.info(
            "Παροχή %s: Επιτυχής διαγραφή των flat state εγγραφών του αισθητήρα.",
            supply,
        )
    except Exception as err:
        _LOGGER.error(
            "Παροχή %s: Σφάλμα κατά τη διαγραφή των flat state εγγραφών "
            "του αισθητήρα: %s",
            supply,
            err,
        )
