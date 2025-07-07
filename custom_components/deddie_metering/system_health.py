"""Provide info to system health for ΔΕΔΔΗΕ."""

import os
import json
from typing import Any, Dict
from homeassistant.core import HomeAssistant, callback
from homeassistant.components import system_health
from .helpers.storage import load_last_update
from .api.client import validate_credentials
from .const import DOMAIN, API_URL, CONF_HAS_PV


BASE = os.path.dirname(__file__)
with open(os.path.join(BASE, "manifest.json"), encoding="utf-8") as fp:
    _MANIFEST = json.load(fp)
INTEGRATION_VERSION = _MANIFEST.get("version", "–")


@callback
def async_register(
    hass: HomeAssistant, register: system_health.SystemHealthRegistration
) -> None:
    """Καταχώρηση callbacks για το System Health."""
    register.async_register_info(
        system_health_info,
        # το navigation path μέσα στο UI
        "/config/integrations",
    )


async def system_health_info(hass: HomeAssistant) -> Dict[str, Any]:
    """Επιστρέφει δυναμικά τα πεδία health για κάθε παροχή (config entry)."""
    info: Dict[str, Any] = {}
    # Έκδοση ενσωμάτωσης
    info["version"] = INTEGRATION_VERSION
    for entry in hass.config_entries.async_entries(DOMAIN):
        # Όνομα παροχής
        info["name"] = entry.title
        # Διαθεσιμότητα API
        info["api"] = system_health.async_check_can_reach_url(hass, API_URL)
        # Συχνότητα ενημέρωσης
        interval = entry.options.get("interval_hours", "–")
        info["frequency"] = f"{interval} ώρες"
        # Έγκυρο token
        token = entry.options.get("token", "-")
        supply = entry.data.get("supplyNumber", "-")
        tax = entry.data.get("taxNumber", "-")
        valid = bool(await validate_credentials(hass, token, supply, tax, "active"))
        info["token"] = valid
        # Υπάρχουν PV
        has_pv = entry.options.get(CONF_HAS_PV, False)
        info["has_pv"] = has_pv
        # Eνημερωμένο μέχρι
        last = await load_last_update(hass, supply, key="active")
        info["last_update"] = last.strftime("%d/%m/%Y %H:%M") if last else "–"
    return info
