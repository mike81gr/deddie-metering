from datetime import datetime, timedelta
import voluptuous as vol
import re
from typing import Any
from homeassistant import config_entries
import homeassistant.util.dt as dt_util
import logging
import asyncio

from .const import DOMAIN, DEFAULT_INTERVAL_HOURS, DEFAULT_INITIAL_DAYS
from .helpers.translate import translate
from .api import validate_credentials

_LOGGER = logging.getLogger("deddie_metering")

# Ο αρχικός ορισμός schema, με interval_hours μεταξύ 1 και 24
DATA_SCHEMA = vol.Schema(
    {
        vol.Required("token"): str,
        vol.Required("supplyNumber"): str,
        vol.Required("taxNumber"): str,
        vol.Optional(
            "initial_time",
            default=(dt_util.now() - timedelta(days=DEFAULT_INITIAL_DAYS)).strftime(
                "%d/%m/%Y"
            ),
        ): str,
        vol.Optional("interval_hours", default=DEFAULT_INTERVAL_HOURS): vol.All(
            int, vol.Range(min=1, max=24)
        ),
    }
)


class DeddieConfigFlow(
    config_entries.ConfigFlow,
    domain=DOMAIN,  # type: ignore[call-arg]
):
    """Config flow για την ενσωμάτωση ΔΕΔΔΗΕ τηλεμετρία καταναλώσεων."""

    VERSION = 1
    CONNECTION_CLASS = config_entries.CONN_CLASS_CLOUD_POLL

    async def async_step_user(
        self, user_input: dict[str, Any] | None = None
    ) -> config_entries.ConfigFlowResult:
        errors: dict[str, str] = {}
        if user_input is not None:
            # Αποθήκευση προηγούμενων τιμών ώστε να διατηρούνται
            # στο form σε περίπτωση σφάλματος
            self._user_input = user_input.copy()
            token = user_input["token"]
            supply = user_input["supplyNumber"]
            tax = user_input["taxNumber"]
            initial_time = user_input.get(
                "initial_time",
                (dt_util.now() - timedelta(days=DEFAULT_INITIAL_DAYS)).strftime(
                    "%d/%m/%Y"
                ),
            )
            interval_hours = user_input.get("interval_hours", DEFAULT_INTERVAL_HOURS)

            # Έλεγχοι εγκυρότητας πεδίων και credentials
            # 1) supplyNumber και taxNumber (9 ψηφία)
            if len(supply) != 9 or not supply.isdigit():
                errors["supplyNumber"] = "invalid_supply_number"
            elif len(tax) != 9 or not tax.isdigit():
                errors["taxNumber"] = "invalid_tax_number"

            # 2) μορφής, εγκυρότητας και παρελθοντικής ημερομηνίας
            if initial_time:
                DATE_RE = re.compile(r"^\d{2}/\d{2}/\d{4}$")
                if not DATE_RE.match(initial_time):
                    errors["initial_time"] = "invalid_date_format"
                else:
                    try:
                        # semantic check (θα σηκώσει ValueError αν δεν είναι έγκυρο)
                        dt_obj = datetime.strptime(initial_time, "%d/%m/%Y")
                        # Δεν επιτρέπουμε σημερινή ή μελλοντική ημερομηνία
                        if dt_obj.date() >= dt_util.now().date():
                            errors["initial_time"] = "invalid_date_not_past"
                    except ValueError:
                        errors["initial_time"] = "invalid_date_format"

            # 3) εύρος interval_hours (1-24)
            if interval_hours < 1 or interval_hours > 24:
                errors["interval_hours"] = "invalid_interval_hours"

            # 4) dry‑run επαλήθευση credentials
            if not errors:
                try:
                    curves = await validate_credentials(self.hass, token, supply, tax)
                except Exception as e:
                    if "Unauthorized" in str(e) or "401" in str(e):
                        errors["base"] = "invalid_token_or_tax"
                    else:
                        errors["base"] = "unknown_error"
                else:
                    if not curves:
                        errors["base"] = "invalid_supply"

            if errors:
                # Inline schema με defaults από user_input ώστε να διατηρούνται οι τιμές
                defaults = self._user_input
                inline_schema = vol.Schema(
                    {
                        vol.Required("token", default=defaults.get("token", "")): str,
                        vol.Required(
                            "supplyNumber", default=defaults.get("supplyNumber", "")
                        ): str,
                        vol.Required(
                            "taxNumber", default=defaults.get("taxNumber", "")
                        ): str,
                        vol.Optional(
                            "initial_time",
                            default=defaults.get(
                                "initial_time",
                                (
                                    dt_util.now() - timedelta(days=DEFAULT_INITIAL_DAYS)
                                ).strftime("%d/%m/%Y"),
                            ),
                        ): str,
                        vol.Optional(
                            "interval_hours",
                            default=defaults.get(
                                "interval_hours", DEFAULT_INTERVAL_HOURS
                            ),
                        ): vol.All(int, vol.Range(min=1, max=24)),
                    }
                )
                return self.async_show_form(
                    step_id="user",
                    data_schema=inline_schema,
                    errors=errors,
                    description_placeholders={
                        "token_link": self._build_token_link(),
                        "help_link": self._build_help_link(),
                    },
                )

            await self.async_set_unique_id(supply)
            self._abort_if_unique_id_configured()
            _LOGGER.debug(
                "Παροχή %s: Καταχωρήθηκε επιτυχώς! (Κλειδί Token=%s, "
                "ΑΦΜ=%s, Συχνότητα ενημερώσεων=%s ώρες, Αρχική ημερομηνία=%s)",
                supply,
                token[:4] + "***",
                tax,
                interval_hours,
                initial_time,
            )
            # Δημιουργία persistent notification για τον επιτυχή έλεγχο των Credentials
            from homeassistant.components.persistent_notification import (
                async_create as pn_create,
            )

            res = pn_create(
                self.hass,
                translate("config.success_notification", self.hass.config.language),
                title=translate(
                    "config.success_title", self.hass.config.language, supply=supply
                ),
                notification_id="deddie_metering_success",
            )
            if asyncio.iscoroutine(res):
                self.hass.async_create_task(res)

            # Αποθήκευση entry.data & entry.options
            data = {
                "supplyNumber": supply,
                "taxNumber": tax,
            }
            options = {
                "token": token,
                "initial_time": initial_time,
                "interval_hours": interval_hours,
            }
            return self.async_create_entry(
                title=f"Παροχή {supply}",
                data=data,
                options=options,
            )

        # Πρώτη εμφάνιση φόρμας
        defaults = self._user_input if hasattr(self, "_user_input") else {}
        return self.async_show_form(
            step_id="user",
            data_schema=DATA_SCHEMA,
            errors=errors,
            description_placeholders={
                "token_link": self._build_token_link(),
                "help_link": self._build_help_link(),
            },
        )

    def _build_token_link(self) -> str:
        if self.hass.config.language.lower().startswith("el"):
            token_label = "ΔΕΔΔΗΕ"
        else:
            token_label = "HEDNO"
        return f'<a href="https://apps.deddie.gr/mdp/intro.html">{token_label}</a>'

    def _build_help_link(self) -> str:
        return (
            '<a href="https://www.insomnia.gr/forums/topic/'
            "841087-%CE%B4%CE%B5%CE%B4%CE%B4%CE%B7%CE%B5-"
            "%CF%84%CE%B7%CE%BB%CE%B5%CE%BC%CE%B5%CF%84%CF%81%CE%AF%CE%B1-"
            "%CE%BA%CE%B1%CF%84%CE%B1%CE%BD%CE%B1%CE%BB%CF%8E%CF%83%CE%B5%CF%89%CE%BD-"
            'deddie-consumption-metering">'
            "insomnia.gr</a>"
        )

    @staticmethod
    def async_get_options_flow(
        config_entry: config_entries.ConfigEntry,
    ) -> config_entries.OptionsFlow:
        from .options_flow import DeddieOptionsFlowHandler

        return DeddieOptionsFlowHandler(config_entry)
