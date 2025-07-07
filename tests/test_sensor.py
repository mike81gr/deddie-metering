import sys
import types
import pytest
from unittest.mock import AsyncMock, MagicMock

from deddie_metering.const import ATTR_CONSUMPTION, DOMAIN
from deddie_metering.helpers.translate import translate
from deddie_metering.sensor import (
    async_setup_entry,
    DeddieConsumptionSensor,
    DeddieProductionSensor,
    DeddieInjectionSensor,
)


# Autouse fixture to stub homeassistant modules
@pytest.fixture(autouse=True)
def stub_homeassistant_modules():
    # Create dummy homeassistant package and helpers submodules
    ha_mod = types.ModuleType("homeassistant")
    helpers_mod = types.ModuleType("homeassistant.helpers")
    entity_mod = types.ModuleType("homeassistant.helpers.entity")
    event_mod = types.ModuleType("homeassistant.helpers.event")
    # Provide dummy DeviceInfo & async_call_later
    entity_mod.DeviceInfo = type("DeviceInfo", (), {})
    event_mod.async_call_later = lambda hass, delay, callback: callback
    # Assemble hierarchy
    helpers_mod.entity = entity_mod
    helpers_mod.event = event_mod
    ha_mod.helpers = helpers_mod
    sys.modules["homeassistant"] = ha_mod
    sys.modules["homeassistant.helpers"] = helpers_mod
    sys.modules["homeassistant.helpers.entity"] = entity_mod
    sys.modules["homeassistant.helpers.event"] = event_mod
    yield
    # Cleanup
    for mod in [
        "homeassistant.helpers.event",
        "homeassistant.helpers.entity",
        "homeassistant.helpers",
        "homeassistant",
    ]:
        sys.modules.pop(mod, None)


@pytest.mark.asyncio
async def test_fresh_install_sensor(monkeypatch, hass):
    coord = MagicMock()
    coord.data = {
        ATTR_CONSUMPTION: 5.5,
        f"latest_date_{ATTR_CONSUMPTION}": "2025-04-23",
        f"last_fetch_{ATTR_CONSUMPTION}": "2025-04-24T12:00:00",
    }
    coord.async_add_listener = MagicMock()

    monkeypatch.setattr(
        "deddie_metering.sensor.load_initial_jump_flag", AsyncMock(return_value=False)
    )
    save_flag = AsyncMock()
    monkeypatch.setattr("deddie_metering.sensor.save_initial_jump_flag", save_flag)

    sensor = DeddieConsumptionSensor(coord, "123456789", "en")
    sensor.hass = hass
    sensor._supply = "123456789"

    await sensor.async_added_to_hass()
    assert sensor.native_value == 0.0

    await sensor._delayed_update(None)
    assert sensor.native_value == 5.5
    save_flag.assert_called_once_with(hass, "123456789", True, key=ATTR_CONSUMPTION)


@pytest.mark.asyncio
async def test_restore_state_sensor(monkeypatch, hass):
    coord = MagicMock()
    coord.data = {
        ATTR_CONSUMPTION: 7.7,
        f"latest_date_{ATTR_CONSUMPTION}": "2025-04-20",
        f"last_fetch_{ATTR_CONSUMPTION}": "2025-04-21T15:30:00",
    }
    coord.async_add_listener = MagicMock()

    monkeypatch.setattr(
        "deddie_metering.sensor.load_initial_jump_flag", AsyncMock(return_value=True)
    )
    last_state = MagicMock(state="2.2")
    monkeypatch.setattr(
        DeddieConsumptionSensor,
        "async_get_last_state",
        AsyncMock(return_value=last_state),
    )

    sensor = DeddieConsumptionSensor(coord, "987654321", "en")
    sensor.hass = hass

    await sensor.async_added_to_hass()
    assert sensor.native_value == 7.7
    assert sensor._purge_unsub is not None
    attrs = sensor.extra_state_attributes
    assert attrs[translate("sensor.attr_until", "en")] == "19/04/2025 24:00"
    assert attrs[translate("sensor.attr_last_fetch", "en")] == "21/04/2025 15:30:00"


@pytest.mark.asyncio
async def test_initial_jump_flag_true_but_no_state(monkeypatch, hass):
    coord = MagicMock()
    coord.data = {ATTR_CONSUMPTION: 3.3}
    coord.async_add_listener = MagicMock()

    monkeypatch.setattr(
        "deddie_metering.sensor.load_initial_jump_flag", AsyncMock(return_value=True)
    )

    sensor = DeddieConsumptionSensor(coord, "111111111", "en")
    sensor.hass = hass

    await sensor.async_added_to_hass()
    assert sensor.native_value == 0.0
    assert sensor._fresh_install is True


@pytest.mark.asyncio
async def test_value_error_in_state_conversion(monkeypatch, hass):
    # Test that a non-numeric restored state triggers the
    # ValueError branch
    coord = MagicMock(data=None)
    coord.async_add_listener = MagicMock()
    monkeypatch.setattr(
        "deddie_metering.sensor.load_initial_jump_flag", AsyncMock(return_value=True)
    )
    bad_state = MagicMock(state="not-a-number")
    monkeypatch.setattr(
        DeddieConsumptionSensor,
        "async_get_last_state",
        AsyncMock(return_value=bad_state),
    )

    sensor = DeddieConsumptionSensor(coord, "123", "en")
    sensor.hass = hass

    await sensor.async_added_to_hass()
    assert sensor.native_value == 0.0


def test_device_info_property():
    # Test the device_info property covers identifiers
    # /manufacturer/name/model
    coord = MagicMock()
    sensor = DeddieConsumptionSensor(coord, "123456789", "en")
    expected = {
        "identifiers": {(DOMAIN, "123456789")},
        "manufacturer": "ΔΕΔΔΗΕ",
        "name": "DEDDIE",
        "model": "Deddie Meter",
        "sw_version": "1.1.0",
        "suggested_area": "Ηλεκτρικός πίνακας",
    }
    assert sensor.device_info == expected


@pytest.mark.asyncio
async def test_extra_state_attributes_formatting():
    coord = MagicMock(
        data={
            f"latest_date_{ATTR_CONSUMPTION}": "bad-date",
            f"last_fetch_{ATTR_CONSUMPTION}": "also-bad",
        }
    )
    sensor = DeddieConsumptionSensor(coord, "123", "en")
    attrs = sensor.extra_state_attributes
    key_until = translate("sensor.attr_until", "en")
    key_fetch = translate("sensor.attr_last_fetch", "en")
    assert attrs[key_until] == "bad-date"
    assert attrs[key_fetch] == "also-bad"


@pytest.mark.asyncio
async def test_async_purge_calls_helper(monkeypatch, hass):
    coord = MagicMock(data={ATTR_CONSUMPTION: 4.4})
    sensor = DeddieConsumptionSensor(coord, "321", "en")
    sensor.hass = hass
    sensor.entity_id = "sensor.test"

    called = AsyncMock()
    monkeypatch.setattr("deddie_metering.sensor.purge_flat_states", called)
    sensor._purge_unsub = None
    sensor._schedule_purge()
    await sensor._async_purge(None)
    called.assert_awaited_once_with(hass, "sensor.test", "321")


@pytest.mark.asyncio
async def test_handle_coordinator_update_with_none_data(hass):
    coord = MagicMock(data=None, async_add_listener=MagicMock())
    sensor = DeddieConsumptionSensor(coord, "111111111", "en")
    sensor.hass = hass
    sensor._total = 5.5
    sensor.entity_id = "sensor.test"
    sensor._purge_unsub = None

    sensor._handle_coordinator_update()
    assert sensor.native_value == 0.0
    assert sensor._purge_unsub is not None


@pytest.mark.asyncio
async def test_available_property(monkeypatch, hass):
    coord = MagicMock(has_pv=False)
    cons = DeddieConsumptionSensor(coord, "supply", "en")
    assert cons.available is True
    prod = DeddieProductionSensor(coord, "supply", "en")
    inj = DeddieInjectionSensor(coord, "supply", "en")
    assert prod.available is False
    assert inj.available is False
    coord.has_pv = True
    assert prod.available is True
    assert inj.available is True


def test_schedule_purge_idempotent():
    coord = MagicMock()
    sensor = DeddieConsumptionSensor(coord, "supply", "en")
    sentinel = object()
    sensor._purge_unsub = sentinel
    sensor._schedule_purge()
    assert sensor._purge_unsub is sentinel


@pytest.mark.asyncio
async def test_async_setup_entry(monkeypatch, hass):
    hass = MagicMock()
    entry = MagicMock()
    entry.entry_id = "entry_id"
    entry.data = {"supplyNumber": "sup123"}
    coord = MagicMock()
    hass.data = {DOMAIN: {entry.entry_id: {"coordinator": coord}}}
    added = []

    def add_entities(entities):
        added.extend(entities)

    await async_setup_entry(hass, entry, add_entities)
    assert len(added) == 3
    types_set = {type(e) for e in added}
    assert DeddieConsumptionSensor in types_set
    assert DeddieProductionSensor in types_set
    assert DeddieInjectionSensor in types_set
