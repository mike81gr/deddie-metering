from datetime import datetime, timedelta
from homeassistant.components.sensor import SensorEntity, SensorDeviceClass
from homeassistant.const import UnitOfEnergy
from homeassistant.helpers.restore_state import RestoreEntity
from homeassistant.helpers.event import async_call_later
from homeassistant.helpers.entity import DeviceInfo

from .const import DOMAIN, ATTR_CONSUMPTION, ATTR_PRODUCTION, ATTR_INJECTION
from .helpers.storage import load_initial_jump_flag, save_initial_jump_flag
from .helpers.statistics import purge_flat_states
from .helpers.translate import translate


async def async_setup_entry(hass, entry, async_add_entities):
    coordinator = hass.data[DOMAIN][entry.entry_id]["coordinator"]
    supply = entry.data["supplyNumber"]
    language = hass.config.language
    async_add_entities(
        [
            DeddieConsumptionSensor(coordinator, supply, language),
            DeddieProductionSensor(coordinator, supply, language),
            DeddieInjectionSensor(coordinator, supply, language),
        ]
    )


class _DeddieSensorBase(SensorEntity, RestoreEntity):
    """
    Template αισθητήρων για την παρακολούθηση της κατανάλωσης/παραγωγής/έγχυσης
    μέσω του DataUpdateCoordinator.
    - Σε νέο (fresh setup) config entry, ο αισθητήρας αγνοεί το restore state
      και ξεκινάει από 0.0.
    - Σε επανεκκινήσεις/reload/fresh not first (δηλαδή, όταν το persistent flag
      έχει οριστεί σε True), ο αισθητήρας αρχικοποιείται με την αποθηκευμένη
      κατάσταση μέσω του RestoreEntity.
    - Πραγματοποιεί purge flat states.
    - Παρέχει common extra_state_attributes formatting.
    """

    # Παραμετροποίηση αισθητήρα
    _attr_device_class = SensorDeviceClass.ENERGY
    _attr_state_class = "total_increasing"
    _attr_native_unit_of_measurement = UnitOfEnergy.KILO_WATT_HOUR
    _attr_has_entity_name = True
    _attr_suggested_display_precision = 2

    def __init__(
        self,
        coordinator,
        supply: str,
        language: str,
        attr_key: str,
        translation_key: str,
    ):
        self.coordinator = coordinator
        self._supply = supply
        self._lang = language
        self._attr_key = attr_key
        self._attr_translation_key = translation_key
        self._attr_translation_placeholders = {"supply": supply}
        self._attr_unique_id = f"{translation_key}_{supply}"
        self._total = 0.0
        self._fresh_install = False
        self._initial_jump_done_flag = False
        self._purge_unsub = None

    @property
    def available(self) -> bool:
        """
        Οι αισθητήρες παραγωγής/έγχυσης είναι διαθέσιμοι
        μόνο αν ο coordinator ανίχνευσε PV (has_pv=True).
        Ο αισθητήρας κατανάλωσης είναι πάντα διαθέσιμος.
        """
        # self._attr_key παίρνει τιμές "active", "produced" ή "injected"
        if self._attr_key in (ATTR_PRODUCTION, ATTR_INJECTION):
            return self.coordinator.has_pv
        return True

    async def async_added_to_hass(self):
        """
        Καταχώρηση του αισθητήρα και επαναφορά της κατάστασης.
        Φορτώνουμε το persistent flag για να αποφασίσουμε αν πρόκειται
        για fresh setup. Αν δεν έχει γίνει η πρώτη "jump" ενημέρωση
        (flag False), αγνοούμε το restore state και ξεκινάμε από 0.0.
        Αλλιώς, χρησιμοποιούμε την αποθηκευμένη κατάσταση.
        """
        # Φόρτωση του persistent flag για την παροχή
        self._initial_jump_done_flag = await load_initial_jump_flag(
            self.hass, self._supply, key=self._attr_key
        )
        if not self._initial_jump_done_flag:
            # Fresh setup: αρχικιποίηση από 0.0
            self.async_get_last_state = lambda: None
            self._fresh_install = True
            self._total = 0.0
        else:
            # fresh not fisrt (Normal restart/reload): Επαναφορά από restore
            last_state = await self.async_get_last_state()
            if last_state is None or last_state.state in (None, "unknown"):
                self._fresh_install = True
                self._total = 0.0
            else:
                self._fresh_install = False
                try:
                    self._total = float(last_state.state)
                except ValueError:
                    self._total = 0.0
                # Coordinator listener override: άμεση ενημέρωση του state (sos)
                if self.coordinator.data:
                    self._total = self.coordinator.data.get(self._attr_key, 0.0)
                    self._schedule_purge()

        # Πρώτη ενημέρωση του αισθητήρα με state
        await super().async_added_to_hass()
        self.async_write_ha_state()

        # Register listener για μελλοντικά updates
        self.async_on_remove(
            self.coordinator.async_add_listener(self._handle_coordinator_update)
        )

        # Fresh install delayed_update, τρέχει μόνο στην αρχική ενημέρωση
        if self._fresh_install:
            async_call_later(self.hass, 2, self._delayed_update)

    def _handle_coordinator_update(self):
        """Ενημερώνει τα state όταν ο coordinator φέρνει νέα δεδομένα."""
        new_total = (
            self.coordinator.data.get(self._attr_key, 0.0)
            if self.coordinator.data
            else 0.0
        )
        self._total = new_total
        self.async_write_ha_state()
        self._schedule_purge()

    async def _delayed_update(self, _now) -> None:
        """
        Μετά από delay, ενημερώνει το state με τα δεδομένα του
        coordinator και αποθηκεύει το flag.
        """
        self._total = (
            self.coordinator.data.get(self._attr_key, 0.0)
            if self.coordinator.data
            else 0.0
        )
        self.async_write_ha_state()
        self._schedule_purge()
        # Αποθήκευση του flag ώστε στις επανεκκινήσεις να χρησιμοποιείται
        # το restore state
        await save_initial_jump_flag(self.hass, self._supply, True, key=self._attr_key)

    def _schedule_purge(self) -> None:
        """Προγραμματίζει καθαρισμό flat states μετά από 5 λεπτά,
        μόνο αν δεν υπάρχει ήδη προγραμματισμένο."""
        if not self.available or self._purge_unsub is not None:
            return
        self._purge_unsub = async_call_later(self.hass, 300, self._async_purge)

    async def _async_purge(self, _now) -> None:
        """Ασύγχρονος callback που καλεί το purge_flat_states στο event loop
        και reset του handle."""
        self._purge_unsub = None
        await purge_flat_states(self.hass, self.entity_id, self._supply)

    @property
    def native_value(self) -> float:
        """Επιστρέφει την τρέχουσα τιμή κατανάλωσης."""
        return self._total

    @property
    def extra_state_attributes(self):
        """Επιστρέφει πρόσθετα attributes με πληροφορίες για την ενημέρωση."""
        latest_date = (
            self.coordinator.data.get(f"latest_date_{self._attr_key}")
            if self.coordinator.data
            else None
        )
        formatted_date = None
        if latest_date:
            try:
                dt_obj = datetime.strptime(latest_date, "%Y-%m-%d") - timedelta(days=1)
                formatted_date = dt_obj.strftime("%d/%m/%Y") + " 24:00"
            except ValueError:
                formatted_date = latest_date

        last_fetch = (
            self.coordinator.data.get(f"last_fetch_{self._attr_key}")
            if self.coordinator.data
            else None
        )
        formatted_fetch = None
        if last_fetch:
            try:
                fetch_obj = datetime.fromisoformat(last_fetch)
                formatted_fetch = fetch_obj.strftime("%d/%m/%Y %H:%M:%S")
            except ValueError:
                formatted_fetch = last_fetch

        return {
            translate("sensor.attr_until", self._lang): formatted_date,
            translate("sensor.attr_last_fetch", self._lang): formatted_fetch,
            translate("sensor.attr_info", self._lang): translate(
                "sensor.attr_info_value", self._lang
            ),
        }

    @property
    def device_info(self) -> DeviceInfo:
        """
        Επιστρέφει τα στοιχεία της “συσκευής” ώστε
        όλα τα sensors να εμφανίζονται κάτω από μία device.
        """
        return {
            "identifiers": {(DOMAIN, self._supply)},
            "manufacturer": "ΔΕΔΔΗΕ",
            "name": "DEDDIE",
            "model": "Deddie Meter",
            "sw_version": "1.1.0",
            "suggested_area": "Ηλεκτρικός πίνακας",
        }


class DeddieConsumptionSensor(_DeddieSensorBase):
    def __init__(self, coordinator, supply: str, language: str):
        super().__init__(
            coordinator,
            supply,
            language,
            ATTR_CONSUMPTION,
            "consumption",
        )


class DeddieProductionSensor(_DeddieSensorBase):
    def __init__(self, coordinator, supply: str, language: str):
        super().__init__(
            coordinator,
            supply,
            language,
            ATTR_PRODUCTION,
            "production",
        )


class DeddieInjectionSensor(_DeddieSensorBase):
    def __init__(self, coordinator, supply: str, language: str):
        super().__init__(
            coordinator,
            supply,
            language,
            ATTR_INJECTION,
            "injection",
        )
