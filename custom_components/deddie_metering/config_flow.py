from datetime import datetime, timedelta
import voluptuous as vol
import re
from typing import Any
from homeassistant import config_entries
import homeassistant.util.dt as dt_util
import logging
import asyncio

from .const import (
    DOMAIN,
    DEFAULT_INTERVAL_HOURS,
    DEFAULT_INITIAL_DAYS,
    CONF_HAS_PV,
    CONF_FRESH_SETUP,
)
from .helpers.storage import load_last_total, load_last_update
from .helpers.translate import translate
from .api.client import validate_credentials

_LOGGER = logging.getLogger("deddie_metering")


class DeddieConfigFlow(
    config_entries.ConfigFlow,
    domain=DOMAIN,  # type: ignore[call-arg]
):
    """Config flow για την ενσωμάτωση ΔΕΔΔΗΕ τηλεμετρία καταναλώσεων."""

    VERSION = 1
    MINOR_VERSION = 2
    CONNECTION_CLASS = config_entries.CONN_CLASS_CLOUD_POLL

    def _validate_user_input(self, user_input: dict) -> dict[str, str]:
        """
        Ελέγχει και επιστρέφει λεξικό σφαλμάτων για κάθε πεδίο του user_input.
        """
        errors: dict[str, str] = {}
        supply = user_input.get("supplyNumber", "")
        tax = user_input.get("taxNumber", "")
        initial_time = user_input.get("initial_time", "")
        interval_hours = user_input.get("interval_hours")

        # Έλεγχος format 'supplyNumber' - ακριβώς 9 ψηφία
        if not re.fullmatch(r"\d{9}", supply):
            errors["supplyNumber"] = "invalid_supply_number"
            return errors

        # Έλεγχος format 'taxNumber' - ακριβώς 9 ψηφία
        if not re.fullmatch(r"\d{9}", tax):
            errors["taxNumber"] = "invalid_tax_number"
            return errors

        # Έλεγχος format 'initial_time' ως dd/mm/yyyy
        if initial_time:
            DATE_RE = re.compile(r"^\d{2}/\d{2}/\d{4}$")
            if not DATE_RE.match(initial_time):
                errors["initial_time"] = "invalid_date_format"
            else:
                try:
                    dt_obj = datetime.strptime(initial_time, "%d/%m/%Y")
                    if dt_obj.date() >= dt_util.now().date():
                        errors["initial_time"] = "invalid_date_not_past"
                except ValueError:
                    errors["initial_time"] = "invalid_date_format"

        # Έλεγχος εύρους για 'interval_hours'
        if interval_hours is None or not (1 <= interval_hours <= 24):
            errors["interval_hours"] = "invalid_interval_hours"

        return errors

    async def async_step_user(
        self, user_input: dict[str, Any] | None = None
    ) -> config_entries.ConfigFlowResult:
        """
        Αρχικό βήμα χρήστη: δείχνει τη φόρμα, ελέγχει τα πεδία, και δημιουργεί entry.
        """
        defaults = user_input or {}
        errors: dict[str, str] = {}

        # Εμφάνιση αρχικής φόρμας
        if not user_input:
            return self.async_show_form(
                step_id="user",
                data_schema=self._get_user_schema(defaults),
                errors=errors,
                description_placeholders={
                    "token_link": self._build_token_link(),
                    "help_link": self._build_help_link(),
                },
            )

        # 1) Field-validation
        errors = self._validate_user_input(user_input)
        if errors:
            return self.async_show_form(
                step_id="user",
                data_schema=self._get_user_schema(defaults),
                errors=errors,
                description_placeholders={
                    "token_link": self._build_token_link(),
                    "help_link": self._build_help_link(),
                },
            )

        token = user_input.get("token", "")
        supply = user_input.get("supplyNumber", "")
        tax = user_input.get("taxNumber", "")
        initial_time = user_input.get("initial_time", "")
        interval_hours = user_input.get("interval_hours", DEFAULT_INTERVAL_HOURS)

        # 2) Unique ID
        await self.async_set_unique_id(supply)
        self._abort_if_unique_id_configured()

        # 3) Δοκιμαστική κλήση (Dry-run credentials)
        try:
            curves = await validate_credentials(
                self.hass,
                token,
                supply,
                tax,
                "active",
            )
        except Exception as e:
            if "Unauthorized" in str(e) or "401" in str(e):
                errors["base"] = "invalid_token_or_tax"
                return self.async_show_form(
                    step_id="user",
                    data_schema=self._get_user_schema(defaults),
                    errors=errors,
                    description_placeholders={
                        "token_link": self._build_token_link(),
                        "help_link": self._build_help_link(),
                    },
                )
            else:
                errors["base"] = "unknown_error"
                return self.async_show_form(
                    step_id="user",
                    data_schema=self._get_user_schema(defaults),
                    errors=errors,
                    description_placeholders={
                        "token_link": self._build_token_link(),
                        "help_link": self._build_help_link(),
                    },
                )
        else:
            if not curves:
                errors["base"] = "invalid_supply"
                return self.async_show_form(
                    step_id="user",
                    data_schema=self._get_user_schema(defaults),
                    errors=errors,
                    description_placeholders={
                        "token_link": self._build_token_link(),
                        "help_link": self._build_help_link(),
                    },
                )

        # 4) Auto-detect Φωτοβολταϊκών
        try:
            has_pv = bool(
                await validate_credentials(
                    self.hass,
                    token,
                    supply,
                    tax,
                    "produced",
                )
            )
        except Exception:
            has_pv = False

        _LOGGER.debug(
            "Παροχή %s: Καταχωρήθηκε επιτυχώς! (Token=%s, ΑΦΜ=%s, "
            "Συχνότητα=%s ώρες, Αρχική ημερομηνία=%s)",
            supply,
            token[:4] + "***",
            tax,
            interval_hours,
            initial_time,
        )

        # 5) Έλεγχος Fresh setup (last_total και last_update αποθηκευμένα)
        last_total = await load_last_total(self.hass, supply, key="active")
        last_update = await load_last_update(self.hass, supply, key="active")
        if last_total is not None and last_update is not None:
            fresh_setup_flag = False
        else:
            fresh_setup_flag = True

        # 6) Persistent Notification & create entry (data & options)
        await self._success_notification(supply)
        data = {"supplyNumber": supply, "taxNumber": tax}
        options = {
            "token": token,
            "initial_time": initial_time,
            "interval_hours": interval_hours,
            CONF_HAS_PV: has_pv,
            CONF_FRESH_SETUP: fresh_setup_flag,
        }
        return self.async_create_entry(
            title=f"Παροχή {supply}",
            data=data,
            options=options,
        )

    async def _success_notification(self, supply: str) -> bool:
        # Ειδοποίηση επιτυχούς setup
        from homeassistant.components.persistent_notification import (
            async_create as pn_create,
        )

        res = pn_create(
            self.hass,
            translate("config.success_notification", self.hass.config.language),
            title=translate(
                "config.success_title", self.hass.config.language, supply=supply
            ),
            notification_id="deddie_success",
        )
        if asyncio.iscoroutine(res):
            self.hass.async_create_task(res)

        return True

    def _build_token_link(self) -> str:
        if self.hass.config.language.lower().startswith("el"):
            token_label = "ΔΕΔΔΗΕ"
        else:
            token_label = "HEDNO"
        return f'<a href="https://apps.deddie.gr/mdp/intro.html">{token_label}</a>'

    def _build_help_link(self) -> str:
        return (
            '<a href="https://www.insomnia.gr/forums/topic/'
            "841087-%CE%B4%CE%B5%CE%CE%97%CE%B5-"
            "%CF%84%CE%B7%CE%BB%CE%B5%CE%BC%CE%B5%CF%84%CF%81%CE%AF%CE%B1-"
            "%CE%BA%CE%B1%CF%84%CE%B1%CE%BD%CE%B1%CE%BB%CF%8E%CF%83%CE%B5%CF%89%CE%BD-"
            'deddie-consumption-metering">insomnia.gr</a>'
        )

    @staticmethod
    def _get_user_schema(defaults: dict) -> vol.Schema:
        """Στατική κατασκευή του data_schema για το user step."""
        return vol.Schema(
            {
                vol.Required("token", default=defaults.get("token", "")): str,
                vol.Required(
                    "supplyNumber", default=defaults.get("supplyNumber", "")
                ): str,
                vol.Required("taxNumber", default=defaults.get("taxNumber", "")): str,
                vol.Optional(
                    "initial_time",
                    default=defaults.get(
                        "initial_time",
                        (dt_util.now() - timedelta(days=DEFAULT_INITIAL_DAYS)).strftime(
                            "%d/%m/%Y"
                        ),
                    ),
                ): str,
                vol.Optional(
                    "interval_hours",
                    default=defaults.get("interval_hours", DEFAULT_INTERVAL_HOURS),
                ): vol.All(int, vol.Range(min=1, max=24)),
            }
        )

    @staticmethod
    def async_get_options_flow(
        config_entry: config_entries.ConfigEntry,
    ) -> config_entries.OptionsFlow:
        from .options_flow import DeddieOptionsFlowHandler

        return DeddieOptionsFlowHandler(config_entry)
