# type: ignore
import sys
import pytest
from unittest.mock import MagicMock
from types import ModuleType
from pathlib import Path
import types
import types as _types
import datetime
import tracemalloc
import homeassistant.helpers as _helpers_pkg

# ==== STUB HOMEASSISTANT & homeassistant.helpers ====
sys.modules.setdefault("homeassistant", types.ModuleType("homeassistant"))
sys.modules.setdefault(
    "homeassistant.helpers", types.ModuleType("homeassistant.helpers")
)
# Stub για homeassistant.helpers.entity_registry
entity_registry_mod = types.ModuleType("homeassistant.helpers.entity_registry")
entity_registry_mod.async_get = lambda hass: None
entity_registry_mod.async_get_entity_id = lambda **kwargs: None
entity_registry_mod.async_update_entity = lambda *args, **kwargs: None
sys.modules["homeassistant.helpers.entity_registry"] = entity_registry_mod
_helpers_pkg.entity_registry = entity_registry_mod
# Stub για homeassistant.helpers.aiohttp
aiohttp_compat_mod = types.ModuleType("homeassistant.helpers.aiohttp_compat")
aiohttp_compat_mod.restore_original_aiohttp_cancel_behavior = lambda: None
sys.modules["homeassistant.helpers.aiohttp_compat"] = aiohttp_compat_mod
# Stub για homeassistant.helpers.json
json_mod = types.ModuleType("homeassistant.helpers.json")
json_mod.json_dumps = lambda obj: None
sys.modules["homeassistant.helpers.json"] = json_mod
_helpers_pkg.json = json_mod
# Stub για homeassistant.helpers.frame
frame_mod = types.ModuleType("homeassistant.helpers.frame")
frame_mod.report = lambda *args, **kwargs: None
sys.modules["homeassistant.helpers.frame"] = frame_mod
_helpers_pkg.frame = frame_mod

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "custom_components"))
tracemalloc.start(10)


@pytest.fixture
def hass():
    return MagicMock()


# 1) Dummy package homeassistant
homeassistant_mod = sys.modules.setdefault(
    "homeassistant", types.ModuleType("homeassistant")
)

# 2) Δημιουργούμε πραγματικό sub-package homeassistant.components
components_mod = types.ModuleType("homeassistant.components")
homeassistant_mod.components = components_mod
sys.modules["homeassistant.components"] = components_mod

# 3) Stub για το module homeassistant.data_entry_flow
data_entry_flow_mod = ModuleType("homeassistant.data_entry_flow")
# FlowResult πρέπει να υπάρχει για options_flow και config_flow
data_entry_flow_mod.FlowResult = dict
sys.modules["homeassistant.data_entry_flow"] = data_entry_flow_mod

# 4) Dummy module sqlalchemy.text
sqlalchemy_mod = types.ModuleType("sqlalchemy")
# απλά επιστρέφουμε το ίδιο το SQL κείμενο – στα tests δεν τρέχει πραγματική SQL
sqlalchemy_mod.text = lambda s: s
sys.modules["sqlalchemy"] = sqlalchemy_mod

# 5) Stub homeassistant.util για options flow
util_mod = types.ModuleType("homeassistant.util")
util_mod.__path__ = []
sys.modules["homeassistant.util"] = util_mod
# Stub για homeassistant.util.location
location_mod = types.ModuleType("homeassistant.util.location")
sys.modules["homeassistant.util.location"] = location_mod
util_mod.location = location_mod
# Stub για homeassistant.util.async_
async_mod = types.ModuleType("homeassistant.util.async_")
async_mod.protect_loop = lambda loop, strict=False, *args, **kwargs: loop
async_mod.cancelling = lambda func: func
async_mod.run_callback_threadsafe = lambda hass, callback, *args, **kwargs: callback(
    *args, **kwargs
)
async_mod.shutdown_run_callback_threadsafe = lambda *args, **kwargs: None
sys.modules["homeassistant.util.async_"] = async_mod
# Stub για homeassistant.util.json (JsonObjectType)
json_util_mod = types.ModuleType("homeassistant.util.json")


class JsonObjectType:
    pass


json_util_mod.JsonObjectType = JsonObjectType
sys.modules["homeassistant.util.json"] = json_util_mod
util_mod.json = json_util_mod
# Stub για homeassistant.util.read_only_dict
read_only_mod = types.ModuleType("homeassistant.util.read_only_dict")
read_only_mod.ReadOnlyDict = dict
sys.modules["homeassistant.util.read_only_dict"] = read_only_mod
util_mod.read_only_dict = read_only_mod
# Stub για homeassistant.util.timeout (TimeoutManager)
timeout_mod = types.ModuleType("homeassistant.util.timeout")
timeout_mod.TimeoutManager = object
sys.modules["homeassistant.util.timeout"] = timeout_mod
util_mod.timeout = timeout_mod
# Stub για homeassistant.util.ulid
ulid_mod = types.ModuleType("homeassistant.util.ulid")
ulid_mod.ulid = lambda: None
ulid_mod.ulid_at_time = lambda timestamp: None
sys.modules["homeassistant.util.ulid"] = ulid_mod
util_mod.ulid = ulid_mod
# Stub για homeassistant.util.unit_system
unit_system_mod = types.ModuleType("homeassistant.util.unit_system")
unit_system_mod.METRIC_SYSTEM = object()
unit_system_mod.US_CUSTOMARY_SYSTEM = object()
unit_system_mod.UnitSystem = type("UnitSystem", (), {})
unit_system_mod._CONF_UNIT_SYSTEM_IMPERIAL = "imperial"
unit_system_mod._CONF_UNIT_SYSTEM_METRIC = "metric"
unit_system_mod._CONF_UNIT_SYSTEM_US_CUSTOMARY = "us_customary"
unit_system_mod.get_unit_system = lambda hass: unit_system_mod.METRIC_SYSTEM
sys.modules["homeassistant.util.unit_system"] = unit_system_mod
util_mod.unit_system = unit_system_mod
# Stub για homeassistant.util.uuid
uuid_mod = types.ModuleType("homeassistant.util.uuid")
# dummy συνάρτηση, δεν χρησιμοποιείται στα tests
uuid_mod.uuid = lambda: "00000000-0000-0000-0000-000000000000"
sys.modules["homeassistant.util.uuid"] = uuid_mod
util_mod.uuid = uuid_mod

# 6) Stub voluptuous για config flows και options flows
vol = _types.ModuleType("voluptuous")
# Schema stub: returns schema definition
vol.Schema = lambda schema: schema
# Required and Optional stub: identity for key definitions
vol.Required = lambda *args, **kwargs: args[0]
vol.Optional = lambda *args, **kwargs: args[0]

# 7) Stub για το module homeassistant.const
const_mod = types.ModuleType("homeassistant.const")
const_mod.__version__ = "2023.11.1"


class DummyUnitOfEnergy:
    KILO_WATT_HOUR = "kWh"


const_mod.UnitOfEnergy = DummyUnitOfEnergy
const_mod.ATTR_DOMAIN = "domain"
const_mod.ATTR_FRIENDLY_NAME = "friendly_name"
const_mod.ATTR_SERVICE = "service"
const_mod.ATTR_SERVICE_DATA = "service data"
const_mod.COMPRESSED_STATE_ATTRIBUTES = "compressed state attributes"
const_mod.COMPRESSED_STATE_CONTEXT = "compressed state context"
const_mod.COMPRESSED_STATE_LAST_CHANGED = "compressed state last changed"
const_mod.COMPRESSED_STATE_LAST_UPDATED = "compressed state last updated"
const_mod.COMPRESSED_STATE_STATE = "compressed state state"
const_mod.EVENT_CALL_SERVICE = "event call sercice"
const_mod.EVENT_CORE_CONFIG_UPDATE = "event core config update"
const_mod.EVENT_HOMEASSISTANT_CLOSE = "event homeassistant close"
const_mod.EVENT_HOMEASSISTANT_FINAL_WRITE = "event homeassistant final write"
const_mod.EVENT_HOMEASSISTANT_START = "event homeassistant start"
const_mod.EVENT_HOMEASSISTANT_STARTED = "event homeassistant started"
const_mod.EVENT_HOMEASSISTANT_STOP = "event homeassistant stop"
const_mod.EVENT_SERVICE_REGISTERED = "event service registered"
const_mod.EVENT_SERVICE_REMOVED = "event service removed"
const_mod.EVENT_STATE_CHANGED = "event state changed"
const_mod.LENGTH_METERS = "length meters"
const_mod.MATCH_ALL = "match all"
const_mod.MAX_LENGTH_EVENT_EVENT_TYPE = "max length event event_type"
const_mod.MAX_LENGTH_STATE_STATE = "max length state state"
const_mod.MAX_LENGTH_STATE_STATE = "max length state state"
sys.modules["homeassistant.const"] = const_mod


# 8) Stub για το range με accepts min/max
class _Range:
    def __init__(self, min=None, max=None):
        pass


vol.Range = _Range
# All stub: returns last validator or identity
vol.All = lambda *args: (args[-1] if args else (lambda v: v))
# Register stub module
sys.modules["voluptuous"] = vol

# 9) Dummy module για το homeassistant.util.dt
dummy_dt = ModuleType("homeassistant.util.dt")
dummy_dt.now = lambda: datetime.datetime.now()
dummy_dt.utcnow = lambda: datetime.datetime.utcnow()
dummy_dt.as_local = lambda dt: dt
dummy_dt.parse_datetime = lambda s: datetime.datetime.fromisoformat(s)
sys.modules["homeassistant.util.dt"] = dummy_dt


# 10) Dummy κλάση για το configflow.
class DummyConfigFlow:
    def __init_subclass__(cls, **kwargs):
        pass


# 11) Dummy κλάση για ConfigEntry.
class DummyConfigEntry:
    pass


# 12) Dummy κλάση για OptionsFlow.
class DummyOptionsFlow:
    pass


dummy_config_entries = type("DummyModule", (), {"ConfigFlow": DummyConfigFlow})
config_entries_module = ModuleType("homeassistant.config_entries")
config_entries_module.ConfigFlow = DummyConfigFlow
config_entries_module.CONN_CLASS_CLOUD_POLL = "cloud_poll"
config_entries_module.ConfigFlowResult = dict
config_entries_module.ConfigEntry = DummyConfigEntry
config_entries_module.OptionsFlow = DummyOptionsFlow
# Provide HANDLERS registry needed by config_flow
config_entries_module.HANDLERS = types.SimpleNamespace(
    register=lambda domain: (lambda cls: cls)
)
sys.modules["homeassistant.config_entries"] = config_entries_module


# 13) Dummy κλάση για sensor entity
class DummySensorEntity:
    async def async_added_to_hass(self):
        return None

    def async_write_ha_state(self):
        return None

    def async_on_remove(self, remove_callback):
        pass


# 14) Dummy κλάση για το SensorDeviceClass
class DummySensorDeviceClass:
    ENERGY = "energy"


sensor_module = ModuleType("homeassistant.components.sensor")
sensor_module.SensorEntity = DummySensorEntity
sensor_module.SensorDeviceClass = DummySensorDeviceClass
sys.modules["homeassistant.components.sensor"] = sensor_module


# 16) Dummy κλάση για restore entity
class DummyRestoreEntity:
    async def async_get_last_state(self):
        return None


restore_state_module = ModuleType("homeassistant.helpers.restore_state")
restore_state_module.RestoreEntity = DummyRestoreEntity
sys.modules["homeassistant.helpers.restore_state"] = restore_state_module


# 17) Dummy κλάση για το store
class DummyStore:
    def __init__(self, hass, version, key):
        pass

    async def async_load(self):
        return None


storage_module = ModuleType("homeassistant.helpers.storage")
storage_module.Store = DummyStore
sys.modules["homeassistant.helpers.storage"] = storage_module


# 18) Dummy κλάση για το UpdateCoordinator.
class DummyDataUpdateCoordinator:
    pass


update_coordinator_module = ModuleType("homeassistant.helpers.update_coordinator")
setattr(update_coordinator_module, "DataUpdateCoordinator", DummyDataUpdateCoordinator)
# Provide dummy UpdateFailed for coordinator imports
update_coordinator_module.UpdateFailed = Exception
sys.modules["homeassistant.helpers.update_coordinator"] = update_coordinator_module

# Stub homeassistant.helpers as real package with needed submodules
helpers_pkg = types.ModuleType("homeassistant.helpers")
helpers_pkg.__path__ = []

# entity submodule for DeviceInfo
entity_mod = types.ModuleType("homeassistant.helpers.entity")
entity_mod.DeviceInfo = type("DeviceInfo", (), {})

# event submodule for async_call_later
event_mod = types.ModuleType("homeassistant.helpers.event")
event_mod.async_call_later = lambda hass, delay, callback: callback

# aiohttp_client submodule for async_get_clientsession
aiohttp_mod = types.ModuleType("homeassistant.helpers.aiohttp_client")
aiohttp_mod.async_get_clientsession = lambda hass: None

# Attach submodules to helpers_pkg
helpers_pkg.entity = entity_mod
helpers_pkg.event = event_mod
helpers_pkg.aiohttp_client = aiohttp_mod

# Register modules in sys.modules
sys.modules["homeassistant.helpers"] = helpers_pkg
sys.modules["homeassistant.helpers.entity"] = entity_mod
sys.modules["homeassistant.helpers.event"] = event_mod
sys.modules["homeassistant.helpers.aiohttp_client"] = aiohttp_mod

sys.modules["homeassistant.components.recorder"] = MagicMock()
sys.modules["homeassistant.components.recorder.statistics"] = MagicMock()

# 19) Stub persistent_notification component για config_flow και options_flow
persistent_notification_mod = types.ModuleType(
    "homeassistant.components.persistent_notification"
)
persistent_notification_mod.async_create = lambda *args, **kwargs: None
sys.modules["homeassistant.components.persistent_notification"] = (
    persistent_notification_mod
)
components_mod.persistent_notification = persistent_notification_mod


# 20) Stub για homeassistant.helpers.entity_registry
entity_registry_mod = types.ModuleType("homeassistant.helpers.entity_registry")
