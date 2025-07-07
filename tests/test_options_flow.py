import pytest
import asyncio
from datetime import datetime
from unittest.mock import AsyncMock, MagicMock, patch
import voluptuous
from deddie_metering import options_flow
import sys

# Stub Boolean for voluptuous schema definitions
voluptuous.Boolean = lambda *args, **kwargs: (lambda v: v)


# Patch dt_util.now to fixed date for consistent date comparisons
@pytest.fixture(autouse=True)
def patch_dt_now(monkeypatch):
    fixed = datetime(2025, 4, 22)
    monkeypatch.setattr(options_flow.dt_util, "now", lambda: fixed)
    monkeypatch.setattr(options_flow.dt_util, "as_local", lambda dt: dt)


# Stub save_last_total to avoid MagicMock await errors
options_flow.save_last_total = AsyncMock(return_value=None)


@pytest.fixture
def dummy_config_entry(hass):
    entry = MagicMock()
    entry.data = {
        "supplyNumber": "123456789",
        "taxNumber": "987654321",
    }
    entry.options = {
        "token": "initial_token",
        "interval_hours": 12,
        "initial_time": "01/01/2024",
        "CONF_HAS_PV": "False",
    }
    entry.hass = hass
    hass.config_entries.async_update_entry = lambda *args, **kwargs: None
    return entry


# Helper to stub show_form and create_entry
def setup_options_flow(handler):
    async def fake_create_entry(title, data):
        return {"type": "create_entry", "title": title, "data": data}

    handler.async_create_entry = fake_create_entry

    async def fake_show_form(
        step_id=None, data_schema=None, errors=None, description_placeholders=None
    ):
        return {"type": "form", "errors": errors or {}}

    handler.async_show_form = fake_show_form


@pytest.mark.asyncio
async def test_token_change_triggers_notify_and_entry(
    hass, dummy_config_entry, monkeypatch
):
    handler = options_flow.DeddieOptionsFlowHandler(dummy_config_entry)
    setup_options_flow(handler)
    user_input = {
        "token": "new_token",
        "interval_hours": 12,
        "initial_time": "01/01/2024",
        "CONF_HAS_PV": False,
    }
    called = {"task_scheduled": False}

    async def fake_pn_create(hass_arg, msg, title, notification_id):
        return None

    def fake_async_create_task(coro):
        called["task_scheduled"] = True
        return asyncio.get_event_loop().create_task(coro)

    dummy_config_entry.hass.async_create_task = fake_async_create_task

    monkeypatch.setattr(
        sys.modules["homeassistant.components.persistent_notification"],
        "async_create",
        fake_pn_create,
    )

    with patch.object(
        options_flow, "validate_credentials", new=AsyncMock(return_value=[{}])
    ), patch.object(options_flow, "translate", return_value="ok"):
        result = await handler.async_step_init(user_input)
        if asyncio.iscoroutine(result):
            result = await result

    assert result["type"] == "create_entry"
    assert result["data"] == user_input
    assert called["task_scheduled"] is True


@pytest.mark.asyncio
async def test_initial_time_validations(hass, dummy_config_entry):
    handler = options_flow.DeddieOptionsFlowHandler(dummy_config_entry)
    setup_options_flow(handler)

    # Invalid format
    result = await handler.async_step_init({"initial_time": "2025-01-01"})
    if asyncio.iscoroutine(result):
        result = await result
    assert result["errors"]["initial_time"] == "invalid_date_format"

    # Future date
    future = (datetime(2025, 4, 23)).strftime("%d/%m/%Y")
    result = await handler.async_step_init({"initial_time": future})
    if asyncio.iscoroutine(result):
        result = await result
    assert result["errors"]["initial_time"] == "date_in_future"

    # Not earlier
    result = await handler.async_step_init({"initial_time": "02/01/2024"})
    if asyncio.iscoroutine(result):
        result = await result
    assert result["errors"]["initial_time"] == "date_not_earlier"


@pytest.mark.asyncio
async def test_token_error_mapping(hass, dummy_config_entry):
    handler = options_flow.DeddieOptionsFlowHandler(dummy_config_entry)
    setup_options_flow(handler)

    # Unauthorized
    with patch.object(
        options_flow,
        "validate_credentials",
        new=AsyncMock(side_effect=Exception("Unauthorized")),
    ):
        result = await handler.async_step_init({"token": "bad"})
        if asyncio.iscoroutine(result):
            result = await result
    assert result["errors"]["base"] == "invalid_token"

    # Other error
    with patch.object(
        options_flow,
        "validate_credentials",
        new=AsyncMock(side_effect=Exception("Foo")),
    ):
        result = await handler.async_step_init({"token": "bad"})
        if asyncio.iscoroutine(result):
            result = await result
    assert result["errors"]["base"] == "unknown_error"


@pytest.mark.asyncio
async def test_show_form_initial(hass, dummy_config_entry):
    handler = options_flow.DeddieOptionsFlowHandler(dummy_config_entry)
    setup_options_flow(handler)
    result = await handler.async_step_init()
    if asyncio.iscoroutine(result):
        result = await result
    assert result["type"] == "form"


@pytest.mark.asyncio
async def test_initial_time_value_error(hass, dummy_config_entry):
    """Date matches regex but is invalid, should error."""
    handler = options_flow.DeddieOptionsFlowHandler(dummy_config_entry)
    setup_options_flow(handler)
    result = await handler.async_step_init(
        {"initial_time": "31/02/2025", "interval_hours": 12}
    )
    if asyncio.iscoroutine(result):
        result = await result
    assert result["type"] == "form"
    assert result["errors"]["initial_time"] == "invalid_date_format"


@pytest.mark.asyncio
async def test_old_initial_parse_exception_triggers_rebatch(hass, dummy_config_entry):
    """Old initial date unparsable should not block rebatch"""
    dummy_config_entry.options["initial_time"] = "invalid_old"
    handler = options_flow.DeddieOptionsFlowHandler(dummy_config_entry)
    setup_options_flow(handler)
    mock_run = AsyncMock()
    mock_save = AsyncMock()
    with patch.object(options_flow, "run_initial_batches", new=mock_run), patch.object(
        options_flow, "save_initial_jump_flag", new=mock_save
    ):
        new_date = "01/01/2023"
        result = await handler.async_step_init(
            {
                "token": dummy_config_entry.options["token"],
                "initial_time": new_date,
                "interval_hours": 12,
            }
        )
        if asyncio.iscoroutine(result):
            result = await result
    assert mock_run.await_count == 1
    assert result["type"] == "create_entry"


def test_options_flow_build_token_link_en():
    from deddie_metering.options_flow import DeddieOptionsFlowHandler

    handler = DeddieOptionsFlowHandler(MagicMock())
    handler.hass = MagicMock()
    handler.hass.config = MagicMock()
    handler.hass.config.language = "en"
    link = handler._build_token_link()
    assert link == '<a href="https://apps.deddie.gr/mdp/intro.html">HEDNO</a>'
