from datetime import timedelta
import homeassistant.util.dt as dt_util
from homeassistant.components.persistent_notification import async_create as pn_create
import asyncio

from ..helpers.translate import translate
from ..helpers.storage import load_last_update, save_last_update
from .client import validate_credentials
from ..const import (
    CONF_HAS_PV,
    ATTR_PRODUCTION,
    DEFAULT_PV_INTERVAL,
    ATTR_PV_DETECTION,
)


async def load_last_pv_check(hass, supply: str):
    # Φόρτωση timestamp του τελευταίου ελέγχου για ύπαρξη φωτοβολταϊκών
    return await load_last_update(hass, supply, ATTR_PV_DETECTION)


async def save_last_pv_check(hass, supply: str, timestamp) -> None:
    # Αποθήκευση timestamp του τελευταίου ελέγχου για ύπαρξη φωτοβολταϊκών
    await save_last_update(hass, supply, timestamp, ATTR_PV_DETECTION)


async def detect_pv(
    hass,
    entry,
    token: str,
    supply: str,
    tax: str,
    interval: timedelta = DEFAULT_PV_INTERVAL,
) -> bool:
    """
    Εκτέλεση ελέγχου PV-detection μία φορά ανά καθορισμένο χρόνο.
    Εάν εντοπιστεί παραγωγή Φ/Β, αποθηκεύει το 'has_pv' στο config options.
    """
    #
    has_pv = entry.options.get(CONF_HAS_PV, False)
    if has_pv:
        return True

    now = dt_util.utcnow()
    last_check = await load_last_pv_check(hass, supply)
    if last_check and (now - last_check) < interval:
        return False

    await save_last_pv_check(hass, supply, now)

    # Dry-run κλήση στο API για έλεγχο φωτοβολταϊκών
    try:
        curves = await validate_credentials(hass, token, supply, tax, ATTR_PRODUCTION)
        has_pv = bool(curves)

        if has_pv:
            # Ενημέρωση config entry
            hass.async_create_task(
                hass.config_entries.async_update_entry(
                    entry,
                    options={**entry.options, CONF_HAS_PV: True},
                )
            )
            # Ειδοποίηση αν υπάρχουν φωτοβολταϊκά
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
            return True
    except Exception:
        pass

    return False
