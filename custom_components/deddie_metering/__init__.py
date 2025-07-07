import logging
from datetime import datetime, timedelta
from homeassistant import config_entries
import homeassistant.util.dt as dt_util
from homeassistant.helpers import entity_registry as er
import asyncio

from .const import (
    DOMAIN,
    DEFAULT_INTERVAL_HOURS,
    CONF_HAS_PV,
    CONF_FRESH_SETUP,
    ATTR_PRODUCTION,
    ATTR_INJECTION,
    ATTR_CONSUMPTION,
)
from .coordinator import DeddieDataUpdateCoordinator
from .helpers.translate import translate
from .helpers.utils import run_initial_batches
from .helpers.storage import save_initial_jump_flag
from .api.client import validate_credentials

_LOGGER = logging.getLogger("deddie_metering")


async def async_migrate_entry(hass, entry: config_entries.ConfigEntry) -> bool:
    """Migration from version 1 → 2"""

    _LOGGER.debug(
        "Migrating configuration from version %s.%s",
        entry.version,
        entry.minor_version,
    )
    if entry.version == 1 and entry.minor_version < 2:
        # Επαναφορά πεδίωv από entry v1.0.0
        token: str = entry.options.get("token", "")
        supply: str = entry.data.get("supplyNumber", "")
        tax: str = entry.data.get("taxNumber", "")

        # Έλεγχος ύπαρξης φωτοβολταϊκών
        curves = await validate_credentials(
            hass,
            token,
            supply,
            tax,
            ATTR_PRODUCTION,
        )
        has_pv = bool(curves)

        # Προσθήκη has_pv & migrated_flag στα options
        new_options = {**entry.options}
        new_options[CONF_HAS_PV] = has_pv
        new_options["migrated_to_1_1"] = True

        # Ειδοποίηση αν υπάρχουν φωτοβολταϊκά
        from homeassistant.components.persistent_notification import (
            async_create as pn_create,
        )

        if has_pv:
            res = pn_create(
                hass,
                translate("init.pv_detected_message", hass.config.language),
                title=translate(
                    "init.pv_detected_title", hass.config.language, supply=supply
                ),
                notification_id="deddie_pv_detected",
            )
            if asyncio.iscoroutine(res):
                hass.async_create_task(res)

        # Ενημέρωση config entry
        hass.config_entries.async_update_entry(
            entry,
            options=new_options,
            minor_version=2,
            version=1,
        )

        # Migration v1.0.0 → v1.1.0: Ρύθμιση initial jump flags
        # 1) Αισθητήρας Κατανάλωσης: fresh not first
        await save_initial_jump_flag(hass, supply, True, key=ATTR_CONSUMPTION)

        # 2) Αισθητήρες Παραγωγής/Έγχυσης: fresh setup,
        #    μόνο εάν εντοπίστηκαν PV κατά το dry-run
        if has_pv:
            await save_initial_jump_flag(hass, supply, False, key=ATTR_PRODUCTION)
            await save_initial_jump_flag(hass, supply, False, key=ATTR_INJECTION)

        # Εύρεση consumption sensor v1.0.0
        registry = er.async_get(hass)
        supply = entry.data["supplyNumber"]
        old_unique_id = f"sensor.deddie_consumption_{supply}"
        ent_id = registry.async_get_entity_id(
            domain="sensor", platform=DOMAIN, unique_id=old_unique_id
        )

        # Ενημέρωση παλιού entry, με το νέο entity_id κατανάλωσης
        if ent_id:
            registry.async_update_entity(ent_id, new_unique_id=f"consumption_{supply}")
            _LOGGER.debug("Migration: updated old entity '%s'", ent_id)

        _LOGGER.debug(
            "Migration to configuration version %s.%s successful",
            entry.version,
            entry.minor_version,
        )
    return True


async def async_setup_entry(hass, entry):
    token = entry.options["token"]
    supply = entry.data["supplyNumber"]
    tax = entry.data["taxNumber"]
    interval = entry.options.get("interval_hours", DEFAULT_INTERVAL_HOURS)
    initial_time = dt_util.as_local(
        datetime.strptime(entry.options["initial_time"], "%d/%m/%Y")
    )
    has_pv = entry.options.get(CONF_HAS_PV, False)

    options = dict(entry.options)
    # Έλεγχος migration σε v1.1.0
    migrated = options.pop("migrated_to_1_1", False)

    # Έλεγχος πρώτης εγκατάστασης (fresh setup)
    fresh_setup = options.pop(CONF_FRESH_SETUP, False)

    # Αν κάποιο από τα δύο keys βρέθηκε κι αφαιρέθηκε, ενημερώνουμε το entry
    if migrated or fresh_setup:
        hass.config_entries.async_update_entry(entry, options=options)

    # Συνθήκες για επιλογή βήματος στον coordinator:
    # 1) Αν migrated=True (βήμα Α1):
    #    -> fresh not first για κατανάλωση(restore persistent δεδομένα)
    #    -> fresh setup για παραγωγή/έγχυση (run_initial_batches)
    # 2) Αν migrated=False:
    #    Αν fresh_setup  = True (βήμα Α2):
    #    -> fresh setup για όλους τους αισθητήρες (run_initial_batches)
    #    Αν fresh_setup  = False (βήμα C):
    #    -> fresh not first για όλους τους αισθητήρες (restore persistent δεδομένα)
    if migrated:
        _LOGGER.info(
            "Παροχή %s: <Έκδοση v1.1.0> " "Εκτελείται ενημέρωση διαθέσιμων αισθητήρων.",
            supply,
        )
        if has_pv:
            await run_initial_batches(
                hass,
                token,
                supply,
                tax,
                initial_time,
                has_pv,
                inc_con=False,
            )
        choose_step_flag = "A1"
    else:
        if fresh_setup:
            _LOGGER.info(
                "Παροχή %s: Έναρξη αρχικής ενημέρωσης. "
                "Ξεκινά η διαδικασία batch processing...",
                supply,
            )
            await run_initial_batches(
                hass,
                token,
                supply,
                tax,
                initial_time,
                has_pv,
                inc_con=True,
            )
            await save_initial_jump_flag(hass, supply, False, key=ATTR_CONSUMPTION)
            if has_pv:
                await save_initial_jump_flag(hass, supply, False, key=ATTR_PRODUCTION)
                await save_initial_jump_flag(hass, supply, False, key=ATTR_INJECTION)
            choose_step_flag = "A2"
        else:
            # Fresh not first
            _LOGGER.info(
                "Παροχή %s: Εκτελείται ενημέρωση διαθέσιμων αισθητήρων.",
                supply,
            )
            await save_initial_jump_flag(hass, supply, True, key=ATTR_CONSUMPTION)
            if has_pv:
                await save_initial_jump_flag(hass, supply, True, key=ATTR_PRODUCTION)
                await save_initial_jump_flag(hass, supply, True, key=ATTR_INJECTION)
            choose_step_flag = "C"

    # Δημιουργία Coordinator
    update_interval = timedelta(hours=interval)
    coordinator = DeddieDataUpdateCoordinator(
        hass,
        token,
        supply,
        tax,
        update_interval,
        choose_step_flag=choose_step_flag,
        has_pv=has_pv,
        entry=entry,
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
