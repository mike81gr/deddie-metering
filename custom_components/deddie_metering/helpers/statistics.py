import logging
from datetime import datetime
import homeassistant.util.dt as dt_util
from homeassistant.components.recorder import get_instance
from homeassistant.components.recorder.statistics import (
    async_import_statistics,
    StatisticData,
    StatisticMetaData,
    StatisticMeanType,
)
from homeassistant.const import UnitOfEnergy
from sqlalchemy import text

from homeassistant.components.sensor import SensorDeviceClass

_LOGGER = logging.getLogger("deddie_metering")


async def _connect(instance, engine):
    """Τυλίγει το engine.connect() μέσα σε async_add_executor_job."""
    return await instance.async_add_executor_job(engine.connect)


async def update_future_statistics(
    hass,
    supply: str,
    last_meter_dt: datetime,
    last_total: float,
    type_key: str,
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
    statistic_id = f"sensor.deddie_{type_key}_{supply}"

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
    # Δυναμικό όνομα βάσει type_key
    if type_key == "consumption":
        display_name = f"Κατανάλωση ΔΕΔΔΗΕ {supply}"
    elif type_key == "production":
        display_name = f"Παραγωγή ΔΕΔΔΗΕ {supply}"
    elif type_key == "injection":
        display_name = f"Έγχυση ΔΕΔΔΗΕ {supply}"

    metadata = StatisticMetaData(
        statistic_id=statistic_id,
        source="recorder",
        name=display_name,
        unit_of_measurement=UnitOfEnergy.KILO_WATT_HOUR,
        has_mean=False,
        has_sum=True,
        mean_type=StatisticMeanType.NONE,
        unit_class=SensorDeviceClass.ENERGY
    )
    # Καλείται η async_import_statistics μέσα σε async_add_executor_job
    await hass.async_add_executor_job(
        async_import_statistics, hass, metadata, statistic_data_list
    )
    return len(statistic_data_list)


async def run_update_future_statistics(
    hass,
    supply: str,
    last_start_dt: datetime,
    total_consumption: float,
    type_key: str,
) -> None:
    updated_count = await update_future_statistics(
        hass, supply, last_start_dt, total_consumption, type_key
    )
    if updated_count > 0:
        if type_key == "consumption":
            label = "κατανάλωσης"
        elif type_key == "production":
            label = "παραγωγής ενέργειας"
        elif type_key == "injection":
            label = "έγχυσης ενέργειας"
        _LOGGER.info(
            "Παροχή %s: Ενημερώθηκαν στη βάση δεδομένων HA %d ασυνεπείς εγγραφές "
            "του αισθητήρα %s με νέα συνολική κατανάλωση=%.2f KWh.",
            supply,
            updated_count,
            label,
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
            "Παροχή %s: Επιτυχής διαγραφή των flat state εγγραφών του αισθητήρα %s.",
            supply,
            entity_id,
        )
    except Exception as err:
        _LOGGER.error(
            "Παροχή %s: Σφάλμα κατά τη διαγραφή των flat state εγγραφών "
            "του αισθητήρα %s: %s",
            supply,
            entity_id,
            err,
        )
