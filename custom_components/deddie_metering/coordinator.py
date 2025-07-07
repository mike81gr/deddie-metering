import logging
from datetime import timedelta, datetime
from homeassistant.helpers.update_coordinator import DataUpdateCoordinator, UpdateFailed
from typing import Any, Dict
import homeassistant.util.dt as dt_util
import homeassistant.components.persistent_notification as pn
import asyncio

from .helpers.utils import batch_fetch, fetch_since
from .helpers.storage import load_last_total, load_last_update
from .helpers.translate import translate
from .api.detection import detect_pv
from .const import (
    DEFAULT_PV_THRESHOLD,
    ATTR_CONSUMPTION,
    ATTR_PRODUCTION,
    ATTR_INJECTION,
)

_LOGGER = logging.getLogger("deddie_metering")


class DeddieDataUpdateCoordinator(DataUpdateCoordinator):
    """
    DataUpdateCoordinator για το integration Deddie Metering,
    με δυνατότητα να επιστρέφει στην πρώτη ενημέρωση
    (fresh setup) state=0.0, ώστε ο αισθητήρας να αρχικοποιείται
    σωστά (δηλαδή, καταγράφοντας αρχικά 0.0 στον recorder).
    """

    def __init__(
        self,
        hass,
        token: str,
        supply: str,
        tax: str,
        update_interval: timedelta,
        choose_step_flag: str,
        has_pv: bool,
        entry: str,
    ):
        self._token = token
        self._supply = supply
        self._tax = tax
        self._choose_step_flag = choose_step_flag
        self.has_pv = has_pv
        self._entry = entry
        super().__init__(
            hass,
            _LOGGER,
            name=f"DeddieMetering_{supply}",
            update_interval=update_interval,
        )

    async def _async_update_data(self) -> Dict[str, Any]:
        try:
            # (A1) Fresh not first κατανάλωση & Fresh setup παραγωγή/έγχυση
            if self._choose_step_flag == "A1":
                return await self._handle_migrated_jump()
            # (A2) Fresh setup κατανάλωση/παραγωγή/έγχυση
            elif self._choose_step_flag == "A2":
                return await self._handle_fresh_setup_jump()
            # (B) Επιστρέφονται τα total_kWh μετά την αρχικοποίηση στα A1 & A2
            elif self._choose_step_flag == "B":
                return await self._handle_post_jump_restore()
            # (C) Fresh not first: Επιστρέφονται τα persistent δεδομένα
            elif self._choose_step_flag == "C":
                return await self._handle_persistent_restore()
            # (D) Περιοδική ενημέρωση από ΔΕΔΔΗΕ API
            elif self._choose_step_flag == "D":
                return await self._handle_periodic_update()
            else:
                raise UpdateFailed(f"Άγνωστο βήμα: {self._choose_step_flag}")

        except Exception as err:
            raise UpdateFailed(
                f"Σφάλμα στην ενημέρωση για την παροχή {self._supply}: {err}"
            )

    # Εκτέλεση βήματος (A1)
    async def _handle_migrated_jump(self) -> Dict[str, Any]:
        _LOGGER.info(
            "Παροχή %s: Aρχικοποιήση αισθητήρων σε κατάσταση 0.0",
            self._supply,
        )
        self._choose_step_flag = "B"
        now = dt_util.now().isoformat()
        self.schedule_refresh()
        return {
            # Παραγωγή
            ATTR_PRODUCTION: 0.0,
            f"latest_date_{ATTR_PRODUCTION}": None,
            f"last_fetch_{ATTR_PRODUCTION}": now,
            # Έγχυση
            ATTR_INJECTION: 0.0,
            f"latest_date_{ATTR_INJECTION}": None,
            f"last_fetch_{ATTR_INJECTION}": now,
        }

    # Εκτέλεση βήματος (A2)
    async def _handle_fresh_setup_jump(self) -> Dict[str, Any]:
        _LOGGER.info(
            "Παροχή %s: Aρχικοποιήση αισθητήρων σε κατάσταση 0.0",
            self._supply,
        )
        self._choose_step_flag = "B"
        now = dt_util.now().isoformat()
        self.schedule_refresh()
        return {
            # Κατανάλωση
            ATTR_CONSUMPTION: 0.0,
            f"latest_date_{ATTR_CONSUMPTION}": None,
            f"last_fetch_{ATTR_CONSUMPTION}": now,
            # Παραγωγή
            ATTR_PRODUCTION: 0.0,
            f"latest_date_{ATTR_PRODUCTION}": None,
            f"last_fetch_{ATTR_PRODUCTION}": now,
            # Έγχυση
            ATTR_INJECTION: 0.0,
            f"latest_date_{ATTR_INJECTION}": None,
            f"last_fetch_{ATTR_INJECTION}": now,
        }

    # Εκτέλεση βήματος (B)
    async def _handle_post_jump_restore(self) -> Dict[str, Any]:
        self._choose_step_flag = "D"
        return await self._load_persistent_data(mark_first=True)

    # Εκτέλεση βήματος (C)
    async def _handle_persistent_restore(self) -> Dict[str, Any]:
        self._choose_step_flag = "D"
        self.schedule_refresh()
        return await self._load_persistent_data(mark_first=False)

    # Εκτέλεση βήματος (D)
    async def _handle_periodic_update(self) -> Dict[str, Any]:
        now = dt_util.now()
        # 1o τμήμα - Κατανάλωση
        await self._update_consumption(now)
        # 2 τμήμα - PV detection
        await self._ensure_pv_detected()
        # 3 & 4 τμήμα - Παραγωγή/Έγχυση
        if self.has_pv:
            await self._update_production(now)
            await self._update_injection(now)
        # 5ο τμήμα - payload
        return await self._build_payload(now)

    # Χρησιμοποιείται στα Βήματα (B) & (C)
    async def _load_persistent_data(self, mark_first: bool) -> Dict[str, Any]:
        """
        Φορτώνει τα saved totals/updates και επιστρέφει κοινό dict.
        mark_first: αν True, πρόκειται για μετά jump ή first restore.
        """
        now_ts = dt_util.now().isoformat()
        data = {}
        for key in (ATTR_CONSUMPTION, ATTR_PRODUCTION, ATTR_INJECTION):
            # αγνοούμε production/injection αν δεν έχει PV
            if key != ATTR_CONSUMPTION and not self.has_pv:
                continue
            last_u = await load_last_update(self.hass, self._supply, key=key)
            last_t = await load_last_total(self.hass, self._supply, key=key) or 0.0
            data[key] = last_t
            data[f"latest_date_{key}"] = last_u.date().isoformat() if last_u else None
            data[f"last_fetch_{key}"] = now_ts
            if key == ATTR_CONSUMPTION:
                label = "κατανάλωσης"
            elif key == ATTR_PRODUCTION:
                label = "παραγωγής"
            elif key == ATTR_INJECTION:
                label = "εγχυσης"
            if mark_first:
                _LOGGER.info(
                    "Παροχή %s: Ο αισθητήρας %s έλαβε νέα κατάσταση %.2f KWh.",
                    self._supply,
                    label,
                    last_t,
                )
            else:
                _LOGGER.info(
                    "Παροχή %s: Ανακτώνται τα αποθηκευμένα δεδομένα "
                    "του αισθητήρα %s: %.2f KWh.",
                    self._supply,
                    label,
                    last_t,
                )
        return data

    # Χρησιμοποιείται στο Βήμα (D) -> 1ο τμήμα
    async def _update_consumption(self, now: datetime) -> None:
        last = await load_last_update(self.hass, self._supply, key=ATTR_CONSUMPTION)
        gap = (now - last) if last else timedelta.max
        label = "Περιοδική ενημέρωση κατανάλωσης"
        if gap > timedelta(days=365):
            _LOGGER.info(
                "Παροχή %s: <Περιοδική ενημέρωση κατανάλωσης> "
                "Εντοπίστηκε κενό δεδομένων για %d ημέρες. "
                "Ξεκινά η διαδικασία batch processing...",
                self._supply,
                gap.days,
            )
            await batch_fetch(
                self.hass,
                self._token,
                self._supply,
                self._tax,
                last,
                now,
                label,
                60,
                ATTR_CONSUMPTION,
            )
        else:
            _LOGGER.info(
                "Παροχή %s: Εντοπίστηκε κενό δεδομένων για %d ημέρες. "
                "Έναρξη περιοδικής ενημέρωσης κατανάλωσης ενέργειας.",
                self._supply,
                gap.days,
            )
            await fetch_since(
                self.hass,
                self._token,
                self._supply,
                self._tax,
                last,
                now,
                label,
                60,
                ATTR_CONSUMPTION,
            )

    # Χρησιμοποιείται στο Βήμα (D) -> 2o τμήμα
    async def _ensure_pv_detected(self) -> None:
        if not self.has_pv:
            self.has_pv = await detect_pv(
                self.hass, self._entry, self._token, self._supply, self._tax
            )

    # Χρησιμοποιείται στο Βήμα (D) -> 3ο τμήμα
    async def _update_production(self, now: datetime) -> None:
        last = await load_last_update(self.hass, self._supply, key=ATTR_PRODUCTION)
        gap = (now - last) if last else timedelta.max
        label = "Περιοδική ενημέρωση παραγωγής"
        if gap > timedelta(days=365):
            _LOGGER.info(
                "Παροχή %s: <Περιοδική ενημέρωση παραγωγής> "
                "Εντοπίστηκε κενό δεδομένων για %d ημέρες. "
                "Ξεκινά η διαδικασία batch processing...",
                self._supply,
                gap.days,
            )
            await batch_fetch(
                self.hass,
                self._token,
                self._supply,
                self._tax,
                last,
                now,
                label,
                60,
                ATTR_PRODUCTION,
            )
        else:
            _LOGGER.info(
                "Παροχή %s: Εντοπίστηκε κενό δεδομένων για %d ημέρες. "
                "Έναρξη περιοδικής ενημέρωσης παραγωγής ενέργειας.",
                self._supply,
                gap.days,
            )
            await fetch_since(
                self.hass,
                self._token,
                self._supply,
                self._tax,
                last,
                now,
                label,
                60,
                ATTR_PRODUCTION,
            )

    # Χρησιμοποιείται στο Βήμα (D) -> 4ο τμήμα
    async def _update_injection(self, now: datetime) -> None:
        last = await load_last_update(self.hass, self._supply, key=ATTR_INJECTION)
        gap = (now - last) if last else timedelta.max
        label = "Περιοδική ενημέρωση έγχυσης"
        if gap > timedelta(days=365):
            _LOGGER.info(
                "Παροχή %s: <Περιοδική ενημέρωση έγχυσης> "
                "Εντοπίστηκε κενό δεδομένων για %d ημέρες. "
                "Ξεκινά η διαδικασία batch processing...",
                self._supply,
                gap.days,
            )
            await batch_fetch(
                self.hass,
                self._token,
                self._supply,
                self._tax,
                last,
                now,
                label,
                60,
                ATTR_INJECTION,
            )
        else:
            _LOGGER.info(
                "Παροχή %s: Εντοπίστηκε κενό δεδομένων για %d ημέρες. "
                "Έναρξη περιοδικής ενημέρωσης έγχυσης ενέργειας.",
                self._supply,
                gap.days,
            )
            await fetch_since(
                self.hass,
                self._token,
                self._supply,
                self._tax,
                last,
                now,
                label,
                60,
                ATTR_INJECTION,
            )

    # Χρησιμοποιείται ως βοηθητική στο Βήμα (D) στο 5ο τμήμα
    async def _maybe_warn_on_pv_gap(self, latest) -> None:
        # Έλεγχος συνεχόμενων ημερών χωρίς παραγωγή
        now = dt_util.now().date()
        last = latest.date()
        delta = (now - last).days
        if delta >= DEFAULT_PV_THRESHOLD:
            # Μήνυμα warning για PV
            res = pn.async_create(
                self.hass,
                translate(
                    "coordinator.pv_warning_message",
                    self.hass.config.language,
                    days=delta,
                ),
                title=translate(
                    "coordinator.pv_warning_title",
                    self.hass.config.language,
                    supply=self._supply,
                ),
                notification_id=f"deddie_metering_pv_warning_{self._supply}",
            )
            if asyncio.iscoroutine(res):
                self.hass.async_create_task(res)

    # Χρησιμοποιείται στο Βήμα (D) -> 5ο τμήμα
    async def _build_payload(self, now: datetime) -> Dict[str, Any]:
        now_ts = now.isoformat()
        result: Dict[str, Any] = {}
        for key in (ATTR_CONSUMPTION, ATTR_PRODUCTION, ATTR_INJECTION):
            if key != ATTR_CONSUMPTION and not self.has_pv:
                continue
            total = await load_last_total(self.hass, self._supply, key=key)
            last_u = await load_last_update(self.hass, self._supply, key=key)
            result[key] = total
            result[f"latest_date_{key}"] = last_u.date().isoformat() if last_u else None
            result[f"last_fetch_{key}"] = now_ts
            if key == ATTR_PRODUCTION:
                await self._maybe_warn_on_pv_gap(last_u)
        return result

    # Χρησιμοποιείται στα Βήματα (A1), (A2) & (C)
    def schedule_refresh(self) -> None:
        """Προγραμματίζει ανανέωση μετά από 1 δευτερόλεπτο."""
        self.hass.loop.call_later(
            1, lambda: self.hass.async_create_task(self.async_request_refresh())
        )
