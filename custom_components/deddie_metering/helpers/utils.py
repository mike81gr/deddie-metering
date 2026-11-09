import logging
from collections import defaultdict
from datetime import datetime, timedelta
import homeassistant.util.dt as dt_util
from .external_statistics import (
    StatisticData,
    async_add_external_statistics,
    async_get_base_sum,
    async_has_any_rows,
    async_track_queued,
    StatisticsReadError,
    async_warn_if_rows_after,
    external_metadata,
    external_statistic_id,
)
from .storage import (
    load_backfill_done,
    load_last_total,
    save_backfill_done,
    save_last_total,
    save_last_update,
)

from ..api.client import get_data_from_api
from ..const import ATTR_PRODUCTION, ATTR_INJECTION, ATTR_CONSUMPTION


_LOGGER = logging.getLogger("deddie_metering")


async def process_and_insert(
    hass,
    records: list,
    supply: str,
    total_consumption: float,
    type_key: str,
    warn_later: bool = True,
) -> tuple:
    """
    Επεξεργάζεται τα records του API και γράφει ωριαίες εγγραφές στο εξωτερικό
    statistic `deddie_metering:<type_key>_<supply>`. Δεκτές είναι μόνο πλήρεις
    ημέρες (24 έγκυρα records). Το άθροισμα ξεκινά από το sum της εγγραφής
    αμέσως πριν από την πρώτη εισερχόμενη ώρα (rebase), άρα η επανεισαγωγή
    δίνει ίδια αποτελέσματα. Αν δεν γίνει δεκτή καμία πλήρης ημέρα, το
    `total_consumption` επιστρέφεται αμετάβλητο. Αν αποτύχει η ανάγνωση της
    βάσης, δεν γράφεται τίποτα και εγείρεται StatisticsReadError. Με
    warn_later=False δεν καταγράφεται WARNING για μεταγενέστερες εγγραφές
    (ενδιάμεσα batches: το επόμενο batch θα τις ξαναγράψει).
    """
    skipped_count = 0
    overall_count = 0
    last_valid_meter_dt = None
    hourly: list = []

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
        # Τα records της ημέρας ταξινομούνται βάσει της meterDate.
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
                hourly.append((start_dt, float(rec["consumption"])))
            except Exception as e:
                _LOGGER.info(
                    "Παροχή %s: Παράβλεψη εγγραφής για την ημέρα %s λόγω σφάλματος: %s",
                    supply,
                    day,
                    e,
                )
                skipped_count += 1
        overall_count += len(day_records)

    if hourly:
        hourly.sort(key=lambda item: item[0])
        statistic_id = external_statistic_id(type_key, supply)
        try:
            running = await async_get_base_sum(hass, statistic_id, hourly[0][0])
        except Exception as err:
            _LOGGER.error(
                "Παροχή %s: Αδυναμία ανάγνωσης στατιστικών (%s). "
                "Δεν γράφτηκαν δεδομένα. Θα ξαναδοκιμαστεί στον επόμενο κύκλο.",
                supply,
                err,
            )
            raise StatisticsReadError(str(err)) from err
        stats = []
        queued = {}
        for start_dt, kwh in hourly:
            # Στρογγυλοποίηση σε 6 δεκαδικά: αφαιρεί τα υπολείμματα float
            # (π.χ. 723.4490000000003) χωρίς να αλλάζει πραγματικές τιμές,
            # αφού οι τιμές του ΔΕΔΔΗΕ έχουν λιγότερα δεκαδικά (συνήθως 3).
            running = round(running + kwh, 6)
            stats.append(StatisticData(start=start_dt, state=running, sum=running))
            queued[start_dt] = running
        async_add_external_statistics(hass, external_metadata(type_key, supply), stats)
        await async_track_queued(hass, statistic_id, queued)
        if warn_later:
            await async_warn_if_rows_after(hass, statistic_id, hourly[-1][0])
        total_consumption = running

    if skipped_count:
        _LOGGER.info(
            "Παροχή %s: Απορρίφθηκαν %d εγγραφές λόγω ελλιπών δεδομένων.",
            supply,
            skipped_count,
        )

    # Επιστρέφουμε overall_count, το νέο συνολικό consumption και
    # την τελευταία έγκυρη meterDate.
    return overall_count, total_consumption, last_valid_meter_dt


async def run_initial_batches(
    hass, token, supply, tax, initial_time, has_pv: bool, inc_con: bool
):
    """
    Αρχική λήψη για κατανάλωση, παραγωγή και έγχυση. Κάθε λήψη που
    ολοκληρώνεται χωρίς σφάλμα σημειώνεται ως ολοκληρωμένη πλήρης λήψη του
    εξωτερικού statistic, ώστε να μην επαναληφθεί κατά την εκκίνηση.
    """
    end_time = dt_util.now()

    # Batch-fetch για κατανάλωση
    if inc_con:
        if await batch_fetch(
            hass,
            token,
            supply,
            tax,
            initial_time,
            end_time,
            "Αρχική λήψη κατανάλωσης",
            ATTR_CONSUMPTION,
        ):
            await save_backfill_done(hass, supply, key=ATTR_CONSUMPTION)
    # Αν έχει PV, batch-fetch για παραγωγή/έγχυση
    if has_pv:
        if await batch_fetch(
            hass,
            token,
            supply,
            tax,
            initial_time,
            end_time,
            "Αρχική λήψη παραγωγής",
            ATTR_PRODUCTION,
        ):
            await save_backfill_done(hass, supply, key=ATTR_PRODUCTION)
        if await batch_fetch(
            hass,
            token,
            supply,
            tax,
            initial_time,
            end_time,
            "Αρχική λήψη έγχυσης",
            ATTR_INJECTION,
        ):
            await save_backfill_done(hass, supply, key=ATTR_INJECTION)


async def batch_fetch(
    hass,
    token,
    supply,
    tax,
    start_dt,
    end_dt,
    context_label: str,
    class_type: str = ATTR_CONSUMPTION,
):
    """
    Εκτελεί λήψη δεδομένων σε batches από start_dt έως end_dt, ώστε
    κάθε API call να καλύπτει έως 365 ημέρες (περιορισμός από API ΔΕΔΔΗΕ).
    Η διαδικασία αυτή:
      - Ενημερώνει τα συσσωρευμένα σύνολα (total_consumption/production/injection).
      - Την τελευταία έγκυρη ημερομηνία (last_update) μέσω της
        process_and_insert.
      - Αποθηκεύει τα αποτελέσματα στο persistent store (μέσω save_last_total
        και save_last_update).
      - Χρησιμοποιεί context_label για logging.
      - Καταγράφει WARNING για μεταγενέστερες εγγραφές μόνο στο τελευταίο batch
        (τις προηγούμενες τις ξαναγράφει το επόμενο batch).
    Επιστρέφει True όταν έτρεξαν όλα τα batches χωρίς σφάλμα (ακόμη κι αν ο
    ΔΕΔΔΗΕ δεν είχε εγγραφές) και False όταν η λήψη σταμάτησε σε σφάλμα.
    """
    _LOGGER.info(
        "Παροχή %s: %s από %s έως %s.",
        supply,
        context_label,
        start_dt.strftime("%d/%m/%Y"),
        end_dt.strftime("%d/%m/%Y"),
    )
    current_start = start_dt
    total_consumption = await load_last_total(hass, supply, key=class_type) or 0.0
    # Μεταβλητές για αποθήκευση της πρώτης και της τελευταίας έγκυρης
    # meterDate που επεξεργάστηκε επιτυχώς.
    first_meter_dt = None
    last_meter_dt = None
    total_count = 0
    if class_type == ATTR_CONSUMPTION:
        type_key = "consumption"
    elif class_type == ATTR_PRODUCTION:
        type_key = "production"
    elif class_type == ATTR_INJECTION:
        type_key = "injection"
    completed = True
    while current_start < end_dt:
        # Xρησιμοποιούμε timedelta(days=364) ώστε το effective διάστημα
        # (με το -1 day στο fromDate) να είναι 365 ημέρες.
        batch_end = min(current_start + timedelta(days=364), end_dt)
        try:
            records = await get_data_from_api(
                hass, token, supply, tax, current_start, batch_end, class_type
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
                    hass,
                    records,
                    supply,
                    total_consumption,
                    type_key,
                    warn_later=batch_end >= end_dt,
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
        except StatisticsReadError:
            # Ήδη καταγράφηκε. Σταματάμε ώστε το last_update να μείνει στο
            # τελευταίο επιτυχές batch και η επόμενη ενημέρωση να συνεχίσει από εκεί.
            completed = False
            break
        except Exception as err:
            _LOGGER.error(
                "Παροχή %s: <%s> Σφάλμα στο batch από %s έως %s: %s. "
                "Η λήψη σταματά εδώ και θα συνεχιστεί στην επόμενη ενημέρωση.",
                supply,
                context_label,
                current_start.strftime("%d/%m/%Y"),
                batch_end.strftime("%d/%m/%Y"),
                err,
            )
            completed = False
            break
        current_start = batch_end + timedelta(days=1)

    # Αν βρέθηκαν έγκυρες εγγραφές, ενημερώνουμε τα last_update
    # και last_total με τις τελευταίες έγκυρες τιμές.
    if last_meter_dt is not None:
        await save_last_update(hass, supply, last_meter_dt, key=class_type)
        await save_last_total(hass, supply, total_consumption, key=class_type)
        _LOGGER.info(
            "Παροχή %s: <%s> Αποθηκεύτηκαν επιτυχώς %d εγγραφές "
            "για το χρονικό διάστημα από %s έως %s.",
            supply,
            context_label,
            total_count,
            first_meter_dt.strftime("%d/%m/%Y") if first_meter_dt else "Unknown",
            (last_meter_dt - timedelta(days=1)).strftime("%d/%m/%Y"),
        )
    else:
        _LOGGER.info(
            "Παροχή %s: <%s> Σφάλμα κατά τη λήψη δεδομένων από ΔΕΔΔΗΕ (API). "
            "Ελέγξτε αν η τηλεμετρία σας είναι ενεργοποιημένη.",
            supply,
            context_label,
        )
    return completed


async def fetch_since(
    hass,
    token,
    supply,
    tax,
    from_dt,
    to_dt,
    context_label: str,
    class_type: str = ATTR_CONSUMPTION,
):
    """
    Single-fetch: κατεβάζει μία φορά δεδομένα από from_dt έως to_dt,
    κάνει process_and_insert και αποθηκεύει last_update/last_total.
    """
    # Μεταβλητή για αποθήκευση της πρώτης έγκυρης meterDate που επεξεργάστηκε επιτυχώς.
    first_meter_dt = None
    if class_type == ATTR_CONSUMPTION:
        type_key = "consumption"
    elif class_type == ATTR_PRODUCTION:
        type_key = "production"
    elif class_type == ATTR_INJECTION:
        type_key = "injection"
    try:
        records = await get_data_from_api(
            hass, token, supply, tax, from_dt, to_dt, class_type
        )
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
            total_consumption = (
                await load_last_total(hass, supply, key=class_type) or 0.0
            )
            count, total_consumption, last_valid = await process_and_insert(
                hass, records, supply, total_consumption, type_key
            )
            # Αν βρέθηκαν έγκυρες εγγραφές, ενημερώνουμε τα last_update
            # και last_total με τις τελευταίες έγκυρες τιμές.
            if count > 0:
                if last_valid:
                    await save_last_update(hass, supply, last_valid, key=class_type)
                    await save_last_total(
                        hass, supply, total_consumption, key=class_type
                    )
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
        else:
            _LOGGER.info(
                "Παροχή %s: <%s> Δεν βρέθηκαν νέες εγγραφές.", supply, context_label
            )
    except StatisticsReadError:
        # Ήδη καταγράφηκε· δεν αποθηκεύεται τίποτα,
        # ξαναδοκιμάζεται στην επόμενη ενημέρωση.
        return
    except Exception as err:
        _LOGGER.error(
            "Παροχή %s: <%s> Σφάλμα κατά τη λήψη δεδομένων από ΔΕΔΔΗΕ (API): %s",
            supply,
            context_label,
            err,
        )


async def async_ensure_external_statistics(
    hass, token, supply, tax, initial_time, has_pv: bool
):
    """
    Γεμίζει το εξωτερικό statistic από το initial_time μέχρι να ολοκληρωθεί
    μία πλήρης λήψη χωρίς σφάλμα (πρώτη εκκίνηση μετά την αναβάθμιση ή
    ημιτελής προηγούμενη λήψη), ή όταν το statistic δεν έχει καμία εγγραφή
    (π.χ. διαγράφηκε). Δεν εξαρτάται από το πότε ξεκινούν τα δεδομένα του
    ΔΕΔΔΗΕ, άρα δεν επαναλαμβάνεται σε κάθε εκκίνηση όταν το initial_time
    είναι παλαιότερο από τα δεδομένα. Η επανεισαγωγή είναι ασφαλής (rebase).
    """
    types = [(ATTR_CONSUMPTION, "consumption")]
    if has_pv:
        types += [(ATTR_PRODUCTION, "production"), (ATTR_INJECTION, "injection")]
    for class_type, type_key in types:
        statistic_id = external_statistic_id(type_key, supply)
        try:
            done = await load_backfill_done(hass, supply, key=class_type)
            if done and await async_has_any_rows(hass, statistic_id):
                continue
        except Exception as err:
            _LOGGER.error(
                "Παροχή %s: Αδυναμία ελέγχου του %s (%s). "
                "Ο έλεγχος θα επαναληφθεί στην επόμενη εκκίνηση.",
                supply,
                statistic_id,
                err,
            )
            continue
        _LOGGER.info(
            "Παροχή %s: Το %s δεν έχει ολοκληρωμένη λήψη από %s. "
            "Έναρξη πλήρους λήψης.",
            supply,
            statistic_id,
            initial_time.strftime("%d/%m/%Y"),
        )
        if await batch_fetch(
            hass,
            token,
            supply,
            tax,
            initial_time,
            dt_util.now(),
            "Μετάβαση σε εξωτερικά στατιστικά",
            class_type,
        ):
            await save_backfill_done(hass, supply, key=class_type)
