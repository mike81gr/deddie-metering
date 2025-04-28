import pytest
import datetime
import deddie_metering.storage as storage_mod


@pytest.fixture
def dummy_storage(monkeypatch):
    """
    Monkeypatch the Store class and dt_util.parse_datetime for in-memory testing.
    """
    storage = {}

    class DummyStore:
        def __init__(self, hass, version, key):
            self.key = key

        async def async_load(self):
            return storage.get(self.key)

        async def async_save(self, data):
            storage[self.key] = data

    # Patch the Store used in storage_mod
    monkeypatch.setattr(storage_mod, "Store", DummyStore)
    # Patch parse_datetime for load_last_update tests
    monkeypatch.setattr(
        storage_mod.dt_util,
        "parse_datetime",
        lambda s: datetime.datetime.fromisoformat(s),
    )
    return storage


@pytest.mark.asyncio
async def test_load_last_total_returns_none_when_no_data(dummy_storage, hass):
    supply = "123456789"
    result = await storage_mod.load_last_total(hass, supply)
    assert result is None


@pytest.mark.asyncio
async def test_save_and_load_last_total(dummy_storage, hass):
    supply = "123456789"
    # Save a total value
    await storage_mod.save_last_total(hass, supply, 100.5)
    key = f"{storage_mod.DOMAIN}_last_total.json"
    # Verify underlying storage
    assert dummy_storage[key] == {f"total_{supply}": 100.5}
    # Load and verify
    result = await storage_mod.load_last_total(hass, supply)
    assert result == 100.5


@pytest.mark.asyncio
async def test_load_last_update_returns_none_when_no_data(dummy_storage, hass):
    supply = "123456789"
    result = await storage_mod.load_last_update(hass, supply)
    assert result is None


@pytest.mark.asyncio
async def test_save_and_load_last_update(dummy_storage, hass):
    supply = "123456789"
    now = datetime.datetime.now()
    # Save the timestamp
    await storage_mod.save_last_update(hass, supply, now)
    key = f"{storage_mod.DOMAIN}_last_update.json"
    # Verify underlying storage
    assert dummy_storage[key] == {f"last_update_{supply}": now.isoformat()}
    # Load and verify
    result = await storage_mod.load_last_update(hass, supply)
    assert result == now


@pytest.mark.asyncio
async def test_load_initial_jump_flag_returns_false_when_no_data(dummy_storage, hass):
    supply = "123456789"
    result = await storage_mod.load_initial_jump_flag(hass, supply)
    assert result is False


@pytest.mark.asyncio
async def test_save_and_load_initial_jump_flag(dummy_storage, hass):
    supply = "123456789"
    # Save the flag
    await storage_mod.save_initial_jump_flag(hass, supply, True)
    key = f"{storage_mod.DOMAIN}_initial_jump.json"
    # Verify underlying storage
    assert dummy_storage[key] == {f"jump_{supply}": True}
    # Load and verify
    result = await storage_mod.load_initial_jump_flag(hass, supply)
    assert result is True


# Additional edge-case tests
@pytest.mark.asyncio
async def test_multiple_supplies(dummy_storage, hass):
    supply1 = "111111111"
    supply2 = "222222222"
    # Save totals for two supplies
    await storage_mod.save_last_total(hass, supply1, 10.0)
    await storage_mod.save_last_total(hass, supply2, 20.0)
    key = f"{storage_mod.DOMAIN}_last_total.json"
    # Both entries should coexist
    assert dummy_storage[key] == {
        f"total_{supply1}": 10.0,
        f"total_{supply2}": 20.0,
    }


@pytest.mark.asyncio
async def test_overwrite_last_total(dummy_storage, hass):
    supply = "123456789"
    # Save initial value
    await storage_mod.save_last_total(hass, supply, 5.0)
    # Overwrite with new value
    await storage_mod.save_last_total(hass, supply, 7.0)
    # Load and verify overwrite
    result = await storage_mod.load_last_total(hass, supply)
    assert result == 7.0


@pytest.mark.asyncio
async def test_load_last_update_with_invalid_parse(monkeypatch, dummy_storage, hass):
    supply = "123456789"
    # Preload storage with an invalid timestamp string
    key = f"{storage_mod.DOMAIN}_last_update.json"
    dummy_storage[key] = {f"last_update_{supply}": "invalid-timestamp"}
    # Monkeypatch parse_datetime to return None on invalid input
    monkeypatch.setattr(storage_mod.dt_util, "parse_datetime", lambda s: None)
    # load_last_update should then return None gracefully
    result = await storage_mod.load_last_update(hass, supply)
    assert result is None
