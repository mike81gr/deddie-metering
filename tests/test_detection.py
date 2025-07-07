import pytest
from datetime import datetime, timedelta
import deddie_metering.api.detection as detection

from deddie_metering.const import (
    CONF_HAS_PV,
    ATTR_PRODUCTION,
    ATTR_PV_DETECTION,
    DEFAULT_PV_INTERVAL,
)
from deddie_metering.api.detection import (
    load_last_pv_check,
    save_last_pv_check,
    detect_pv,
)


class DummyEntry:
    """
    Minimal stub for a Home Assistant ConfigEntry with
    options and config_entries API.
    """

    def __init__(self, options):
        self.options = options
        # stub config_entries API on hass


@pytest.fixture
def entry():
    return DummyEntry({})


@pytest.fixture
def token():
    return "dummy-token"


@pytest.fixture
def supply():
    return "123456789"


@pytest.fixture
def tax():
    return "987654321"


@pytest.fixture
def fixed_now(monkeypatch):
    """Patch dt_util.utcnow to return a fixed point in time."""
    fixed = datetime(2025, 1, 1, 12, 0, 0)
    monkeypatch.setattr(detection.dt_util, "utcnow", lambda: fixed)
    return fixed


@pytest.mark.asyncio
async def test_load_last_pv_check_calls_storage(monkeypatch, hass, supply):
    called = {}

    async def fake_load(h, s, key):
        called["args"] = (h, s, key)
        return "loaded-value"

    monkeypatch.setattr(detection, "load_last_update", fake_load)
    result = await load_last_pv_check(hass, supply)
    assert result == "loaded-value"
    assert called["args"] == (hass, supply, ATTR_PV_DETECTION)


@pytest.mark.asyncio
async def test_save_last_pv_check_calls_storage(monkeypatch, hass, supply):
    called = {}

    async def fake_save(h, s, ts, key):
        called["args"] = (h, s, ts, key)

    monkeypatch.setattr(detection, "save_last_update", fake_save)
    ts = datetime(2025, 1, 1, 0, 0, 0)
    await save_last_pv_check(hass, supply, ts)
    assert called["args"] == (hass, supply, ts, ATTR_PV_DETECTION)


@pytest.mark.asyncio
async def test_detect_pv_immediate_true_if_option_set(hass, entry, token, supply, tax):
    entry.options = {CONF_HAS_PV: True}
    # Stubs that should NOT be called
    monkeypatch = pytest.MonkeyPatch()
    monkeypatch.setattr(
        detection,
        "load_last_pv_check",
        lambda *args, **kwargs: (_ for _ in ()).throw(
            AssertionError("load_last_pv_check called")
        ),
    )
    monkeypatch.setattr(
        detection,
        "save_last_pv_check",
        lambda *args, **kwargs: (_ for _ in ()).throw(
            AssertionError("save_last_pv_check called")
        ),
    )
    monkeypatch.setattr(
        detection,
        "validate_credentials",
        lambda *args, **kwargs: (_ for _ in ()).throw(
            AssertionError("validate_credentials called")
        ),
    )
    result = await detect_pv(hass, entry, token, supply, tax)
    assert result is True
    monkeypatch.undo()


@pytest.mark.asyncio
async def test_detect_pv_within_interval_returns_false(
    monkeypatch, hass, entry, token, supply, tax, fixed_now
):
    # option not set
    entry.options = {}
    # last check less than interval ago
    last = fixed_now - timedelta(hours=12)

    async def fake_load(h, s):
        assert h is hass and s == supply
        return last

    monkeypatch.setattr(detection, "load_last_pv_check", fake_load)
    # These should not be called
    monkeypatch.setattr(
        detection,
        "save_last_pv_check",
        lambda *args, **kwargs: (_ for _ in ()).throw(
            AssertionError("save_last_pv_check called")
        ),
    )
    monkeypatch.setattr(
        detection,
        "validate_credentials",
        lambda *args, **kwargs: (_ for _ in ()).throw(
            AssertionError("validate_credentials called")
        ),
    )
    result = await detect_pv(hass, entry, token, supply, tax)
    assert result is False


@pytest.mark.asyncio
async def test_detect_pv_exception_in_validate_returns_false(
    monkeypatch, hass, entry, token, supply, tax, fixed_now
):
    entry.options = {}

    # no previous check
    async def fake_load_last_pv_check(h, s):
        return None

    monkeypatch.setattr(detection, "load_last_pv_check", fake_load_last_pv_check)
    # record that we did save
    called_save = {}

    async def fake_save(h, s, ts):
        called_save["args"] = (h, s, ts)

    monkeypatch.setattr(detection, "save_last_pv_check", fake_save)

    # validate raises
    async def fake_validate(*args, **kwargs):
        raise RuntimeError("boom")

    monkeypatch.setattr(detection, "validate_credentials", fake_validate)
    result = await detect_pv(hass, entry, token, supply, tax)
    assert result is False
    assert called_save["args"] == (hass, supply, fixed_now)


@pytest.mark.asyncio
async def test_detect_pv_detects_and_notifies(
    monkeypatch, hass, entry, token, supply, tax, fixed_now
):
    entry.options = {}
    # last check expired
    last = fixed_now - DEFAULT_PV_INTERVAL - timedelta(seconds=1)

    async def fake_load_last_pv_check(h, s):
        return last

    monkeypatch.setattr(detection, "load_last_pv_check", fake_load_last_pv_check)
    # record save
    saved = {}

    async def fake_save(h, s, ts):
        saved["args"] = (h, s, ts)

    monkeypatch.setattr(detection, "save_last_pv_check", fake_save)

    # validate returns non-empty -> has PV
    async def fake_validate(h, t, s, x, cls):
        assert (h, t, s, x, cls) == (hass, token, supply, tax, ATTR_PRODUCTION)
        return [1, 2, 3]

    monkeypatch.setattr(detection, "validate_credentials", fake_validate)

    # stub config_entries.async_update_entry to return a coroutine
    def fake_update(entry_obj, options):
        fake_update.called = (entry_obj, options)

        # a dummy coroutine
        async def corr():
            return None

        return corr()

    hass.config_entries = type("cfg", (), {"async_update_entry": fake_update})

    # stub pn_create to return a coroutine
    async def dummy_notify(*args, **kwargs):
        dummy_notify.called = (args, kwargs)

    monkeypatch.setattr(detection, "pn_create", lambda *a, **k: dummy_notify())
    # track async_create_task calls
    tasks = []
    hass.async_create_task = lambda coro: tasks.append(coro)
    # perform detection
    result = await detect_pv(hass, entry, token, supply, tax)
    assert result is True
    for task in tasks:
        await task
    # ensure we saved a new
    assert saved["args"][0] is hass and saved["args"][1] == supply
    # ensure config entry was updated with CONF_HAS_PV=True
    entry_obj, opts = fake_update.called
    assert entry_obj is entry
    assert opts.get(CONF_HAS_PV) is True
    # ensure we scheduled both update and notification coroutines
    assert len(tasks) == 2
