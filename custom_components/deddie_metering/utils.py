import logging
from collections import defaultdict
from datetime import datetime, timedelta
import homeassistant.util.dt as dt_util
from homeassistant.components.recorder.statistics import (
    async_import_statistics,
    StatisticData,
    StatisticMetaData,
)
from homeassistant.const import UnitOfEnergy
from .storage import (
    load_last_total,
    save_last_total,
    save_last_update,
)
from .api import get_data_from_api
from .statistics_helper import run_update_future_statistics

_LOGGER = logging.getLogger("deddie_metering")


async def process_and_insert(
    hass, records: list, supply: str, total_consumption: float
) -> tuple:
    """
    Επεξεργάζεται τα records που λήφθηκαν από το API και εισάγει στατιστικές
    εγγραφές, συνενώνοντας (merging) τις πλήρεις ημέρες (δηλαδή, ημέρες με 24
    έγκυρα records που περιέχουν το πεδίο 'consumption'). Διενεργεί τον έλεγχο
    ότι, για κάθε ημέρα, υπάρχουν 24 έγκυρες εγγραφές. Αν κάποια ημέρα είναι
    ελλιπής, απορρίπτεται ολόκληρη. Δημιουργεί μια ενιαία λίστα αντικειμένων
    StatisticData και καλεί async_import_statistics μία φορά.
    """
    skipped_count = 0
    overall_count = 0
    last_valid_meter_dt = None
    all_stats = []

    # Ομαδοποίηση των records, λαμβάνοντας υπόψη το offset -1 ώρα για το start_dt.
    records_by_day = defaultdict(list)
    for rec in records:
        try:
            meter_dt = datetime.strptime(rec["meterDate"], "%d/%m/%Y %H:%M")
            day_key = (meter_dt - timedelta(hours=1)).date()
            records_by_day[day_key].append(rec)
        except Exception as e:
            _LOGGER.info("Παροχή %s: Αδυναμία ομαδοποίησης record: %s", supply, e)
            skipped_count += 1

    # Επεξεργασία των ομάδων (ημέρες)
    for day, day_records in records_by_day.items():
        # Έλεγχος ότι υπάρχουν ακριβώς 24 εγγραφές και ότι κάθε
        # εγγραφή έχει το πεδίο "consumption" με έγκυρη τιμή.
        if len(day_records) != 24 or any(
            "consumption" not in r or not r["consumption"] for r in day_records
        ):
            _LOGGER.debug(
                "Παροχή %s: Ημέρα %s απορρίπτεται λόγω ελλιπών ή μη έγκυρων εγγραφών.",
                supply,
                day.strftime("%d/%m/%Y"),
            )
            skipped_count += len(day_records)
            continue

        # Επεξεργασία της πλήρους ημέρας:
        # Τα records της ημέρας ταξινομούνται (αν χρειάζεται) βάσει της meterDate.
        day_records.sort(
            key=lambda r: datetime.strptime(r["meterDate"], "%d/%m/%Y %H:%M")
        )
        for rec in day_records:
            try:
                meter_dt = datetime.strptime(rec["meterDate"], "%d/%m/%Y %H:%M")
                meter_dt = dt_util.as_local(meter_dt)
                # Ενημέρωση της τελευταίας έγκυρης meterDate.
                last_valid_meter_dt = meter_dt
                # Υπολογισμός του start_dt με offset -1 ώρα.
                start_dt = meter_dt - timedelta(hours=1)
                consumption = float(rec["consumption"])
                total_consumption += consumption
                stat = StatisticData(
                    start=start_dt, state=total_consumption, sum=total_consumption
                )
                all_stats.append(stat)
            except Exception as e:
                _LOGGER.info(
                    "Παροχή %s: Παράβλεψη εγγραφής για την ημέρα %s λόγω σφάλματος: %s",
                    supply,
                    day,
                    e,
                )
                skipped_count += 1
        overall_count += len(day_records)

    if all_stats:
        statistic_id = f"sensor.deddie_consumption_{supply}"
        metadata = StatisticMetaData(
            statistic_id=statistic_id,
            source="recorder",
            name=f"Κατανάλωση ΔΕΔΔΗΕ {supply}",
            unit_of_measurement=UnitOfEnergy.KILO_WATT_HOUR,
            has_mean=False,
            has_sum=True,
        )
        # Εισαγωγή/ενημέρωση των στατιστικών εγγραφών μέσω async_import_statistics
        await hass.async_add_executor_job(
            async_import_statistics, hass, metadata, all_stats
        )

    if skipped_count:
        _LOGGER.info(
            "Παροχή %s: Απορρίφθηκαν %d εγγραφές λόγω ελλιπών δεδομένων.",
            supply,
            skipped_count,
        )

    # Επιστρέφουμε overall_count, το νέο συνολικό consumption και
    # την τελευταία έγκυρη meterDate.
    return overall_count, total_consumption, last_valid_meter_dt


async def run_initial_batches(hass, token, supply, tax, initial_time):
    """
    Αρχική λήψη χρησιμοποιώντας κοινή συνάρτηση batch
    """
    end_time = dt_util.now()
    await batch_fetch(
        hass, token, supply, tax, initial_time, end_time, "Αρχική λήψη", 60
    )


async def batch_fetch(
    hass, token, supply, tax, start_dt, end_dt, context_label: str, stats_delay: int
):
    """
    Εκτελεί λήψη δεδομένων σε batches από start_dt έως end_dt,
    χρησιμοποιώντας batching ώστε κάθε API call να καλύπτει έως 365 ημέρες
    (περιορισμός από API ΔΕΔΔΗΕ).
    Η διαδικασία αυτή:
      - Ενημερώνει το συσσωρευμένο σύνολο κατανάλωσης (total_consumption).
      - Την τελευταία έγκυρη ημερομηνία (last_update) μέσω της
        process_and_insert.
      - Αποθηκεύει τα αποτελέσματα στο persistent store (μέσω save_last_total
        και save_last_update).
      - Χρησιμοποιεί context_label για logging και stats_delay για deferred
        future stats update
    """
    _LOGGER.info(
        "Παροχή %s: %s από %s έως %s.",
        supply,
        context_label,
        start_dt.strftime("%d/%m/%Y"),
        end_dt.strftime("%d/%m/%Y"),
    )
    current_start = start_dt
    total_consumption = await load_last_total(hass, supply) or 0.0
    # Μεταβλητές για αποθήκευση της πρώτης και της τελευταίας έγκυρης
    # meterDate που επεξεργάστηκε επιτυχώς.
    first_meter_dt = None
    last_meter_dt = None
    total_count = 0

    while current_start < end_dt:
        # Xρησιμοποιούμε timedelta(days=364) ώστε το effective διάστημα
        # (με το -1 day στο fromDate) να είναι 365 ημέρες.
        batch_end = min(current_start + timedelta(days=364), end_dt)
        try:
            records = await get_data_from_api(
                hass, token, supply, tax, current_start, batch_end
            )
            if records:
                if first_meter_dt is None:
                    try:
                        first_meter_dt = dt_util.as_local(
                            datetime.strptime(records[0]["meterDate"], "%d/%m/%Y %H:%M")
                        )
                        _LOGGER.info(
                            "Παροχή %s: <%s> Βρέθηκαν εγγραφές στο batch "
                            "από %s έως %s.",
                            supply,
                            context_label,
                            current_start.strftime("%d/%m/%Y"),
                            batch_end.strftime("%d/%m/%Y"),
                        )
                    except Exception as e:
                        _LOGGER.info(
                            "Παροχή %s: <%s> Αδυναμία επεξεργασίας της "
                            "πρώτης meterDate: %s.",
                            supply,
                            context_label,
                            e,
                        )
                # Χρησιμοποιούμε το αποτέλεσμα της process_and_insert για να
                # πάρουμε την τελευταία έγκυρη meterDate
                count, total_consumption, last_valid = await process_and_insert(
                    hass, records, supply, total_consumption
                )
                total_count += count
                if last_valid:
                    last_meter_dt = last_valid
            else:
                _LOGGER.info(
                    "Παροχή %s: <%s> Δεν βρέθηκαν εγγραφές από %s έως %s.",
                    supply,
                    context_label,
                    current_start.strftime("%d/%m/%Y"),
                    batch_end.strftime("%d/%m/%Y"),
                )
        except Exception as err:
            _LOGGER.error(
                "Παροχή %s: <%s> Σφάλμα στο batch από %s έως %s: %s.",
                supply,
                context_label,
                current_start.strftime("%d/%m/%Y"),
                batch_end.strftime("%d/%m/%Y"),
                err,
            )
        current_start = batch_end + timedelta(days=1)

    # Αν βρέθηκαν έγκυρες εγγραφές, ενημερώνουμε τα last_update
    # και last_total με τις τελευταίες έγκυρες τιμές.
    if last_meter_dt is not None:
        await save_last_update(hass, supply, last_meter_dt)
        await save_last_total(hass, supply, total_consumption)
        _LOGGER.info(
            "Παροχή %s: <%s> Αποθηκεύτηκαν επιτυχώς %d εγγραφές "
            "για το χρονικό διάστημα από %s έως %s.",
            supply,
            context_label,
            total_count,
            first_meter_dt.strftime("%d/%m/%Y") if first_meter_dt else "Unknown",
            (last_meter_dt - timedelta(days=1)).strftime("%d/%m/%Y"),
        )

        # Κλήση run_update_future_statistics αν υπάρχουν ασυνεπείς εγγραφές
        # στο statistics με καθυστέρηση 60΄΄ για ασφαλή πρόσβαση στη βάση δεδομένων
        if total_count > 0:
            # Χρησιμοποιούμε το start_dt της τελευταίας εγγραφής,
            # δηλαδή, last_meter_dt - 1 ώρα
            last_start_dt = last_meter_dt - timedelta(hours=1)
            hass.loop.call_later(
                stats_delay,
                lambda: hass.async_create_task(
                    run_update_future_statistics(
                        hass, supply, last_start_dt, total_consumption
                    )
                ),
            )
    else:
        _LOGGER.info(
            "Παροχή %s: <%s> Σφάλμα κατά τη λήψη δεδομένων από ΔΕΔΔΗΕ (API). "
            "Ελέγξτε αν η τηλεμετρία σας είναι ενεργοποιημένη.",
            supply,
            context_label,
        )


async def fetch_since(
    hass, token, supply, tax, from_dt, to_dt, context_label: str, stats_delay: int
):
    """
    Single-fetch helper: κατεβάζει μία φορά δεδομένα από from_dt έως to_dt,
    κάνει process_and_insert, αποθηκεύει last_update/last_total και
    προγραμματίζει future stats.
    """
    # Μεταβλητή για αποθήκευση της πρώτης έγκυρης meterDate που επεξεργάστηκε επιτυχώς.
    first_meter_dt = None
    try:
        records = await get_data_from_api(hass, token, supply, tax, from_dt, to_dt)
        if records:
            if first_meter_dt is None:
                try:
                    first_meter_dt = dt_util.as_local(
                        datetime.strptime(records[0]["meterDate"], "%d/%m/%Y %H:%M")
                    )
                    _LOGGER.info(
                        "Παροχή %s: <%s> Βρέθηκαν εγγραφές από %s έως %s.",
                        supply,
                        context_label,
                        from_dt.strftime("%d/%m/%Y"),
                        to_dt.strftime("%d/%m/%Y"),
                    )
                except Exception as e:
                    _LOGGER.info(
                        "Παροχή %s: <%s> Αδυναμία επεξεργασίας της πρώτης "
                        "meterDate: %s.",
                        supply,
                        context_label,
                        e,
                    )
            # Ξεκινάμε από την αποθηκευμένη συνολική κατανάλωση
            total_consumption = await load_last_total(hass, supply) or 0.0
            count, total_consumption, last_valid = await process_and_insert(
                hass, records, supply, total_consumption
            )
            # Αν βρέθηκαν έγκυρες εγγραφές, ενημερώνουμε τα last_update
            # και last_total με τις τελευταίες έγκυρες τιμές.
            if last_valid:
                await save_last_update(hass, supply, last_valid)
                await save_last_total(hass, supply, total_consumption)
                _LOGGER.info(
                    "Παροχή %s: <%s> Αποθηκεύτηκαν επιτυχώς %d εγγραφές "
                    "για το χρονικό διάστημα από %s έως %s.",
                    supply,
                    context_label,
                    count,
                    (
                        first_meter_dt.strftime("%d/%m/%Y")
                        if first_meter_dt
                        else "Unknown"
                    ),
                    (last_valid - timedelta(days=1)).strftime("%d/%m/%Y"),
                )

                # Κλήση run_update_future_statistics αν υπάρχουν ασυνεπείς
                # εγγραφές στο statistics με καθυστέρηση 60΄΄ για ασφαλή πρόσβαση
                # στη βάση δεδομένων
                if count > 0:
                    # Χρησιμοποιούμε το start_dt της τελευταίας εγγραφής,
                    # δηλαδή, last_meter_dt - 1 ώρα
                    last_start_dt = last_valid - timedelta(hours=1)
                    hass.loop.call_later(
                        stats_delay,
                        lambda: hass.async_create_task(
                            run_update_future_statistics(
                                hass, supply, last_start_dt, total_consumption
                            )
                        ),
                    )
        else:
            _LOGGER.info(
                "Παροχή %s: <%s> Δεν βρέθηκαν νέες εγγραφές.", supply, context_label
            )
    except Exception:
        _LOGGER.error(
            "Παροχή %s: <%s> Σφάλμα κατά τη λήψη δεδομένων από ΔΕΔΔΗΕ (API).",
            supply,
            context_label,
        )
