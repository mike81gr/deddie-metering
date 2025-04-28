import pytest
import datetime
from unittest.mock import MagicMock, AsyncMock

import deddie_metering
from deddie_metering import (
    async_setup_entry,
    update_listener,
    async_unload_entry,
    async_remove_entry,
)
from deddie_metering.const import DOMAIN


@pytest.mark.asyncio
async def test_async_setup_entry_fresh_install(monkeypatch, hass):
    # Use a real dict for hass.data
    hass.data = {}

    # Prepare a mock entry simulating fresh install (no previous data)
    entry = MagicMock()
    entry.data = {"supplyNumber": "123456789", "taxNumber": "987654321"}
    entry.options = {
        "token": "test_token",
        "initial_time": "01/01/2020",
        "interval_hours": 8,
    }
    entry.entry_id = "entry_id_1"

    # Simulate no persistent data
    monkeypatch.setattr(
        deddie_metering, "load_last_update", AsyncMock(return_value=None)
    )
    monkeypatch.setattr(
        deddie_metering, "load_last_total", AsyncMock(return_value=None)
    )

    # Spy on run_initial_batches
    called = {}

    async def fake_run_initial_batches(
        hass_arg, token_arg, supply_arg, tax_arg, initial_time_arg
    ):
        called["args"] = (hass_arg, token_arg, supply_arg, tax_arg, initial_time_arg)

    monkeypatch.setattr(
        deddie_metering, "run_initial_batches", fake_run_initial_batches
    )

    # Stub save_initial_jump_flag
    monkeypatch.setattr(deddie_metering, "save_initial_jump_flag", AsyncMock())

    # Stub the coordinator class
    class DummyCoordinator:
        def __init__(
            self,
            hass_arg,
            token_arg,
            supply_arg,
            tax_arg,
            update_interval_arg,
            skip_initial_refresh_arg,
        ):
            called["coord_init"] = (
                hass_arg,
                token_arg,
                supply_arg,
                tax_arg,
                update_interval_arg,
                skip_initial_refresh_arg,
            )

        async def async_config_entry_first_refresh(self):
            called["first_refresh"] = True

    monkeypatch.setattr(
        deddie_metering, "DeddieDataUpdateCoordinator", DummyCoordinator
    )

    # Stub platform forwarding
    hass.config_entries.async_forward_entry_setups = AsyncMock(return_value=None)

    # Run setup
    result = await async_setup_entry(hass, entry)

    # Assertions
    assert result is True
    assert "args" in called, "Initial run_initial_batches was not called"
    assert entry.entry_id in hass.data.get(
        DOMAIN, {}
    ), "Coordinator not stored in hass.data"
    assert "coord_init" in called, "Coordinator __init__ not called"
    assert called.get(
        "first_refresh", False
    ), "Coordinator.first_refresh was not invoked"


@pytest.mark.asyncio
async def test_update_listener_triggers_reload(hass):
    hass.data = {}
    entry = MagicMock()
    entry.entry_id = "entry_id_2"

    hass.config_entries.async_reload = AsyncMock()
    await update_listener(hass, entry)
    hass.config_entries.async_reload.assert_awaited_once_with(entry.entry_id)


@pytest.mark.asyncio
async def test_async_unload_and_remove_entry(monkeypatch, hass):
    hass.data = {}
    entry = MagicMock()
    entry.entry_id = "entry_id_3"
    entry.data = {"supplyNumber": "123456789"}

    # Prepare fake coordinator
    fake_coordinator = MagicMock()
    fake_coordinator.async_shutdown = AsyncMock()
    hass.data.setdefault(DOMAIN, {})[entry.entry_id] = {"coordinator": fake_coordinator}

    # Stub unload of sensor platform
    async def fake_unload(arg_entry, domain):
        return True

    hass.config_entries.async_forward_entry_unload = fake_unload

    # Test unload entry
    result_unload = await async_unload_entry(hass, entry)
    assert result_unload is True, "async_unload_entry should return True"
    fake_coordinator.async_shutdown.assert_awaited_once(),
    assert (
        entry.entry_id not in hass.data[DOMAIN]
    ), "Coordinator data was not removed after unload"

    # Prepare for remove
    hass.data.setdefault(DOMAIN, {})[entry.entry_id] = {}

    # Test remove entry
    result_remove = await async_remove_entry(hass, entry)
    assert result_remove is None


@pytest.mark.asyncio
async def test_async_setup_entry_existing_data(monkeypatch, hass):
    hass.data = {}
    entry = MagicMock()
    entry.data = {"supplyNumber": "111222333", "taxNumber": "444555666"}
    entry.options = {"token": "tkn", "initial_time": "01/01/2020", "interval_hours": 12}
    entry.entry_id = "eid_2"

    # Simulate existing persistent data
    saved_dt = datetime.datetime(2025, 1, 1)
    monkeypatch.setattr(
        deddie_metering, "load_last_update", AsyncMock(return_value=saved_dt)
    )
    monkeypatch.setattr(
        deddie_metering, "load_last_total", AsyncMock(return_value=42.5)
    )

    # Spy on run_initial_batches to ensure it's NOT called
    called = {}

    async def fake_run_initial_batches(*args, **kwargs):
        called["ran"] = True

    monkeypatch.setattr(
        deddie_metering, "run_initial_batches", fake_run_initial_batches
    )

    # Stub save_initial_jump_flag
    sjf = AsyncMock()
    monkeypatch.setattr(deddie_metering, "save_initial_jump_flag", sjf)

    # Stub coordinator
    class DummyCoord:
        def __init__(self, *args, **kwargs):
            called["coord_init"] = True

        async def async_config_entry_first_refresh(self):
            called["first_refresh"] = True

    monkeypatch.setattr(deddie_metering, "DeddieDataUpdateCoordinator", DummyCoord)

    hass.config_entries.async_forward_entry_setups = AsyncMock()

    result = await async_setup_entry(hass, entry)

    assert result is True
    # run_initial_batches δεν πρέπει να έχει κληθεί
    assert "ran" not in called
    # save_initial_jump_flag πρέπει να κληθεί με True
    sjf.assert_awaited_once_with(hass, entry.data["supplyNumber"], True)
    # coordinator δημιουργήθηκε και first_refresh εκτελέστηκε
    assert called.get("coord_init") and called.get("first_refresh")
    # έχει κάνει forward στο sensor
    hass.config_entries.async_forward_entry_setups.assert_awaited_once_with(
        entry, ["sensor"]
    )
