import voluptuous as vol
import logging
import re
from datetime import datetime
import homeassistant.util.dt as dt_util
from homeassistant import config_entries

from .const import DEFAULT_INTERVAL_HOURS
from .helpers.translate import translate
from .api import validate_credentials
from .utils import run_initial_batches
from .storage import save_last_total, save_initial_jump_flag

_LOGGER = logging.getLogger("deddie_metering")


class DeddieOptionsFlowHandler(config_entries.OptionsFlow):
    """Διαχείριση επιλογών για την ενσωμάτωση ΔΕΔΔΗΕ τηλεμετρία καταναλώσεων."""

    def __init__(self, config_entry):
        self._config_entry = config_entry
        self.hass = config_entry.hass if hasattr(config_entry, "hass") else None

    def get_data_schema(self):
        return vol.Schema(
            {
                vol.Optional(
                    "token",
                    default=self._config_entry.options.get("token"),
                ): str,
                vol.Optional(
                    "interval_hours",
                    default=self._config_entry.options.get(
                        "interval_hours", DEFAULT_INTERVAL_HOURS
                    ),
                ): vol.All(int, vol.Range(min=1, max=24)),
                vol.Optional(
                    "initial_time",
                    # Default μόνο από options
                    default=self._config_entry.options.get("initial_time"),
                ): str,
            }
        )

    async def async_step_init(self, user_input=None):
        if user_input is not None:
            errors: dict[str, str] = {}
            # Έλεγχος interval_hours
            interval_hours = user_input.get("interval_hours", DEFAULT_INTERVAL_HOURS)
            if interval_hours < 1 or interval_hours > 24:
                errors["interval_hours"] = "invalid_interval_hours"

            # Έλεγχος νέας initial_time
            new_initial = user_input.get("initial_time")
            old_initial = self._config_entry.options.get("initial_time")
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
                        # Δεν επιτρέπονται μελλοντικές ημερομηνίες
                        if new_dt > dt_util.now().date():
                            errors["initial_time"] = "date_in_future"
                        else:
                            try:
                                old_dt = datetime.strptime(
                                    old_initial, "%d/%m/%Y"
                                ).date()
                            except Exception:
                                pass
                            else:
                                # Πρέπει να είναι παλαιότερη η νέα ημερομηνία
                                if new_dt >= old_dt:
                                    errors["initial_time"] = "date_not_earlier"

            # Έλεγχος αλλαγής token
            old_token = self._config_entry.options.get("token")
            new_token = user_input.get("token")
            if new_token and new_token != old_token:
                # Ελέγχουμε το token μέσω dry-run για επαλήθευση εγκυρότητας.
                try:
                    await validate_credentials(
                        self.hass,
                        new_token,
                        self._config_entry.data.get("supplyNumber"),
                        self._config_entry.data.get("taxNumber"),
                    )
                except Exception as e:
                    if "Unauthorized" in str(e) or "401" in str(e):
                        errors["base"] = "invalid_token"
                    else:
                        errors["base"] = "unknown_error"
                else:
                    from homeassistant.components.persistent_notification import (
                        async_create as pn_create,
                    )

                    pn_create(
                        self.hass,
                        translate(
                            "options.token_updated_notification",
                            self.hass.config.language,
                        ),
                        title=translate(
                            "options.token_updated_title",
                            self.hass.config.language,
                            supply=self._config_entry.data.get("supplyNumber"),
                        ),
                        notification_id="deddie_options_token_updated",
                    )

            if errors:
                # Δυναμικό schema με defaults για να κρατάει ότι πληκτρολόγησε ο χρήστης
                defaults = user_input or {}
                inline_schema = vol.Schema(
                    {
                        vol.Optional(
                            "token",
                            default=defaults.get(
                                "token",
                                self._config_entry.options.get("token"),
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
                                self._config_entry.options.get("initial_time"),
                            ),
                        ): str,
                    }
                )
                return self.async_show_form(
                    step_id="init",
                    data_schema=inline_schema,
                    errors=errors,
                    description_placeholders={
                        "token_link": self._build_token_link(),
                        "help_link": self._build_help_link(),
                    },
                )

            # Αν άλλαξε η initial_time, μηδενίζουμε το persisted
            # total και τρέχουμε initial batches
            if new_initial and new_initial != old_initial:
                dt_obj = datetime.strptime(new_initial, "%d/%m/%Y")
                dt_obj = dt_util.as_local(dt_obj)

                # Reset το last_total ώστε το batch να ξεκινήσει από 0.0
                supply = self._config_entry.data["supplyNumber"]
                await save_last_total(self.hass, supply, 0.0)

                _LOGGER.info(
                    "Παροχή %s: Δόθηκε νέα αρχική ημερομηνία. "
                    "Έναρξη αρχικής ενημέρωσης: Ξεκινά η διαδικασία "
                    "batch processing...",
                    self._config_entry.data.get("supplyNumber"),
                )
                await run_initial_batches(
                    self.hass,
                    self._config_entry.options.get("token"),
                    self._config_entry.data.get("supplyNumber"),
                    self._config_entry.data.get("taxNumber"),
                    dt_obj,
                )
                await save_initial_jump_flag(
                    self.hass, self._config_entry.data.get("supplyNumber"), False
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
            return self.async_create_entry(
                title=f"Παροχή {self._config_entry.data.get('supplyNumber')}",
                data=user_input,
            )

        # Αρχική εμφάνιση φόρμας
        return self.async_show_form(
            step_id="init",
            data_schema=self.get_data_schema(),
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
