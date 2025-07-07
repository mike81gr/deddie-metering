import sys
import types
import datetime
import pytest

# === Stub Home Assistant modules ===
sys.modules["homeassistant"] = types.ModuleType("homeassistant")
sys.modules["homeassistant.core"] = types.ModuleType("homeassistant.core")
homeassistant_core = sys.modules["homeassistant.core"]
setattr(homeassistant_core, "HomeAssistant", object)
setattr(homeassistant_core, "callback", lambda f: f)

sys.modules["homeassistant.components"] = types.ModuleType("homeassistant.components")
sys.modules["homeassistant.components.system_health"] = types.ModuleType(
    "homeassistant.components.system_health"
)
ha_system_health = sys.modules["homeassistant.components.system_health"]
setattr(ha_system_health, "async_check_can_reach_url", lambda hass, url: "ok")
setattr(
    ha_system_health,
    "SystemHealthRegistration",
    type("SystemHealthRegistration", (), {}),
)

# Global for the module under test
sh = None


# Dummy classes to simulate HA config entries
class DummyEntry:
    def __init__(self, title, options, data, entry_id="test_id"):
        self.title = title
        self.options = options
        self.data = data
        self.entry_id = entry_id


class DummyConfigEntries:
    def __init__(self, entries):
        self._entries = entries

    def async_entries(self, domain):
        return self._entries


class DummyHass:
    def __init__(self, entries):
        self.config_entries = DummyConfigEntries(entries)
        self.data = {
            sh.DOMAIN: {
                "translations": {
                    "system_health": {
                        "info": {"integration_version": "Έκδοση Ενσωμάτωσης"}
                    }
                }
            }
        }


@pytest.fixture(autouse=True)
def patch_dependencies(monkeypatch):
    # Import module under test after stubbing modules
    global sh
    import deddie_metering.system_health as module

    sh = module

    # Stub external dependencies: validate_credentials and load_last_update
    async def fake_validate(hass, token, supply, tax, class_type):
        return True

    async def fake_load_update(hass, supply, key):
        return datetime.datetime(2025, 5, 26, 0, 0)

    monkeypatch.setattr(sh, "validate_credentials", fake_validate)
    monkeypatch.setattr(sh, "load_last_update", fake_load_update)


def test_async_register_registers_info_and_return_value():
    class DummyRegister:
        def __init__(self):
            self.calls = []

        def async_register_info(self, callback, path=None):
            self.calls.append((callback, path))

    register = DummyRegister()
    result = sh.async_register(None, register)
    # Ensure the method registers info with the correct callback and path
    assert register.calls == [(sh.system_health_info, "/config/integrations")]
    # Ensure async_register returns None
    assert result is None


@pytest.mark.asyncio
async def test_system_health_info_single_entry():
    # Prepare a single dummy config entry
    entry = DummyEntry(
        title="Παροχή 123456789",
        options={"interval_hours": 4, "token": "tok123", "has_pv": False},
        data={"supplyNumber": "123456789", "taxNumber": "987654321"},
        entry_id="entry1",
    )
    hass = DummyHass([entry])

    # Invoke the system_health_info function
    info = await sh.system_health_info(hass)

    # One-time integration version field
    assert info.get("version") == sh.INTEGRATION_VERSION

    # Entry-specific fields
    assert info.get("name") == "Παροχή 123456789"
    assert info.get("api") == "ok"
    assert info.get("frequency") == "4 ώρες"
    assert info.get("token") is True
    assert info.get("has_pv") is False
    assert info.get("last_update") == "26/05/2025 00:00"

    # Validate no unexpected keys are present
    expected_keys = {
        "version",
        "name",
        "api",
        "frequency",
        "token",
        "has_pv",
        "last_update",
    }
    assert set(info.keys()) == expected_keys
