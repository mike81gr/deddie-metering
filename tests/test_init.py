import sys
import types
import pytest
from unittest.mock import MagicMock, AsyncMock

import deddie_metering
from deddie_metering import (
    async_migrate_entry,
    async_setup_entry,
    update_listener,
    async_unload_entry,
    async_remove_entry,
)
from deddie_metering.const import (
    DOMAIN,
    CONF_HAS_PV,
    ATTR_CONSUMPTION,
    ATTR_PRODUCTION,
    ATTR_INJECTION,
)
from deddie_metering.helpers.translate import translate


@pytest.mark.asyncio
async def test_async_migrate_entry_with_pv(monkeypatch, hass):
    """
    Migration από v1.1 σε v1.2 πρέπει να ανιχνεύσει PV (validate_credentials
    επιστρέφει μη κενή λίστα), να στείλει notification, να ενημερώσει το
    entry.options με has_pv=True και να αφαιρέσει το παλιό entity.
    """
    # 1) Προετοιμασία ConfigEntry stub
    entry = MagicMock()
    entry.version = 1
    entry.minor_version = 0
    entry.options = {"token": "tokval"}
    entry.data = {"supplyNumber": "SUPX", "taxNumber": "TAXX"}

    # 2) Stub για validate_credentials → non-empty list ⇒ has_pv=True
    fake_validate = AsyncMock(return_value=[{"dummy": 1}])
    monkeypatch.setattr(deddie_metering, "validate_credentials", fake_validate)

    # 3) Stub για persistent notification
    pn_mod = types.ModuleType("homeassistant.components.persistent_notification")
    stub_pn = AsyncMock()
    pn_mod.async_create = stub_pn
    sys.modules["homeassistant.components.persistent_notification"] = pn_mod

    # 4) Stub για update_entry
    called_update = []

    def fake_update(entry_obj, options=None, minor_version=None, version=None):
        called_update.append((entry_obj, options, minor_version, version))
        return None

    hass.config_entries.async_update_entry = fake_update

    # 5) Stub registry
    fake_registry = MagicMock()
    old_id = f"sensor.deddie_consumption_{entry.data['supplyNumber']}"
    fake_registry.async_get_entity_id.return_value = old_id
    # async_update_entity καλείται συγχρονικά, οπότε χρησιμοποιούμε MagicMock
    fake_registry.async_update_entity = MagicMock()
    monkeypatch.setattr(deddie_metering.er, "async_get", lambda h: fake_registry)

    # 6) Συλλογή tasks ώστε να μην μείνουν un-awaited
    tasks = []
    hass.async_create_task = lambda coro: tasks.append(coro)

    # 7) Εκτέλεση migration
    monkeypatch.setattr(
        deddie_metering, "save_initial_jump_flag", AsyncMock(return_value=None)
    )
    result = await async_migrate_entry(hass, entry)
    assert result is True

    # 8) Εκτέλεση τυχόν scheduled coroutines (notification + removal)
    for task in tasks:
        await task

    # 9) Έλεγχος κλήσης validate_credentials
    fake_validate.assert_awaited_once_with(
        hass,
        entry.options["token"],
        entry.data["supplyNumber"],
        entry.data["taxNumber"],
        ATTR_PRODUCTION,
    )

    # 10) Έλεγχος persistent notification
    stub_pn.assert_awaited_once_with(
        hass,
        translate("init.pv_detected_message", hass.config.language),
        title=translate(
            "init.pv_detected_title",
            hass.config.language,
            supply=entry.data["supplyNumber"],
        ),
        notification_id="deddie_pv_detected",
    )

    # 11) Έλεγχος ενημέρωσης config entry με has_pv=True
    expected_opts = {**{"token": "tokval"}, CONF_HAS_PV: True, "migrated_to_1_1": True}
    assert called_update == [(entry, expected_opts, 2, 1)]

    # 12) Έλεγχος ενημέρωσης παλιού entity
    fake_registry.async_get_entity_id.assert_called_once_with(
        domain="sensor",
        platform=DOMAIN,
        unique_id=old_id,
    )
    fake_registry.async_update_entity.assert_called_once_with(
        old_id, new_unique_id=f"consumption_{entry.data['supplyNumber']}"
    )


@pytest.mark.asyncio
async def test_async_setup_entry_migrated_with_pv(monkeypatch, hass):
    """migrated branch should honor the has_pv flag and set all jump flags."""

    # 1. Προετοιμασία ConfigEntry
    hass.data = {}
    entry = MagicMock()
    entry.data = {"supplyNumber": "SUPPV", "taxNumber": "TAXPV"}
    entry.options = {
        "token": "tokpv",
        "initial_time": "01/01/2020",
        "interval_hours": 4,
        "migrated_to_1_1": True,
        "has_pv": True,
    }
    entry.entry_id = "entry_id_migrated"

    # 2. Spy για run_initial_batches
    called = {}

    async def fake_run_initial_batches(
        hass_arg,
        token_arg,
        supply_arg,
        tax_arg,
        initial_time_arg,
        has_pv,
        inc_con,
    ):
        called["run_initial"] = {
            "has_pv": has_pv,
            "inc_con": inc_con,
        }

    monkeypatch.setattr(
        deddie_metering, "run_initial_batches", fake_run_initial_batches
    )
    monkeypatch.setattr(deddie_metering, "save_initial_jump_flag", AsyncMock())

    # 3. Dummy coordinator για να συλλάβουμε το flag
    coord_args = {}

    class DummyCoord:
        def __init__(
            self,
            hass_arg,
            token_arg,
            supply_arg,
            tax_arg,
            interval_arg,
            choose_step_flag,
            has_pv,
            entry,
        ):
            coord_args["choose_step_flag"] = choose_step_flag
            coord_args["has_pv"] = has_pv
            coord_args["entry"] = entry

        async def async_config_entry_first_refresh(self):
            pass

    monkeypatch.setattr(deddie_metering, "DeddieDataUpdateCoordinator", DummyCoord)

    # 4. Mock των methods του hass.config_entries
    hass.config_entries.async_forward_entry_setups = AsyncMock()
    hass.config_entries.async_update_entry = MagicMock()

    # 5. Εκτέλεση
    result = await async_setup_entry(hass, entry)

    # 6. Assertions
    assert result is True

    # 6.1. Το original entry.options ΔΕΝ αλλάζει in-place
    assert "migrated_to_1_1" in entry.options

    # 6.2. Κλήθηκε το async_update_entry με νέο dict χωρίς το migrated_to_1_1
    expected_opts = {
        "token": entry.options["token"],
        "initial_time": entry.options["initial_time"],
        "interval_hours": entry.options["interval_hours"],
        CONF_HAS_PV: entry.options[CONF_HAS_PV],
    }
    hass.config_entries.async_update_entry.assert_called_once_with(
        entry, options=expected_opts
    )

    # 6.3. run_initial_batches έτρεξε με inc_con=True
    assert "run_initial" in called
    assert called["run_initial"]["inc_con"] is False

    # 6.4. Coordinator init με choose_step_flag="A1" και has_pv=True
    assert coord_args["choose_step_flag"] == "A1"
    assert coord_args["has_pv"] is True


@pytest.mark.asyncio
async def test_async_setup_entry_fresh_setup_with_pv(monkeypatch, hass):
    """Fresh‐setup branch should honor the has_pv flag and set all jump flags."""
    import datetime

    # Prepare entry with has_pv=True
    hass.data = {}
    entry = MagicMock()
    entry.data = {"supplyNumber": "SUPPV", "taxNumber": "TAXPV"}
    entry.options = {
        "token": "tokpv",
        "initial_time": "01/01/2020",
        "interval_hours": 4,
        "has_pv": True,
        "fresh_setup": True,
        "inc_con": True,
    }
    entry.entry_id = "eid_pv"

    # Spy run_initial_batches and save_initial_jump_flag
    rb = AsyncMock(return_value=None)
    sjf = AsyncMock(return_value=None)
    monkeypatch.setattr(deddie_metering, "run_initial_batches", rb)
    monkeypatch.setattr(deddie_metering, "save_initial_jump_flag", sjf)

    # Dummy coordinator to capture skip_initial_refresh and has_pv
    coord_args = {}

    class DummyCoord:
        def __init__(
            self,
            hass_arg,
            token_arg,
            supply_arg,
            tax_arg,
            interval_arg,
            choose_step_flag,
            has_pv,
            entry,
        ):
            coord_args["choose_step_flag"] = choose_step_flag
            coord_args["has_pv"] = has_pv

        async def async_config_entry_first_refresh(self):
            pass

    monkeypatch.setattr(deddie_metering, "DeddieDataUpdateCoordinator", DummyCoord)
    hass.config_entries.async_forward_entry_setups = AsyncMock()

    # Stub platform forwarding & updating
    hass.config_entries.async_forward_entry_setups = AsyncMock()
    hass.config_entries.async_update_entry = MagicMock()

    # Εκτέλεση setup
    result = await async_setup_entry(hass, entry)

    # Assertions
    assert result is True

    # run_initial_batches called exactly once with has_pv=True
    rb.assert_awaited_once_with(
        hass,
        "tokpv",
        "SUPPV",
        "TAXPV",
        datetime.datetime(2020, 1, 1),
        True,
        inc_con=True,
    )

    # All three jump‐flags set to False
    assert sjf.await_count == 3
    keys = {c.kwargs["key"] for c in sjf.await_args_list}
    assert {ATTR_CONSUMPTION, ATTR_PRODUCTION, ATTR_INJECTION} == keys

    # Coordinator init με choose_step_flag="A2" και has_pv=True
    assert coord_args["choose_step_flag"] == "A2"
    assert coord_args["has_pv"] is True


@pytest.mark.asyncio
async def test_async_setup_entry_fresh_not_first_with_pv(monkeypatch, hass):
    """Existing‐data branch should set all jump flags when has_pv=True."""
    from deddie_metering.const import (
        CONF_HAS_PV,
        ATTR_CONSUMPTION,
        ATTR_PRODUCTION,
        ATTR_INJECTION,
    )

    # Prepare entry with has_pv=True
    hass.data = {}
    entry = MagicMock()
    entry.data = {"supplyNumber": "SUP2", "taxNumber": "TAX2"}
    entry.options = {
        "token": "tok2",
        "initial_time": "02/02/2021",
        "interval_hours": 6,
        CONF_HAS_PV: True,
    }
    entry.entry_id = "eid_exist_pv"

    # Spy run_initial_batches (should NOT be called) and save_initial_jump_flag
    ran = {}
    sjf = AsyncMock()
    monkeypatch.setattr(deddie_metering, "run_initial_batches", ran == ["did"])
    monkeypatch.setattr(deddie_metering, "save_initial_jump_flag", sjf)

    # Dummy coordinator to capture skip_initial_refresh and has_pv
    coord_args = {}

    class DummyCoord:
        def __init__(
            self,
            hass_arg,
            token_arg,
            supply_arg,
            tax_arg,
            interval_arg,
            choose_step_flag,
            has_pv,
            entry,
        ):
            coord_args["choose_step_flag"] = "B"
            coord_args["has_pv"] = has_pv

        async def async_config_entry_first_refresh(self):
            pass

    monkeypatch.setattr(deddie_metering, "DeddieDataUpdateCoordinator", DummyCoord)
    hass.config_entries.async_forward_entry_setups = AsyncMock()

    # Execute
    result = await async_setup_entry(hass, entry)
    assert result is True

    # run_initial_batches must NOT have run
    assert "did" not in ran

    # All three jump‐flags set to True
    assert sjf.await_count == 3
    keys = {c.kwargs["key"] for c in sjf.await_args_list}
    assert {ATTR_CONSUMPTION, ATTR_PRODUCTION, ATTR_INJECTION} == keys

    # Coordinator με choose_step_flag="B" και has_pv=True
    assert coord_args["choose_step_flag"] == "B"
    assert coord_args["has_pv"] is True


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
