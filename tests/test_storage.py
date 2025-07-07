import pytest
import datetime
import deddie_metering.helpers.storage as storage_mod


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
async def test_save_and_load_last_total(dummy_storage, hass):
    supply = "123456789"
    # Save a total value
    await storage_mod.save_last_total(hass, supply, 100.5)
    key = f"{storage_mod.DOMAIN}_last_total.json"
    # Verify underlying storage
    assert dummy_storage[key] == {f"active_total_{supply}": 100.5}
    # Load and verify
    result = await storage_mod.load_last_total(hass, supply)
    assert result == 100.5
    result2 = await storage_mod.load_last_total(hass, supply, key="produced")
    assert result2 is None


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
    assert dummy_storage[key] == {f"last_update_active_{supply}": now.isoformat()}
    # Load and verify
    result = await storage_mod.load_last_update(hass, supply)
    assert result == now
    result2 = await storage_mod.load_last_update(hass, supply, key="injected")
    assert result2 is None


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
    assert dummy_storage[key] == {f"jump_active_{supply}": True}
    # Load and verify
    result = await storage_mod.load_initial_jump_flag(hass, supply)
    assert result is True
    result2 = await storage_mod.load_initial_jump_flag(hass, supply, key="injected")
    assert result2 is False
