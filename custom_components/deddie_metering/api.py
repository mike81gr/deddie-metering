import logging
from datetime import timedelta
from homeassistant.util import dt as dt_util
from homeassistant.helpers.aiohttp_client import async_get_clientsession
import asyncio

from .const import API_URL
from .helpers.translate import translate

_LOGGER = logging.getLogger("deddie_metering")


async def get_data_from_api(hass, token, supply, tax, from_dt, to_dt):
    """
    Αλληλεπίδραση με το API ΔΕΔΔΗΕ: κλήσεις τακτικής άντλησης δεδομένων
    και dry‑run επαλήθευσης credentials.

    Οι ημερομηνίες μετατρέπονται ώστε:
      - το toDate να έχει ώρα 20:00:00.000Z
      - το fromDate να έχει ώρα 20:00:00.000Z με αφαίρεση 1 ημέρας.

    Χρησιμοποιεί analysisType=2 για κανονική άντληση δεδομένων.
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
        "classType": "active",
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
            # Δημιουργία persistent notification για το σφάλμα token με
            # χρήση custom _translate_init
            from homeassistant.components.persistent_notification import (
                async_create as pn_create,
            )

            res = pn_create(
                hass,
                translate("api.token_expired_message", hass.config.language),
                title=translate(
                    "api.token_expired_title", hass.config.language, supply=supply
                ),
                notification_id="deddie_metering_token_expired",
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
        if "curves" in data and not data["curves"]:
            _LOGGER.debug(
                "Παροχή %s: Δεν υπάρχουν διαθέσιμα νέα στοιχεία καταναλώσεων.", supply
            )
        else:
            _LOGGER.debug(
                "ΔΕΔΔΗΕ (API): Λίστα καταναλώσεων παροχής %s: %s",
                supply,
                data.get("curves", []),
            )
        return data.get("curves", [])


async def validate_credentials(hass, token: str, supply: str, tax: str) -> list:
    """
    Εκτελεί μια dry-run κλήση στο API για έλεγχο των credentials:
    Διαδικασία:
    - Ορίζουμε ένα test interval: από 16 ημέρες πριν έως 15 ημέρες πριν
    - Χρησιμοποιούμε analysisType=3 για dry-run και επιστρέφει τα δεδομένα (curves).
    - Αν η κλήση αποτύχει, ρίχνει Exception.
    """
    headers = {
        "accept": "application/json;charset=utf-8",
        "token": token,
        "scope": "API",
        "Content-Type": "application/json;charset=utf-8",
    }
    now = dt_util.now()
    from_dt = now - timedelta(days=16)
    to_dt = now - timedelta(days=15)
    from_date_str = f"{from_dt.date().isoformat()}T20:00:00.000Z"
    to_date_str = f"{to_dt.date().isoformat()}T20:00:00.000Z"
    payload = {
        "analysisType": 3,  # Χρησιμοποιείται για dry-run επαλήθευση
        "classType": "active",
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
