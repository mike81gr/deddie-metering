import logging
from datetime import timedelta
from homeassistant.helpers.update_coordinator import DataUpdateCoordinator, UpdateFailed
import homeassistant.util.dt as dt_util

from .utils import batch_fetch, fetch_since
from .storage import load_last_total, load_last_update

_LOGGER = logging.getLogger("deddie_metering")


class DeddieDataUpdateCoordinator(DataUpdateCoordinator):
    """
    DataUpdateCoordinator για το integration Deddie Metering,
    με δυνατότητα να επιστρέφει στην πρώτη ενημέρωση
    (fresh install) state=0.0, ώστε ο αισθητήρας να αρχικοποιείται
    σωστά (δηλαδή, καταγράφοντας αρχικά 0.0 στον recorder).
    """

    def __init__(
        self,
        hass,
        token: str,
        supply: str,
        tax: str,
        update_interval: timedelta,
        skip_initial_refresh: bool,
    ):
        self._token = token
        self._supply = supply
        self._tax = tax
        self._skip_first_refresh = skip_initial_refresh
        super().__init__(
            hass,
            _LOGGER,
            name=f"DeddieMetering_{supply}",
            update_interval=update_interval,
        )

    async def _async_update_data(self):
        try:
            # Fresh setup: Πρώτη ενημέρωση με 0.0 (αν _skip_first_refresh είναι True)
            if self._skip_first_refresh:
                _LOGGER.info(
                    "Παροχή %s: Ο αισθητήρας αρχικοποιείται σε κατάσταση 0.0.",
                    self._supply,
                )
                self._skip_first_refresh = False
                self._initial_jump_done = False
                # Trigger second refresh after 1 sec
                self.schedule_refresh()
                return {
                    "total_kwh": 0.0,
                    "latest_date": None,
                    "last_fetch": dt_util.now().isoformat(),
                }
            # Δεύτερη φορά μετά το jump: επιστρέφει το total_kwh χωρίς API
            if hasattr(self, "_initial_jump_done") and self._initial_jump_done is False:
                self._initial_jump_done = True
                total = await load_last_total(self.hass, self._supply) or 0.0
                last_update = await load_last_update(self.hass, self._supply)
                _LOGGER.info(
                    "Παροχή %s: Ο αισθητήρας έλαβε νέα κατάσταση %.2f KWh.",
                    self._supply,
                    total,
                )
                return {
                    "total_kwh": total,
                    "latest_date": (
                        last_update.date().isoformat() if last_update else None
                    ),
                    "last_fetch": dt_util.now().isoformat(),
                }

            # Fresh not first: Αν δεν έχει ακόμη γίνει η πρώτη ενημέρωση,
            # επιστρέφονται τα αποθηκευμένα persistent δεδομένα χωρίς API call.
            if not hasattr(self, "_first_update_done"):
                self._first_update_done = False
            if not self._first_update_done:
                self._first_update_done = True
                total = await load_last_total(self.hass, self._supply) or 0.0
                last_update = await load_last_update(self.hass, self._supply)
                _LOGGER.info(
                    "Παροχή %s: Ανακτώνται τα αποθηκευμένα δεδομένα "
                    "του αισθητήρα: %.2f KWh.",
                    self._supply,
                    total,
                )
                self.schedule_refresh()
                return {
                    "total_kwh": total,
                    "latest_date": (
                        last_update.date().isoformat() if last_update else None
                    ),
                    "last_fetch": dt_util.now().isoformat(),
                }
            else:
                # Περιοδική ενημέρωση από ΔΕΔΔΗΕ API
                last_update = await load_last_update(self.hass, self._supply)
                new_to = dt_util.now()
                formatted_date = (
                    (last_update - timedelta(days=1)).strftime("%d/%m/%Y")
                    if last_update
                    else "Unknown"
                )
                _LOGGER.info(
                    "Παροχή %s: Βρέθηκε προηγούμενη λήψη την %s. "
                    "Έναρξη περιοδικής ενημέρωσης.",
                    self._supply,
                    formatted_date,
                )
                gap = new_to - last_update
                if gap > timedelta(days=7):
                    _LOGGER.info(
                        "Παροχή %s: Εντοπίστηκε κενό δεδομένων για %d ημέρες. "
                        "Ξεκινά η διαδικασία batch processing...",
                        self._supply,
                        gap.days,
                    )
                    await batch_fetch(
                        self.hass,
                        self._token,
                        self._supply,
                        self._tax,
                        last_update,
                        new_to,
                        "Περιοδική ενημέρωση",
                        60,
                    )
                else:
                    await fetch_since(
                        self.hass,
                        self._token,
                        self._supply,
                        self._tax,
                        last_update,
                        new_to,
                        "Περιοδική ενημέρωση",
                        60,
                    )

                # Ενημέρωση του αισθητήρα: επιστρέφουμε τα νέα δεδομένα
                # ώστε να ενημερωθεί το sensor state.
                latest_value = await load_last_update(self.hass, self._supply)
                total_consumption = await load_last_total(self.hass, self._supply)
                return {
                    "total_kwh": total_consumption,
                    "latest_date": latest_value.date().isoformat(),
                    "last_fetch": new_to.isoformat(),
                }

        except Exception as err:
            raise UpdateFailed(
                f"Σφάλμα στην ενημέρωση για την παροχή {self._supply}: {err}"
            )

    def schedule_refresh(self) -> None:
        """Προγραμματίζει ανανέωση μετά από 1 δευτερόλεπτο."""
        self.hass.loop.call_later(
            1, lambda: self.hass.async_create_task(self.async_request_refresh())
        )
