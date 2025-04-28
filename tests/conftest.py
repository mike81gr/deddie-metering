# type: ignore
import sys
import pytest
from unittest.mock import MagicMock
import datetime
from types import ModuleType
from pathlib import Path
import types
import types as _types

# 1) Dummy package homeassistant
homeassistant_mod = sys.modules.setdefault(
    "homeassistant", types.ModuleType("homeassistant")
)

# 2) Δημιουργούμε πραγματικό sub-package homeassistant.components
components_mod = types.ModuleType("homeassistant.components")
homeassistant_mod.components = components_mod
sys.modules["homeassistant.components"] = components_mod

# 3) Dummy module sqlalchemy.text
sqlalchemy_mod = types.ModuleType("sqlalchemy")
# απλά επιστρέφουμε το ίδιο το SQL κείμενο – στα tests δεν τρέχει πραγματική SQL
sqlalchemy_mod.text = lambda s: s
sys.modules["sqlalchemy"] = sqlalchemy_mod

# --- Stub voluptuous for config and options flows ---

vol = _types.ModuleType("voluptuous")
# Schema stub: returns schema definition
vol.Schema = lambda schema: schema
# Required and Optional stub: identity for key definitions
vol.Required = lambda *args, **kwargs: args[0]
vol.Optional = lambda *args, **kwargs: args[0]


# Range stub: accepts min/max, returns identity callable
class _Range:
    def __init__(self, min=None, max=None):
        pass

    def __call__(self, value):
        return value


vol.Range = _Range
# All stub: returns last validator or identity
vol.All = lambda *args: (args[-1] if args else (lambda v: v))
# Register stub module
sys.modules["voluptuous"] = vol

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "custom_components"))

# Δημιουργούμε ένα dummy module για το homeassistant.util.dt με τη μέθοδο now.
dummy_dt = ModuleType("homeassistant.util.dt")


def now() -> datetime.datetime:
    return datetime.datetime.now()


dummy_dt.now = now  # type: ignore[attr-defined]
sys.modules["homeassistant.util.dt"] = dummy_dt


# Δημιουργούμε μια minimal dummy έκδοση του module που παρέχει το ConfigFlow.
class DummyConfigFlow:
    def __init_subclass__(cls, **kwargs):
        pass

    async def async_set_unique_id(self, unique_id):
        return None

    def _abort_if_unique_id_configured(self):
        pass

    async def async_create_entry(self, title, data):
        return {"type": "create_entry", "title": title, "data": data}


# Dummy κλάσεις για ConfigEntry και OptionsFlow.
class DummyConfigEntry:
    pass


class DummyOptionsFlow:
    pass


dummy_config_entries = type("DummyModule", (), {"ConfigFlow": DummyConfigFlow})
config_entries_module = ModuleType("homeassistant.config_entries")
config_entries_module.ConfigFlow = DummyConfigFlow  # type: ignore[attr-defined]
config_entries_module.CONN_CLASS_CLOUD_POLL = "cloud_poll"  # type: ignore[attr-defined]
config_entries_module.ConfigFlowResult = dict  # type: ignore[attr-defined]
config_entries_module.ConfigEntry = DummyConfigEntry  # type: ignore[attr-defined]
config_entries_module.OptionsFlow = DummyOptionsFlow  # type: ignore[attr-defined]
sys.modules["homeassistant.config_entries"] = config_entries_module
sys.modules["homeassistant.const"] = MagicMock()
sys.modules["homeassistant.util"] = MagicMock()  # Χρησιμοποιεί το dummy για .util.dt
sys.modules["homeassistant.components"] = MagicMock()


class DummySensorEntity:
    def __init__(self, *args, **kwargs):
        pass

    async def async_added_to_hass(self):
        return None

    def async_write_ha_state(self):
        return None

    def async_on_remove(self, remove_callback):
        pass


sensor_module = ModuleType("homeassistant.components.sensor")
sensor_module.SensorEntity = DummySensorEntity  # type: ignore[attr-defined]
sys.modules["homeassistant.components.sensor"] = sensor_module


class DummyRestoreEntity:
    async def async_get_last_state(self):
        return None


restore_state_module = ModuleType("homeassistant.helpers.restore_state")
restore_state_module.RestoreEntity = DummyRestoreEntity  # type: ignore[attr-defined]
sys.modules["homeassistant.helpers.restore_state"] = restore_state_module


class DummyStore:
    def __init__(self, hass, version, key):
        pass

    async def async_load(self):
        return None

    async def async_save(self, data):
        pass


storage_module = ModuleType("homeassistant.helpers.storage")
storage_module.Store = DummyStore  # type: ignore[attr-defined]
sys.modules["homeassistant.helpers.storage"] = storage_module


class DummyDataUpdateCoordinator:
    async def async_config_entry_first_refresh(self):
        return None

    def async_add_listener(self, listener):
        return lambda: None

    async def async_request_refresh(self):
        return None

    async def async_shutdown(self):
        return None


update_coordinator_module = ModuleType("homeassistant.helpers.update_coordinator")
setattr(
    update_coordinator_module,
    "DataUpdateCoordinator",
    DummyDataUpdateCoordinator,  # type: ignore[attr-defined]
)
sys.modules["homeassistant.helpers.update_coordinator"] = update_coordinator_module
sys.modules["homeassistant.components.recorder"] = MagicMock()
sys.modules["homeassistant.components.recorder.statistics"] = MagicMock()
sys.modules["homeassistant.helpers"] = MagicMock()
sys.modules["homeassistant.helpers.typing"] = MagicMock()
sys.modules["homeassistant.helpers.aiohttp_client"] = MagicMock()
sys.modules["homeassistant.helpers.update_coordinator"] = MagicMock()
sys.modules["homeassistant.helpers.storage"] = MagicMock()
sys.modules["homeassistant.helpers.event"] = MagicMock()


# Δημιουργούμε μία dummy async_create που είναι synchronous και επιστρέφει None.
def dummy_async_create(*args, **kwargs):
    return None


# Δημιουργούμε το package homeassistant.components
components_pkg = types.ModuleType("homeassistant.components")
# Δημιουργούμε το persistent_notification sub-module
pn_mod = types.ModuleType("homeassistant.components.persistent_notification")
pn_mod.async_create = dummy_async_create
# Συνδέουμε το sub-module στο package
components_pkg.persistent_notification = pn_mod

# Καταχωρούμε και τα δύο στο sys.modules
sys.modules["homeassistant.components"] = components_pkg
sys.modules["homeassistant.components.persistent_notification"] = pn_mod

# Ενημερώνουμε το parent module ώστε getattr(homeassistant, 'components')
# να επιστρέφει το σωστό αντικείμενο
homeassistant_mod = sys.modules.setdefault(
    "homeassistant", types.ModuleType("homeassistant")
)
homeassistant_mod.components = components_pkg


"""
Δημιουργεί ένα dummy instance του Home Assistant χρησιμοποιώντας
 MagicMock για χρήση στα tests.
"""


@pytest.fixture
def hass():
    hass = MagicMock()
    hass.config = MagicMock()
    hass.config.language = "en"
    import asyncio

    hass.async_create_task = lambda coro: asyncio.get_event_loop().create_task(coro)
    return hass
