import types
import pytest
from unittest.mock import AsyncMock, MagicMock, call
from deddie_metering.sensor import DeddieConsumptionSensor
from deddie_metering.helpers.translate import translate


# event helper
event_mod = types.ModuleType("homeassistant.helpers.event")


def async_call_later(hass, delay, callback):
    return callback


@pytest.mark.asyncio
async def test_fresh_install_sensor(monkeypatch, hass):

    # Arrange: dummy coordinator with sample data
    coord = MagicMock()
    coord.data = {
        "total_kwh": 5.5,
        "latest_date": "2025-04-23",
        "last_fetch": "2025-04-24T12:00:00",
    }
    coord.async_add_listener = MagicMock()

    # Patch storage flags
    monkeypatch.setattr(
        "deddie_metering.sensor.load_initial_jump_flag", AsyncMock(return_value=False)
    )
    save_flag = AsyncMock()
    monkeypatch.setattr("deddie_metering.sensor.save_initial_jump_flag", save_flag)

    # Instantiate sensor and attach hass
    sensor = DeddieConsumptionSensor(coord, "123456789", "en")
    sensor.hass = hass

    # Act: simulate addition to hass
    await sensor.async_added_to_hass()
    # Assert initial native_value (fresh install) is zero
    assert sensor.native_value == 0.0

    # Act: simulate delayed update callback
    await sensor._delayed_update(None)
    # Assert state updated to coordinator data
    assert sensor.native_value == 5.5
    # Assert initial jump flag saved correctly
    save_flag.assert_called_once_with(hass, "123456789", True)


@pytest.mark.asyncio
async def test_restore_state_sensor(monkeypatch, hass):
    # Arrange: dummy coordinator with sample data
    coord = MagicMock()
    coord.data = {
        "total_kwh": 7.7,
        "latest_date": "2025-04-20",
        "last_fetch": "2025-04-21T15:30:00",
    }
    coord.async_add_listener = MagicMock()

    # Simulate that the initial jump flag was already set
    monkeypatch.setattr(
        "deddie_metering.sensor.load_initial_jump_flag", AsyncMock(return_value=True)
    )
    # Simulate a saved last state
    last_state = MagicMock(state="2.2")
    monkeypatch.setattr(
        DeddieConsumptionSensor,
        "async_get_last_state",
        AsyncMock(return_value=last_state),
    )

    # Instantiate sensor and attach hass
    sensor = DeddieConsumptionSensor(coord, "987654321", "en")
    sensor.hass = hass

    # Act: simulate addition to hass
    await sensor.async_added_to_hass()
    # Assert that sensor state reflects coordinator data
    assert sensor.native_value == 7.7

    # Inspect extra state attributes formatting
    attrs = sensor.extra_state_attributes
    assert attrs["Data up to:"] == "19/04/2025 24:00"
    assert attrs["Last API fetch:"] == "21/04/2025 15:30:00"

    # Ensure purge scheduled for flat states
    assert sensor._purge_unsub is not None


# New test: flag true but no last state
@pytest.mark.asyncio
async def test_initial_jump_flag_true_but_no_state(monkeypatch, hass):
    # Arrange
    coord = MagicMock()
    coord.data = {"total_kwh": 3.3}
    coord.async_add_listener = MagicMock()

    # initial_jump_flag True
    monkeypatch.setattr(
        "deddie_metering.sensor.load_initial_jump_flag", AsyncMock(return_value=True)
    )
    # async_get_last_state returns None
    monkeypatch.setattr(
        DeddieConsumptionSensor, "async_get_last_state", AsyncMock(return_value=None)
    )

    sensor = DeddieConsumptionSensor(coord, "111111111", "en")
    sensor.hass = hass

    # Act
    await sensor.async_added_to_hass()
    # Should treat as fresh install
    assert sensor.native_value == 0.0
    assert sensor._fresh_install is True


# New test: handle coordinator update
@pytest.mark.asyncio
async def test_handle_coordinator_update(monkeypatch, hass):
    # Arrange
    coord = MagicMock()
    coord.data = None
    coord.async_add_listener = MagicMock()
    sensor = DeddieConsumptionSensor(coord, "222222222", "en")
    sensor.hass = hass
    # Set initial total
    sensor._total_kwh = 1.0
    sensor.entity_id = "sensor.test"

    # Stub async_call_later for purge
    # from homeassistant.helpers.event import async_call_later

    # Simulate coordinator update
    coord.data = {"total_kwh": 9.9}

    # Act
    sensor._handle_coordinator_update()

    # Assert
    assert sensor._total_kwh == 9.9
    assert callable(sensor._purge_unsub)


@pytest.mark.asyncio
async def test_extra_state_attributes_formatting(monkeypatch, hass):
    coord = MagicMock(data={"latest_date": "bad-date", "last_fetch": "also-bad"})
    sensor = DeddieConsumptionSensor(coord, "123", "en")
    # δεν χρειάζεται να καλέσουμε async_added_to_hass για property
    attrs = sensor.extra_state_attributes
    assert attrs["Data up to:"] == "bad-date"
    assert attrs["Last API fetch:"] == "also-bad"


@pytest.mark.asyncio
async def test_async_purge_calls_helper(monkeypatch, hass):
    coord = MagicMock(data={"total_kwh": 4.4})
    sensor = DeddieConsumptionSensor(coord, "321", "en")
    sensor.hass = hass
    sensor.entity_id = "sensor.test"  # <— εδώ ορίζουμε το entity_id

    called = AsyncMock()
    monkeypatch.setattr("deddie_metering.sensor.purge_flat_states", called)

    # Simulate that purge was scheduled
    sensor._purge_unsub = None
    sensor._schedule_purge()

    # Εκτελούμε το callback
    await sensor._async_purge(None)

    called.assert_awaited_once_with(hass, "sensor.test", "321")


@pytest.mark.asyncio
async def test_handle_coordinator_update_with_none_data(monkeypatch, hass):
    coord = MagicMock(data=None, async_add_listener=MagicMock())
    sensor = DeddieConsumptionSensor(coord, "111111111", "en")
    sensor.hass = hass
    # set a non-zero initial total
    sensor._total_kwh = 5.5
    sensor.entity_id = "sensor.test"
    sensor._purge_unsub = None

    # Act
    sensor._handle_coordinator_update()

    # Assert native_value reset to 0.0 and purge scheduled
    assert sensor._total_kwh == 0.0
    assert sensor._purge_unsub is not None


@pytest.mark.asyncio
async def test_delayed_update_saves_flag_each_time(monkeypatch, hass):
    coord = MagicMock(data={"total_kwh": 2.2})
    sensor = DeddieConsumptionSensor(coord, "222222222", "en")
    sensor.hass = hass

    # Patch save_initial_jump_flag
    save_flag = AsyncMock()
    monkeypatch.setattr("deddie_metering.sensor.save_initial_jump_flag", save_flag)

    # Simulate fresh install delayed update twice
    await sensor._delayed_update(None)
    await sensor._delayed_update(None)

    # Should save flag on each call
    assert save_flag.await_count == 2
    save_flag.assert_has_awaits(
        [call(hass, "222222222", True), call(hass, "222222222", True)]
    )


def test_extra_state_attributes_with_no_data():
    coord = MagicMock(data=None)
    sensor = DeddieConsumptionSensor(coord, "333333333", "en")
    # No hass needed for property access
    attrs = sensor.extra_state_attributes

    assert attrs["Data up to:"] is None
    assert attrs["Last API fetch:"] is None
    assert attrs["Info:"] == "The data is not LIVE"


def test_extra_state_attributes_translation_el():
    coord = MagicMock(data=None)
    sensor = DeddieConsumptionSensor(coord, "444444444", "el")
    attrs = sensor.extra_state_attributes

    # Greek keys and values
    key_until = translate("sensor.attr_until", "el")
    key_fetch = translate("sensor.attr_last_fetch", "el")
    key_info = translate("sensor.attr_info", "el")
    info_value = translate("sensor.attr_info_value", "el")

    assert key_until in attrs and attrs[key_until] is None
    assert key_fetch in attrs and attrs[key_fetch] is None
    assert key_info in attrs and attrs[key_info] == info_value
