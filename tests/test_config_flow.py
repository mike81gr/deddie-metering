import pytest
import asyncio
from datetime import datetime, timedelta
from unittest.mock import AsyncMock, patch
import sys

import homeassistant.util.dt as dt_util
from deddie_metering.const import CONF_HAS_PV, CONF_FRESH_SETUP

# Override the dummy persistent_notification.async_create to be synchronous
_pn = sys.modules.get("homeassistant.components.persistent_notification")
if _pn:
    _pn.async_create = lambda *args, **kwargs: None  # type: ignore[attr-defined]

# Use a fixed past date for tests
PAST_DATE = (datetime.now() - timedelta(days=30)).strftime("%d/%m/%Y")
DEFAULT_INTERVAL = 8


# Helper to set up the config flow instance with required stubs
def setup_flow(hass):
    from deddie_metering import config_flow

    # Ensure dt_util.now returns a real datetime
    config_flow.dt_util.now = lambda: datetime.now()

    flow = config_flow.DeddieConfigFlow()
    flow.hass = hass
    flow.async_set_unique_id = AsyncMock(return_value=None)
    flow._abort_if_unique_id_configured = lambda: None

    # Stub for showing forms
    async def fake_show_form(*args, **kwargs):
        return {"type": "form", "errors": kwargs.get("errors", {})}

    flow.async_show_form = fake_show_form

    # Default stub for entry creation
    flow.async_create_entry = AsyncMock(
        return_value={
            "type": "create_entry",
            "title": "Supply Test",
            "data": {},
            "options": {},
        }
    )

    return flow


@pytest.mark.asyncio
async def test_show_form_initial_config_flow(hass):
    """Το async_step_user χωρίς user_input πρέπει να εμφανίζει τη φόρμα."""
    flow = setup_flow(hass)
    raw = await flow.async_step_user()
    result = raw
    if asyncio.iscoroutine(raw):
        result = await raw
    assert result["type"] == "form"


@pytest.mark.asyncio
async def test_valid_input_with_defaults(hass, monkeypatch):
    """
    Valid minimal input (defaults) should create an entry
    and include has_pv in options.
    """
    flow = setup_flow(hass)
    user_input = {
        "token": "valid_token",
        "supplyNumber": "123456789",
        "taxNumber": "987654321",
        "initial_time": PAST_DATE,
        "interval_hours": DEFAULT_INTERVAL,
    }

    # 1) Κάνουμε το async_create να επιστρέφει coroutine
    async def fake_pn_create(hass_arg, msg, title, notification_id):
        return None

    monkeypatch.setattr(
        sys.modules["homeassistant.components.persistent_notification"],
        "async_create",
        fake_pn_create,
    )

    # 2) Stub στο hass.async_create_task για να καταγράψουμε το coroutine
    created = []

    def fake_async_create_task(coro):
        created.append(coro)
        # προγραμματίζουμε το coroutine ώστε να μην έχουμε warning
        asyncio.get_event_loop().create_task(coro)

    hass.async_create_task = fake_async_create_task
    with patch(
        "deddie_metering.config_flow.validate_credentials",
        new=AsyncMock(return_value=[{"dummy": "data"}]),
    ), patch("deddie_metering.config_flow.translate", return_value="ok"):
        result = await flow.async_step_user(user_input)
        if asyncio.iscoroutine(result):
            result = await result

    assert result["type"] == "create_entry"
    assert flow.async_create_entry.called
    _, kwargs = flow.async_create_entry.call_args
    opts = kwargs.get("options", {})
    assert CONF_HAS_PV in opts
    assert opts[CONF_HAS_PV] is True

    # 3) Έλεγχος ότι πράγματι προγραμματίστηκε το coroutine
    assert len(created) == 1, "αναμενόταν ένα coroutine να προγραμματιστεί"
    assert asyncio.iscoroutine(created[0]), "αναμενόταν coroutine ως όρισμα"


@pytest.mark.asyncio
async def test_invalid_supply_number(hass):
    """Supply number must be exactly 9 digits."""
    flow = setup_flow(hass)
    user_input = {
        "token": "t",
        "supplyNumber": "123",
        "taxNumber": "987654321",
        "initial_time": PAST_DATE,
        "interval_hours": DEFAULT_INTERVAL,
    }
    with patch(
        "deddie_metering.config_flow.validate_credentials",
        new=AsyncMock(return_value=[{}]),
    ), patch("deddie_metering.config_flow.translate", return_value="ok"):
        result = await flow.async_step_user(user_input)
        if asyncio.iscoroutine(result):
            result = await result

    assert result["type"] == "form"
    assert result["errors"]["supplyNumber"] == "invalid_supply_number"


@pytest.mark.asyncio
async def test_invalid_tax_number(hass):
    """Tax number must be exactly 9 digits."""
    flow = setup_flow(hass)
    user_input = {
        "token": "t",
        "supplyNumber": "123456789",
        "taxNumber": "abc",
        "initial_time": PAST_DATE,
        "interval_hours": DEFAULT_INTERVAL,
    }
    with patch(
        "deddie_metering.config_flow.validate_credentials",
        new=AsyncMock(return_value=[{}]),
    ), patch("deddie_metering.config_flow.translate", return_value="ok"):
        result = await flow.async_step_user(user_input)
        if asyncio.iscoroutine(result):
            result = await result

    assert result["type"] == "form"
    assert result["errors"]["taxNumber"] == "invalid_tax_number"


@pytest.mark.asyncio
async def test_interval_too_large(hass):
    """Interval hours above maximum (24) should error."""
    flow = setup_flow(hass)
    user_input = {
        "token": "t",
        "supplyNumber": "123456789",
        "taxNumber": "987654321",
        "initial_time": PAST_DATE,
        "interval_hours": 25,
    }
    with patch(
        "deddie_metering.config_flow.validate_credentials",
        new=AsyncMock(return_value=[{}]),
    ), patch("deddie_metering.config_flow.translate", return_value="ok"):
        result = await flow.async_step_user(user_input)
        if asyncio.iscoroutine(result):
            result = await result

    assert result["type"] == "form"
    assert result["errors"]["interval_hours"] == "invalid_interval_hours"


@pytest.mark.asyncio
async def test_invalid_date_format(hass):
    """Initial time wrong format should error."""
    flow = setup_flow(hass)
    user_input = {
        "token": "t",
        "supplyNumber": "123456789",
        "taxNumber": "987654321",
        "initial_time": "2025-01-01",
        "interval_hours": DEFAULT_INTERVAL,
    }
    with patch(
        "deddie_metering.config_flow.validate_credentials",
        new=AsyncMock(return_value=[{}]),
    ), patch("deddie_metering.config_flow.translate", return_value="ok"):
        result = await flow.async_step_user(user_input)
        if asyncio.iscoroutine(result):
            result = await result

    assert result["type"] == "form"
    assert result["errors"]["initial_time"] == "invalid_date_format"


@pytest.mark.asyncio
async def test_date_not_past(hass):
    """Initial time equal to today should error."""
    flow = setup_flow(hass)
    today_str = datetime.now().strftime("%d/%m/%Y")
    user_input = {
        "token": "t",
        "supplyNumber": "123456789",
        "taxNumber": "987654321",
        "initial_time": today_str,
        "interval_hours": DEFAULT_INTERVAL,
    }
    with patch(
        "deddie_metering.config_flow.validate_credentials",
        new=AsyncMock(return_value=[{}]),
    ), patch("deddie_metering.config_flow.translate", return_value="ok"):
        result = await flow.async_step_user(user_input)
        if asyncio.iscoroutine(result):
            result = await result

    assert result["type"] == "form"
    assert result["errors"]["initial_time"] == "invalid_date_not_past"


@pytest.mark.asyncio
async def test_validate_credentials_exception(hass):
    """Exception in validate_credentials yields invalid_token_or_tax."""
    flow = setup_flow(hass)
    user_input = {
        "token": "bad",
        "supplyNumber": "123456789",
        "taxNumber": "987654321",
        "initial_time": PAST_DATE,
        "interval_hours": DEFAULT_INTERVAL,
    }
    with patch(
        "deddie_metering.config_flow.validate_credentials",
        new=AsyncMock(side_effect=Exception("Unauthorized")),
    ), patch("deddie_metering.config_flow.translate", return_value="ok"):
        result = await flow.async_step_user(user_input)
        if asyncio.iscoroutine(result):
            result = await result

    assert result["type"] == "form"
    assert result["errors"]["base"] == "invalid_token_or_tax"


@pytest.mark.asyncio
async def test_supply_invalid_returns_invalid_supply(hass):
    """Empty first validate_credentials returns invalid_supply."""
    flow = setup_flow(hass)
    user_input = {
        "token": "tok",
        "supplyNumber": "123456789",
        "taxNumber": "987654321",
        "initial_time": PAST_DATE,
        "interval_hours": DEFAULT_INTERVAL,
    }
    with patch(
        "deddie_metering.config_flow.validate_credentials",
        new=AsyncMock(return_value=[]),
    ), patch("deddie_metering.config_flow.translate", return_value="ok"):
        result = await flow.async_step_user(user_input)
        if asyncio.iscoroutine(result):
            result = await result
    assert result["type"] == "form"
    assert result["errors"]["base"] == "invalid_supply"


@pytest.mark.asyncio
async def test_credentials_unknown_error_non_401(hass):
    """Generic error in validate_credentials yields unknown_error."""
    flow = setup_flow(hass)
    user_input = {
        "token": "tok",
        "supplyNumber": "123456789",
        "taxNumber": "987654321",
        "initial_time": PAST_DATE,
        "interval_hours": DEFAULT_INTERVAL,
    }
    with patch(
        "deddie_metering.config_flow.validate_credentials",
        new=AsyncMock(side_effect=Exception("some error")),
    ), patch("deddie_metering.config_flow.translate", return_value="ok"):
        result = await flow.async_step_user(user_input)
        if asyncio.iscoroutine(result):
            result = await result
    assert result["type"] == "form"
    assert result["errors"]["base"] == "unknown_error"


@pytest.mark.asyncio
async def test_second_validate_credentials_raises_sets_has_pv_false(hass):
    """Exception in second validate_credentials call should set has_pv False."""
    flow = setup_flow(hass)
    user_input = {
        "token": "valid_token",
        "supplyNumber": "123456789",
        "taxNumber": "987654321",
        "initial_time": PAST_DATE,
        "interval_hours": DEFAULT_INTERVAL,
    }
    side_effects = [[{"dummy": 1}], Exception("error on second")]

    async def fake_validate(hass_arg, token, supply, tax, class_type):
        res = side_effects.pop(0)
        if isinstance(res, Exception):
            raise res
        return res

    with patch(
        "deddie_metering.config_flow.validate_credentials",
        new=fake_validate,
    ), patch("deddie_metering.config_flow.translate", return_value="ok"):
        result = await flow.async_step_user(user_input)
        if asyncio.iscoroutine(result):
            result = await result
    assert result["type"] == "create_entry"
    _, kwargs = flow.async_create_entry.call_args
    opts = kwargs.get("options", {})
    assert CONF_HAS_PV in opts and opts[CONF_HAS_PV] is False


def test_build_token_and_help_links(hass):
    """Token and help links build correctly for languages."""
    from deddie_metering.config_flow import DeddieConfigFlow

    flow = DeddieConfigFlow()
    flow.hass = hass
    hass.config.language = "en"
    token_link_en = flow._build_token_link()
    assert "HEDNO" in token_link_en
    help_link = flow._build_help_link()
    assert "insomnia.gr" in help_link
    hass.config.language = "el"
    token_link_el = flow._build_token_link()
    assert "ΔΕΔΔΗΕ" in token_link_el


@pytest.mark.asyncio
async def test_invalid_date_parsing_value_error(hass):
    """Initial time with valid format but invalid date should error."""
    flow = setup_flow(hass)
    user_input = {
        "token": "t",
        "supplyNumber": "123456789",
        "taxNumber": "987654321",
        "initial_time": "32/13/2020",
        "interval_hours": DEFAULT_INTERVAL,
    }
    with patch(
        "deddie_metering.config_flow.validate_credentials",
        new=AsyncMock(return_value=[{"dummy": "data"}]),
    ), patch("deddie_metering.config_flow.translate", return_value="ok"):
        result = await flow.async_step_user(user_input)
        if asyncio.iscoroutine(result):
            result = await result

    assert result["type"] == "form"
    assert result["errors"]["initial_time"] == "invalid_date_format"


@pytest.mark.asyncio
async def test_interval_boundary_values(hass):
    """Interval hours at boundaries 1 and 24 should be accepted."""
    for hours in (1, 24):
        flow = setup_flow(hass)
        user_input = {
            "token": "valid_token",
            "supplyNumber": "123456789",
            "taxNumber": "987654321",
            "initial_time": PAST_DATE,
            "interval_hours": hours,
        }
        with patch(
            "deddie_metering.config_flow.validate_credentials",
            new=AsyncMock(return_value=[{"dummy": "data"}]),
        ), patch("deddie_metering.config_flow.translate", return_value="ok"):
            result = await flow.async_step_user(user_input)
            if asyncio.iscoroutine(result):
                result = await result
        assert result["type"] == "create_entry"


def test_config_flow_class_attributes():
    """Verify ConfigFlow version and connection class attributes."""
    from deddie_metering.config_flow import DeddieConfigFlow
    from homeassistant.config_entries import CONN_CLASS_CLOUD_POLL

    assert DeddieConfigFlow.MINOR_VERSION == 2
    assert DeddieConfigFlow.CONNECTION_CLASS == CONN_CLASS_CLOUD_POLL


def test_async_get_options_flow_returns_handler(hass):
    """Ensure async_get_options_flow returns the correct options flow handler."""
    from deddie_metering.config_flow import DeddieConfigFlow
    from deddie_metering.options_flow import DeddieOptionsFlowHandler

    dummy_entry = type("Entry", (), {"hass": hass})()
    handler = DeddieConfigFlow.async_get_options_flow(dummy_entry)
    assert isinstance(handler, DeddieOptionsFlowHandler)


@pytest.mark.asyncio
async def test_existing_data_sets_fresh_setup_false(hass, monkeypatch):
    """When previous totals exist, fresh_setup flag should be False."""
    flow = setup_flow(hass)
    user_input = {
        "token": "tok",
        "supplyNumber": "123456789",
        "taxNumber": "987654321",
        "initial_time": PAST_DATE,
        "interval_hours": DEFAULT_INTERVAL,
    }
    monkeypatch.setattr(
        "deddie_metering.config_flow.validate_credentials",
        AsyncMock(return_value=[{"dummy": 1}]),
    )
    monkeypatch.setattr("deddie_metering.config_flow.translate", lambda *a, **k: "ok")
    monkeypatch.setattr(
        "deddie_metering.config_flow.load_last_total", AsyncMock(return_value=1.0)
    )
    monkeypatch.setattr(
        "deddie_metering.config_flow.load_last_update",
        AsyncMock(return_value=dt_util.now()),
    )

    result = await flow.async_step_user(user_input)
    if asyncio.iscoroutine(result):
        result = await result
    assert result["type"] == "create_entry"
    _, kwargs = flow.async_create_entry.call_args
    assert kwargs["options"].get(CONF_FRESH_SETUP) is False
