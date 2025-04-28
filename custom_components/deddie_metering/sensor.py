from datetime import datetime, timedelta
from homeassistant.components.sensor import SensorEntity
from homeassistant.const import UnitOfEnergy
from homeassistant.helpers.restore_state import RestoreEntity
from homeassistant.helpers.event import async_call_later

from .const import DOMAIN
from .storage import load_initial_jump_flag, save_initial_jump_flag
from .statistics_helper import purge_flat_states
from .helpers.translate import translate


async def async_setup_entry(hass, entry, async_add_entities):
    coordinator = hass.data[DOMAIN][entry.entry_id]["coordinator"]
    supply = entry.data["supplyNumber"]
    language = hass.config.language
    async_add_entities([DeddieConsumptionSensor(coordinator, supply, language)])


class DeddieConsumptionSensor(SensorEntity, RestoreEntity):
    """
    Αισθητήρας για την παρακολούθηση της κατανάλωσης μέσω του DataUpdateCoordinator.

    - Σε νέο (fresh setup) config entry, ο αισθητήρας αγνοεί το restore state
      και ξεκινάει από 0.0.
    - Σε επανεκκινήσεις/reload/fresh_not_first (δηλαδή, όταν το persistent flag
      έχει οριστεί σε True),
      ο αισθητήρας αρχικοποιείται με την αποθηκευμένη κατάσταση μέσω του RestoreEntity.
    """

    # Παραμετροποίηση αισθητήρα

    _attr_has_entity_name = True
    _attr_translation_key = "consumption"

    def __init__(self, coordinator, supply: str, language: str):
        self.coordinator = coordinator
        self._supply = supply
        self._attr_translation_placeholders = {"supply": supply}
        self._lang = language
        self._attr_unique_id = f"sensor.deddie_consumption_{supply}"
        self._attr_device_class = "energy"
        self._attr_state_class = "total_increasing"
        self._attr_native_unit_of_measurement = UnitOfEnergy.KILO_WATT_HOUR
        self._total_kwh = 0.0
        self._fresh_install = False
        self._initial_jump_done_flag = False
        self._purge_unsub = None

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
            self.hass, self._supply
        )

        if self._initial_jump_done_flag is False:
            # Fresh setup: αγνοούμε restore, ξεκινάμε από 0.0
            self.async_get_last_state = lambda: None
            self._fresh_install = True
            self._total_kwh = 0.0
        else:
            # Normal restart/reload/fresh not fisrt: επαναφορά από restore
            last_state = await self.async_get_last_state()
            if last_state is None or last_state.state in (None, "unknown"):
                self._fresh_install = True
                self._total_kwh = 0.0
            else:
                self._fresh_install = False
                try:
                    self._total_kwh = float(last_state.state)
                except ValueError:
                    self._total_kwh = 0.0
                # Coordinator override: άμεση ενημέρωση του state από
                # τoν coordinator (sos)
                if self.coordinator.data:
                    self._total_kwh = self.coordinator.data.get("total_kwh", 0.0)
                    # Εκκινούμε την _schedule_purge.
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
            self._schedule_delayed_update()

    def _handle_coordinator_update(self):
        """Ενημερώνει το state όταν ο coordinator φέρνει νέα δεδομένα."""
        new_total = (
            self.coordinator.data.get("total_kwh", 0.0)
            if self.coordinator.data
            else 0.0
        )
        self._total_kwh = new_total
        self.async_write_ha_state()
        self._schedule_purge()

    def _schedule_delayed_update(self) -> None:
        """Προγραμματίζει την πρώτη delayed ενημέρωση (fresh setup)."""
        async_call_later(self.hass, 2, self._delayed_update)

    async def _delayed_update(self, _now) -> None:
        """
        Μετά από delay, ενημερώνει το state με τα δεδομένα του
        coordinator και αποθηκεύει το flag.
        """
        self._total_kwh = (
            self.coordinator.data.get("total_kwh", 0.0)
            if self.coordinator.data
            else 0.0
        )
        self.async_write_ha_state()
        self._schedule_purge()
        # Αποθήκευση του flag ώστε στις επανεκκινήσεις να χρησιμοποιείται
        # το restore state
        await save_initial_jump_flag(self.hass, self._supply, True)

    def _schedule_purge(self) -> None:
        """Προγραμματίζει καθαρισμό flat states μετά από 5 λεπτά,
        ΜΟΝΟ αν δεν υπάρχει ήδη προγραμματισμένο."""
        if self._purge_unsub is not None:
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
        return self._total_kwh

    @property
    def extra_state_attributes(self):
        """Επιστρέφει πρόσθετα attributes με πληροφορίες για την ενημέρωση."""
        latest_date = (
            self.coordinator.data.get("latest_date") if self.coordinator.data else None
        )
        formatted_date = None
        if latest_date:
            try:
                dt_obj = datetime.strptime(latest_date, "%Y-%m-%d") - timedelta(days=1)
                formatted_date = dt_obj.strftime("%d/%m/%Y") + " 24:00"
            except ValueError:
                formatted_date = latest_date

        last_fetch = (
            self.coordinator.data.get("last_fetch") if self.coordinator.data else None
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
