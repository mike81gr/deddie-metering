import voluptuous as vol
import logging
import re
import asyncio
from datetime import datetime, timedelta
import homeassistant.util.dt as dt_util
from homeassistant import config_entries
from homeassistant.config_entries import ConfigEntry
from homeassistant.data_entry_flow import FlowResult
from typing import Any, Dict

from .const import DEFAULT_INTERVAL_HOURS, DEFAULT_INITIAL_DAYS, CONF_HAS_PV
from .api.client import validate_credentials
from .helpers.translate import translate
from .helpers.utils import run_initial_batches
from .helpers.storage import save_last_total, save_initial_jump_flag

_LOGGER = logging.getLogger("deddie_metering")


class DeddieOptionsFlowHandler(config_entries.OptionsFlow):
    """Διαχείριση επιλογών για την ενσωμάτωση ΔΕΔΔΗΕ τηλεμετρία καταναλώσεων."""

    def __init__(self, config_entry: ConfigEntry) -> None:
        self._config_entry = config_entry
        self.hass = config_entry.hass if hasattr(config_entry, "hass") else None

    def _get_schema(self, defaults: Dict[str, Any]) -> vol.Schema:
        """Δημιουργεί το schema με τα αποθηκευμένα options."""
        return vol.Schema(
            {
                vol.Required(
                    "token",
                    default=defaults.get(
                        "token", self._config_entry.options.get("token")
                    ),
                ): str,
                vol.Optional(
                    "interval_hours",
                    default=defaults.get(
                        "interval_hours",
                        self._config_entry.options.get(
                            "interval_hours", DEFAULT_INTERVAL_HOURS
                        ),
                    ),
                ): vol.All(int, vol.Range(min=1, max=24)),
                vol.Optional(
                    "initial_time",
                    default=defaults.get(
                        "initial_time",
                        self._config_entry.options.get(
                            "initial_time",
                            (
                                dt_util.now() - timedelta(days=DEFAULT_INITIAL_DAYS)
                            ).strftime("%d/%m/%Y"),
                        ),
                    ),
                ): str,
            }
        )

    async def async_step_init(
        self, user_input: dict[str, Any] | None = None
    ) -> FlowResult:
        defaults = user_input or {}
        errors: dict[str, str] = {}

        # Εμφάνιση αρχικής φόρμας
        if not user_input:
            return self.async_show_form(
                step_id="init",
                data_schema=self._get_schema(defaults),
                errors=errors,
                description_placeholders={
                    "token_link": self._build_token_link(),
                    "help_link": self._build_help_link(),
                },
            )

        supply = self._config_entry.data.get("supplyNumber", "")
        tax = self._config_entry.data.get("taxNumber", "")
        old_token = self._config_entry.options.get("token", "")
        new_token = user_input.get("token", old_token)
        old_initial = self._config_entry.options.get("initial_time", "")
        new_initial = user_input.get("initial_time", old_initial)
        interval_hours = user_input.get("interval_hours", DEFAULT_INTERVAL_HOURS)

        # 1) Field-validation (interval_hours & initial_time)
        field_errors = self._validate_user_input(user_input)

        # 2) Έλεγχος αλλαγής token
        token_errors: dict[str, str] = {}
        if "token" in user_input and new_token and new_token != old_token:
            token_errors = await self._async_validate_token(
                new_token, old_token, supply, tax
            )

        # --- (1) & (2) αθροιστικό validation ---
        errors = {**field_errors, **token_errors}
        if errors:
            return self.async_show_form(
                step_id="init",
                data_schema=self._get_schema(defaults),
                errors=errors,
                description_placeholders={
                    "token_link": self._build_token_link(),
                    "help_link": self._build_help_link(),
                },
            )
        if new_token and new_token != old_token:
            await self._update_notification(supply)

        # 3) Έλεγχος αλλαγής initial_time για πρόσθετες ενέργειες
        await self._async_check_initial_time(
            new_initial,
            old_initial,
            supply,
            tax,
            new_token,
        )

        _LOGGER.info(
            "Παροχή %s: Ενημερώθηκε επιτυχώς! "
            "(Κλειδί Token=%s, Συχνότητα ενημερώσεων=%s ώρες, "
            "Αρχική ημερομηνία=%s)",
            self._config_entry.data.get("supplyNumber"),
            (new_token or old_token)[:4] + "***",
            interval_hours,
            (new_initial or old_initial),
        )

        # 4) Create entry (options)
        new_options = {
            **self._config_entry.options,
            **user_input,
        }
        return self.async_create_entry(
            title=f"Παροχή {supply}",
            data=new_options,
        )

    def _validate_user_input(self, user_input: Dict[str, Any]) -> Dict[str, str]:
        """
        Ελέγχει format και τιμές πεδίων.
        Επιστρέφει λεξικό πεδίων -> κωδικοί σφάλματος.
        """
        errors: Dict[str, str] = {}

        # Έλεγχος νέας initial_time
        new_initial = user_input.get("initial_time", "")
        old_initial = self._config_entry.options.get("initial_time", "")
        if new_initial and new_initial != old_initial:
            DATE_RE = re.compile(r"^\d{2}/\d{2}/\d{4}$")
            if not DATE_RE.match(new_initial):
                errors["initial_time"] = "invalid_date_format"
            else:
                try:
                    new_dt = datetime.strptime(new_initial, "%d/%m/%Y").date()
                except ValueError:
                    errors["initial_time"] = "invalid_date_format"
                else:
                    if new_dt > dt_util.now().date():
                        errors["initial_time"] = "date_in_future"
                    else:
                        try:
                            old_dt = datetime.strptime(old_initial, "%d/%m/%Y").date()
                        except Exception:
                            pass
                        else:
                            if new_dt >= old_dt:
                                errors["initial_time"] = "date_not_earlier"

        # Έλεγχος εύρους για 'interval_hours'
        interval_hours = user_input.get("interval_hours")
        if interval_hours is None or not (1 <= interval_hours <= 24):
            errors["interval_hours"] = "invalid_interval_hours"

        return errors

    async def _async_validate_token(
        self,
        new_token: str,
        old_token: str,
        supply: str,
        tax: str,
    ) -> Dict[str, str]:
        """
        Ελέγχος αλλαγής κλειδιού token και εγκυρότητας.
        Επιστρέφει λεξικό πεδίων -> κωδικοί σφάλματος.
        """
        errors: Dict[str, str] = {}
        if new_token and new_token != old_token:
            # Επαλήθευση εγκυρότητας token μέσω dry-run.
            try:
                await validate_credentials(
                    self.hass,
                    new_token,
                    supply,
                    tax,
                    "active",
                )
            except Exception as e:
                if "Unauthorized" in str(e) or "401" in str(e):
                    errors["base"] = "invalid_token"
                else:
                    errors["base"] = "unknown_error"

        return errors

    async def _async_check_initial_time(
        self,
        new_initial: str,
        old_initial: str,
        supply: str,
        tax: str,
        new_token: str,
    ) -> Dict[str, str]:
        """
        Ελέγχος αλλαγής αρχικής ημερομηνίας.
        Reset το persisted total και έναρξη initial batches
        Επιστρέφει λεξικό πεδίων -> κωδικοί σφάλματος κενό.
        """
        errors: Dict[str, str] = {}
        if new_initial and new_initial != old_initial:
            dt_obj = datetime.strptime(new_initial, "%d/%m/%Y")
            dt_obj = dt_util.as_local(dt_obj)
            token = new_token or self._config_entry.options.get("token")
            has_pv = self._config_entry.options.get(CONF_HAS_PV, False)

            # Reset όλων των last_totals ώστε το batch να ξεκινήσει
            # από 0.0 και όλων των jump flags
            for key in ("active", "produced", "injected"):
                await save_last_total(self.hass, supply, 0.0, key=key)
                await save_initial_jump_flag(self.hass, supply, False, key=key)

            _LOGGER.info(
                "Παροχή %s: Δόθηκε νέα αρχική ημερομηνία. "
                "Έναρξη αρχικής ενημέρωσης: Ξεκινά η διαδικασία "
                "batch processing...",
                supply,
            )
            await run_initial_batches(
                self.hass,
                token,
                supply,
                tax,
                dt_obj,
                has_pv,
                inc_con=True,
            )

        return errors

    async def _update_notification(self, supply: str) -> bool:
        # Ειδοποίηση επιτυχούς setup
        from homeassistant.components.persistent_notification import (
            async_create as pn_create,
        )

        res = pn_create(
            self.hass,
            translate("options.token_updated_notification", self.hass.config.language),
            title=translate(
                "options.token_updated_title", self.hass.config.language, supply=supply
            ),
            notification_id="deddie_options_token_updated",
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
            "841087-%CE%B4%CE%B5%CE%B4%CE%B4%CE%B7%CE%B5-"
            "%CF%84%CE%B7%CE%BB%CE%B5%CE%BC%CE%B5%CF%84%CF%81%CE%AF%CE%B1-"
            "%CE%BA%CE%B1%CF%84%CE%B1%CE%BD%CE%B1%CE%BB%CF%8E%CF%83%CE%B5%CF%89%CE%BD-"
            'deddie-consumption-metering">'
            "insomnia.gr</a>"
        )
