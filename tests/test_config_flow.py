import pytest
import asyncio
from datetime import datetime, timedelta
from unittest.mock import AsyncMock, patch
import sys


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
        return_value={"type": "create_entry", "title": "Supply Test", "data": {}}
    )

    return flow


@pytest.mark.asyncio
async def test_show_form_initial_config_flow(hass):
    """Το async_step_user χωρίς user_input πρέπει να εμφανίζει τη φόρμα."""
    flow = setup_flow(hass)
    # Καλούμε χωρίς user_input
    raw = await flow.async_step_user()
    result = raw
    if asyncio.iscoroutine(raw):
        result = await raw
    # Should return form
    assert result["type"] == "form"


@pytest.mark.asyncio
async def test_valid_input_with_defaults(hass):
    """Valid minimal input (defaults) should create an entry."""
    flow = setup_flow(hass)
    user_input = {
        "token": "valid_token",
        "supplyNumber": "123456789",
        "taxNumber": "987654321",
        "initial_time": PAST_DATE,
        "interval_hours": DEFAULT_INTERVAL,
    }
    with patch(
        "deddie_metering.config_flow.validate_credentials",
        new=AsyncMock(return_value=[{"dummy": "data"}]),
    ):
        with patch("deddie_metering.config_flow.translate", return_value="ok"):
            result = await flow.async_step_user(user_input)
            if asyncio.iscoroutine(result):
                result = await result

    assert isinstance(result, dict)
    assert result["type"] == "create_entry"
    assert result["title"] == "Supply Test"


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
    ):
        with patch("deddie_metering.config_flow.translate", return_value="ok"):
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
    ):
        with patch("deddie_metering.config_flow.translate", return_value="ok"):
            result = await flow.async_step_user(user_input)
            if asyncio.iscoroutine(result):
                result = await result

    assert result["type"] == "form"
    assert result["errors"]["taxNumber"] == "invalid_tax_number"


@pytest.mark.asyncio
async def test_interval_too_small(hass):
    """Interval hours below minimum (1) should error."""
    flow = setup_flow(hass)
    user_input = {
        "token": "t",
        "supplyNumber": "123456789",
        "taxNumber": "987654321",
        "initial_time": PAST_DATE,
        # below absolute minimum of 1
        "interval_hours": 0,
    }
    with patch(
        "deddie_metering.config_flow.validate_credentials",
        new=AsyncMock(return_value=[{}]),
    ):
        with patch("deddie_metering.config_flow.translate", return_value="ok"):
            result = await flow.async_step_user(user_input)
            if asyncio.iscoroutine(result):
                result = await result

    assert result["type"] == "form"
    assert result["errors"]["interval_hours"] == "invalid_interval_hours"


@pytest.mark.asyncio
async def test_interval_too_large(hass):
    """Interval hours above maximum (24) should error."""
    flow = setup_flow(hass)
    user_input = {
        "token": "t",
        "supplyNumber": "123456789",
        "taxNumber": "987654321",
        "initial_time": PAST_DATE,
        # above absolute maximum of 24
        "interval_hours": 25,
    }
    with patch(
        "deddie_metering.config_flow.validate_credentials",
        new=AsyncMock(return_value=[{}]),
    ):
        with patch("deddie_metering.config_flow.translate", return_value="ok"):
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
        # bad format
        "initial_time": "2025-01-01",
        "interval_hours": DEFAULT_INTERVAL,
    }
    with patch(
        "deddie_metering.config_flow.validate_credentials",
        new=AsyncMock(return_value=[{}]),
    ):
        with patch("deddie_metering.config_flow.translate", return_value="ok"):
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
    ):
        with patch("deddie_metering.config_flow.translate", return_value="ok"):
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
    ):
        with patch("deddie_metering.config_flow.translate", return_value="ok"):
            result = await flow.async_step_user(user_input)
            if asyncio.iscoroutine(result):
                result = await result

    assert result["type"] == "form"
    assert result["errors"]["base"] == "invalid_token_or_tax"


# Additional edge-case tests
@pytest.mark.asyncio
async def test_minimal_input_uses_defaults(hass):
    """Only required fields should use defaults and create entry."""
    flow = setup_flow(hass)
    user_input = {
        "token": "valid_token",
        "supplyNumber": "123456789",
        "taxNumber": "987654321",
    }
    with patch(
        "deddie_metering.config_flow.validate_credentials",
        new=AsyncMock(return_value=[{"dummy": "data"}]),
    ):
        with patch("deddie_metering.config_flow.translate", return_value="ok"):
            result = await flow.async_step_user(user_input)
            if asyncio.iscoroutine(result):
                result = await result
    assert result["type"] == "create_entry"


@pytest.mark.asyncio
async def test_supplynumber_with_non_digits(hass):
    """SupplyNumber containing letters should error."""
    flow = setup_flow(hass)
    user_input = {
        "token": "t",
        "supplyNumber": "12A345678",
        "taxNumber": "987654321",
        "initial_time": PAST_DATE,
        "interval_hours": DEFAULT_INTERVAL,
    }
    with patch(
        "deddie_metering.config_flow.validate_credentials",
        new=AsyncMock(return_value=[{}]),
    ):
        with patch("deddie_metering.config_flow.translate", return_value="ok"):
            result = await flow.async_step_user(user_input)
            if asyncio.iscoroutine(result):
                result = await result
    assert result["type"] == "form"
    assert result["errors"]["supplyNumber"] == "invalid_supply_number"


@pytest.mark.asyncio
async def test_taxnumber_with_non_digits(hass):
    """TaxNumber containing letters should error."""
    flow = setup_flow(hass)
    user_input = {
        "token": "t",
        "supplyNumber": "123456789",
        "taxNumber": "987A54321",
        "initial_time": PAST_DATE,
        "interval_hours": DEFAULT_INTERVAL,
    }
    with patch(
        "deddie_metering.config_flow.validate_credentials",
        new=AsyncMock(return_value=[{}]),
    ):
        with patch("deddie_metering.config_flow.translate", return_value="ok"):
            result = await flow.async_step_user(user_input)
            if asyncio.iscoroutine(result):
                result = await result
    assert result["type"] == "form"
    assert result["errors"]["taxNumber"] == "invalid_tax_number"


@pytest.mark.asyncio
async def test_initial_time_strictly_future(hass):
    """Initial_time in the future (tomorrow) should error."""
    flow = setup_flow(hass)
    tomorrow = (datetime.now() + timedelta(days=1)).strftime("%d/%m/%Y")
    user_input = {
        "token": "t",
        "supplyNumber": "123456789",
        "taxNumber": "987654321",
        "initial_time": tomorrow,
        "interval_hours": DEFAULT_INTERVAL,
    }
    with patch(
        "deddie_metering.config_flow.validate_credentials",
        new=AsyncMock(return_value=[{}]),
    ):
        with patch("deddie_metering.config_flow.translate", return_value="ok"):
            result = await flow.async_step_user(user_input)
            if asyncio.iscoroutine(result):
                result = await result
    assert result["type"] == "form"
    assert result["errors"]["initial_time"] == "invalid_date_not_past"


@pytest.mark.asyncio
async def test_invalid_supply_number_from_api(hass):
    """Empty curves list should yield invalid_supply."""
    flow = setup_flow(hass)
    user_input = {
        "token": "ok",
        "supplyNumber": "123456789",
        "taxNumber": "987654321",
        "initial_time": PAST_DATE,
        "interval_hours": DEFAULT_INTERVAL,
    }
    # dry-run επιστρέφει [], άρα invalid_supply
    with patch(
        "deddie_metering.config_flow.validate_credentials",
        new=AsyncMock(return_value=[]),
    ):
        with patch("deddie_metering.config_flow.translate", return_value="ok"):
            result = await flow.async_step_user(user_input)
            if asyncio.iscoroutine(result):
                result = await result
    assert result["type"] == "form"
    assert result["errors"]["base"] == "invalid_supply"


@pytest.mark.asyncio
async def test_validate_credentials_unknown_error(hass):
    """Non-Unauthorized exception should yield unknown_error."""
    flow = setup_flow(hass)
    user_input = {
        "token": "bad_token",
        "supplyNumber": "123456789",
        "taxNumber": "987654321",
        "initial_time": PAST_DATE,
        "interval_hours": DEFAULT_INTERVAL,
    }
    # dry-run πετάει γενική εξαίρεση
    with patch(
        "deddie_metering.config_flow.validate_credentials",
        new=AsyncMock(side_effect=Exception("server error")),
    ):
        with patch("deddie_metering.config_flow.translate", return_value="ok"):
            result = await flow.async_step_user(user_input)
            if asyncio.iscoroutine(result):
                result = await result
    assert result["type"] == "form"
    assert result["errors"]["base"] == "unknown_error"
