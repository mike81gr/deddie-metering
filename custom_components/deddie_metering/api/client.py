import logging
from datetime import timedelta
from homeassistant.util import dt as dt_util
from homeassistant.helpers.aiohttp_client import async_get_clientsession
import asyncio

from ..const import API_URL, ATTR_PRODUCTION, ATTR_INJECTION, ATTR_CONSUMPTION
from ..helpers.translate import translate

_LOGGER = logging.getLogger("deddie_metering")


async def get_data_from_api(hass, token, supply, tax, from_dt, to_dt, class_type):
    """
    Αλληλεπίδραση με το API ΔΕΔΔΗΕ: κλήσεις τακτικής άντλησης δεδομένων με έλεγχο
    λήξης κλειδιού token.
    Οι ημερομηνίες μετατρέπονται ώστε:
      - το toDate να έχει ώρα 20:00:00.000Z
      - το fromDate να έχει ώρα 20:00:00.000Z με αφαίρεση 1 ημέρας.
    Χρησιμοποιεί analysisType=2 για ωριαία άντληση δεδομένων.
    """
    headers = {
        "accept": "application/json;charset=utf-8",
        "token": token,
        "scope": "API",
        "Content-Type": "application/json;charset=utf-8",
    }
    to_date_str = f"{to_dt.date().isoformat()}T20:00:00.000Z"
    from_date_str = f"{(from_dt.date() - timedelta(days=1)).isoformat()}T20:00:00.000Z"
    payload = {
        "analysisType": 2,
        "classType": class_type,
        "confirmedDataFlag": False,
        "fromDate": from_date_str,
        "hourAnalysisFlag": False,
        "supplyNumber": supply,
        "taxNumber": tax,
        "toDate": to_date_str,
    }
    session = async_get_clientsession(hass)
    async with session.post(API_URL, json=payload, headers=headers) as response:
        resp_text = await response.text()
        if response.status == 401:
            _LOGGER.error(
                "Παροχή %s: Tο κλειδί token πρόσβασης έχει λήξει. "
                "Δεν λαμβάνονται νέα δεδομένα. Παρακαλώ ανανεώστε "
                "το στην ιστοσελίδα https://apps.deddie.gr/mdp/intro.html .",
                supply,
            )
            from homeassistant.components.persistent_notification import (
                async_create as pn_create,
            )

            res = pn_create(
                hass,
                translate("api.token_expired_message", hass.config.language),
                title=translate(
                    "api.token_expired_title", hass.config.language, supply=supply
                ),
                notification_id="deddie_token_expired",
            )
            if asyncio.iscoroutine(res):
                hass.async_create_task(res)
        elif response.status != 200:
            _LOGGER.error(
                "Παροχή %s: Σφάλμα επικοινωνίας με το ΔΕΔΔΗΕ API. "
                "Status: %s, Απόκριση: %s",
                supply,
                response.status,
                resp_text,
            )
            raise Exception(f"API call failed: status {response.status}")
        else:
            _LOGGER.debug(
                "Παροχή %s: Επιτυχής απάντηση (%s) από ΔΕΔΔΗΕ API.",
                supply,
                response.status,
            )
        data = await response.json()
        if "error" in data:
            raise Exception(data["error"])

        if class_type == ATTR_CONSUMPTION:
            label = "καταναλώσεων"
        elif class_type == ATTR_PRODUCTION:
            label = "παραγωγής ενέργειας"
        elif class_type == ATTR_INJECTION:
            label = "έγχυσης ενέργειας"
        if "curves" in data and not data["curves"]:
            _LOGGER.debug(
                "Παροχή %s: Δεν υπάρχουν διαθέσιμα νέα στοιχεία %s.",
                supply,
                label,
            )
        else:
            _LOGGER.debug(
                "ΔΕΔΔΗΕ (API): Λίστα %s παροχής %s: %s",
                label,
                supply,
                data.get("curves", []),
            )
        return data.get("curves", [])


async def validate_credentials(
    hass,
    token: str,
    supply: str,
    tax: str,
    class_type: str,
) -> list:
    """
    Εκτελεί μια dry-run κλήση στο API για έλεγχο των credentials:
    - Ορίζουμε ένα test interval: από 30 ημέρες πριν έως χθεσινή ημέρα.
    - Χρησιμοποιούμε analysisType=4 για μηνιαία ανάλυση (μικρή λίστα).
    - Αν η κλήση αποτύχει, ρίχνει Exception.
    """
    headers = {
        "accept": "application/json;charset=utf-8",
        "token": token,
        "scope": "API",
        "Content-Type": "application/json;charset=utf-8",
    }
    now = dt_util.now()
    from_dt = now - timedelta(days=30)
    to_dt = now - timedelta(days=1)
    from_date_str = f"{from_dt.date().isoformat()}T20:00:00.000Z"
    to_date_str = f"{to_dt.date().isoformat()}T20:00:00.000Z"
    payload = {
        "analysisType": 4,
        "classType": class_type,
        "confirmedDataFlag": False,
        "fromDate": from_date_str,
        "hourAnalysisFlag": False,
        "supplyNumber": supply,
        "taxNumber": tax,
        "toDate": to_date_str,
    }
    session = async_get_clientsession(hass)
    async with session.post(API_URL, json=payload, headers=headers) as response:
        if response.status == 401:
            raise Exception("Unauthorized access: invalid token or tax number.")
        elif response.status != 200:
            raise Exception(f"API call failed: status {response.status}")
        data = await response.json()
        if "error" in data:
            raise Exception(data["error"])
        return data.get("curves", [])
