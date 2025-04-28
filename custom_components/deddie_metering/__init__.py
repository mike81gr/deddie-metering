import logging
from datetime import datetime, timedelta
import homeassistant.util.dt as dt_util

from .const import DOMAIN, DEFAULT_INTERVAL_HOURS
from .coordinator import DeddieDataUpdateCoordinator
from .utils import run_initial_batches
from .storage import load_last_update, load_last_total, save_initial_jump_flag

_LOGGER = logging.getLogger("deddie_metering")


async def async_setup_entry(hass, entry):
    token = entry.options["token"]
    supply = entry.data["supplyNumber"]
    tax = entry.data["taxNumber"]
    interval = entry.options.get("interval_hours", DEFAULT_INTERVAL_HOURS)
    initial_time = dt_util.as_local(
        datetime.strptime(entry.options["initial_time"], "%d/%m/%Y")
    )

    # Φόρτωση persistent δεδομένων (last_update και last_total)
    last_update = await load_last_update(hass, supply)
    last_total = await load_last_total(hass, supply)

    # Εφαρμογή των συνθηκών:
    # 1) Αν (last_update is None and last_totalt is None)
    #   → fresh setup (run_initial_batches).
    # 2) Αν (last_update is not None or/and last_total is not None)
    #   -> fresh not first (restore persistent δεδομένα).
    if last_update is not None and last_total is not None:
        _LOGGER.info(
            "Παροχή %s: Βρέθηκαν αποθηκευμένα δεδομένα. "
            "Εκτελείται επαναφορά δεδομένων αισθητήρα "
            "και έναρξη περιοδικής ενημέρωσης.",
            supply,
        )
        skip_initial_refresh = False  # Fresh not first: δεν γίνεται το jump από 0.0
        await save_initial_jump_flag(hass, supply, True)
    else:
        _LOGGER.info(
            "Παροχή %s: Δεν βρέθηκαν αποθηκευμένα δεδομένα. "
            "Έναρξη αρχικής ενημέρωσης: Ξεκινά η διαδικασία "
            "batch processing...",
            supply,
        )
        await run_initial_batches(hass, token, supply, tax, initial_time)
        skip_initial_refresh = True  # Fresh install: jump από 0.0 -> total_kwh
        await save_initial_jump_flag(hass, supply, False)

    # Δημιουργία Coordinator
    update_interval = timedelta(hours=interval)
    coordinator = DeddieDataUpdateCoordinator(
        hass, token, supply, tax, update_interval, skip_initial_refresh
    )
    await coordinator.async_config_entry_first_refresh()

    hass.data.setdefault(DOMAIN, {})[entry.entry_id] = {"coordinator": coordinator}
    await hass.config_entries.async_forward_entry_setups(entry, ["sensor"])
    entry.async_on_unload(entry.add_update_listener(update_listener))
    return True


async def update_listener(hass, entry):
    supply = entry.data["supplyNumber"]
    _LOGGER.info(
        "Παροχή %s: Οι επιλογές ενημερώθηκαν. Επαναφόρτωση της ενσωμάτωσης.", supply
    )
    await hass.config_entries.async_reload(entry.entry_id)


async def async_unload_entry(hass, entry):
    unload_ok = await hass.config_entries.async_forward_entry_unload(entry, "sensor")
    entry_data = hass.data[DOMAIN].pop(entry.entry_id)
    if "coordinator" in entry_data:
        await entry_data["coordinator"].async_shutdown()
    _LOGGER.info(
        "Παροχή %s: Η καταχώρηση της ενσωμάτωσης "
        "απενεργοποιήθηκε ή διαμορφώθηκε εκ νέου.",
        entry.data["supplyNumber"],
    )
    return unload_ok


async def async_remove_entry(hass, entry):
    supply = entry.data["supplyNumber"]
    _LOGGER.info("Παροχή %s: Η καταχώρηση της ενσωμάτωσης διαγράφηκε.", supply)
