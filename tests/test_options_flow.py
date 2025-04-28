import pytest
import asyncio
from datetime import datetime
from unittest.mock import AsyncMock, MagicMock, patch
from deddie_metering import options_flow


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
    }
    entry.hass = hass
    # Stub update_entry to synchronous
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
async def test_token_change_triggers_notify_and_entry(hass, dummy_config_entry):
    handler = options_flow.DeddieOptionsFlowHandler(dummy_config_entry)
    setup_options_flow(handler)
    user_input = {"token": "new_token", "interval_hours": 12}

    # Track notification calls
    called = {"pn": False}

    def dummy_pn(hass_arg, message, title=None, notification_id=None):
        called["pn"] = True

    with patch(
        "homeassistant.components.persistent_notification.async_create", new=dummy_pn
    ), patch.object(
        options_flow, "validate_credentials", new=AsyncMock(return_value=[{}])
    ), patch.object(
        options_flow, "translate", return_value="ok"
    ):
        result = await handler.async_step_init(user_input)
        if asyncio.iscoroutine(result):
            result = await result

    assert result["type"] == "create_entry"
    assert result["data"] == user_input
    assert called["pn"] is True


@pytest.mark.asyncio
async def test_invalid_interval_errors(hass, dummy_config_entry):
    handler = options_flow.DeddieOptionsFlowHandler(dummy_config_entry)
    setup_options_flow(handler)
    for bad in (0, 25):
        result = await handler.async_step_init({"interval_hours": bad})
        if asyncio.iscoroutine(result):
            result = await result
        assert result["type"] == "form"
        assert result["errors"]["interval_hours"] == "invalid_interval_hours"


@pytest.mark.asyncio
async def test_initial_time_validations(hass, dummy_config_entry):
    handler = options_flow.DeddieOptionsFlowHandler(dummy_config_entry)
    setup_options_flow(handler)

    # Invalid format
    result = await handler.async_step_init({"initial_time": "2025-01-01"})
    if asyncio.iscoroutine(result):
        result = await result
    assert result["errors"]["initial_time"] == "invalid_date_format"

    # Future date relative to 2025-04-22
    future = (datetime(2025, 4, 23)).strftime("%d/%m/%Y")
    result = await handler.async_step_init({"initial_time": future})
    if asyncio.iscoroutine(result):
        result = await result
    assert result["errors"]["initial_time"] == "date_in_future"

    # Not earlier than existing 01/01/2024
    result = await handler.async_step_init({"initial_time": "02/01/2024"})
    if asyncio.iscoroutine(result):
        result = await result
    assert result["errors"]["initial_time"] == "date_not_earlier"


@pytest.mark.asyncio
async def test_token_error_mapping(hass, dummy_config_entry):
    handler = options_flow.DeddieOptionsFlowHandler(dummy_config_entry)
    setup_options_flow(handler)

    # Unauthorized -> invalid_token
    with patch.object(
        options_flow,
        "validate_credentials",
        new=AsyncMock(side_effect=Exception("Unauthorized")),
    ):
        result = await handler.async_step_init({"token": "bad"})
        if asyncio.iscoroutine(result):
            result = await result
    assert result["errors"]["base"] == "invalid_token"

    # Other error -> unknown_error
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
async def test_initial_time_change_triggers_rebatch(hass, dummy_config_entry):
    handler = options_flow.DeddieOptionsFlowHandler(dummy_config_entry)
    setup_options_flow(handler)

    mock_run = AsyncMock()
    mock_save = AsyncMock()
    with patch.object(options_flow, "run_initial_batches", new=mock_run), patch.object(
        options_flow, "save_initial_jump_flag", new=mock_save
    ):
        new_date = "01/01/2023"
        result = await handler.async_step_init(
            {"initial_time": new_date, "interval_hours": 12}
        )
        if asyncio.iscoroutine(result):
            result = await result

    assert mock_run.await_count == 1
    assert mock_save.await_count == 1
    assert result["type"] == "create_entry"
    assert result["data"]["initial_time"] == new_date


@pytest.mark.asyncio
async def test_interval_only_change_creates_entry(hass, dummy_config_entry):
    handler = options_flow.DeddieOptionsFlowHandler(dummy_config_entry)
    setup_options_flow(handler)
    new_interval = 20
    # Ensure no credentials check or notification
    bad_validate = AsyncMock(
        side_effect=AssertionError("validate_credentials should NOT be called")
    )

    def bad_pn(*args, **kwargs):
        raise AssertionError("persistent notification should NOT be called")

    with patch.object(options_flow, "validate_credentials", new=bad_validate), patch(
        "homeassistant.components.persistent_notification.async_create", new=bad_pn
    ):
        result = await handler.async_step_init({"interval_hours": new_interval})
        if asyncio.iscoroutine(result):
            result = await result

    assert result["type"] == "create_entry"
    assert result["data"] == {"interval_hours": new_interval}


@pytest.mark.asyncio
async def test_token_and_initial_time_change_together(hass, dummy_config_entry):
    """
    Changing both token and initial_time triggers notify, rebatch, and create_entry.
    """
    handler = options_flow.DeddieOptionsFlowHandler(dummy_config_entry)
    setup_options_flow(handler)
    user_input = {
        "token": "new_token",
        "initial_time": "01/01/2023",
        "interval_hours": 12,
    }

    called = {"pn": False}

    def dummy_pn(hass_arg, message, title=None, notification_id=None):
        called["pn"] = True

    mock_run = AsyncMock()
    mock_save = AsyncMock()
    with patch(
        "homeassistant.components.persistent_notification.async_create", new=dummy_pn
    ), patch.object(
        options_flow, "validate_credentials", new=AsyncMock(return_value=[{}])
    ), patch.object(
        options_flow, "run_initial_batches", new=mock_run
    ), patch.object(
        options_flow, "save_initial_jump_flag", new=mock_save
    ), patch.object(
        options_flow, "translate", return_value="ok"
    ):
        result = await handler.async_step_init(user_input)
        if asyncio.iscoroutine(result):
            result = await result

    assert called["pn"] is True
    assert mock_run.await_count == 1
    assert mock_save.await_count == 1
    assert result["type"] == "create_entry"
    assert result["data"] == user_input


@pytest.mark.asyncio
async def test_token_and_interval_change_together(hass, dummy_config_entry):
    """
    Changing both token and interval_hours triggers notification
    and create_entry without rebatch.
    """
    handler = options_flow.DeddieOptionsFlowHandler(dummy_config_entry)
    setup_options_flow(handler)
    user_input = {"token": "another_token", "interval_hours": 18}

    # Track notification calls
    called = {"pn": False}

    def dummy_pn(hass_arg, message, title=None, notification_id=None):
        called["pn"] = True

    # Ensure rebatch and save are NOT called
    bad_run = AsyncMock(
        side_effect=AssertionError("run_initial_batches should NOT be called")
    )
    bad_save = AsyncMock(
        side_effect=AssertionError("save_initial_jump_flag should NOT be called")
    )

    with patch(
        "homeassistant.components.persistent_notification.async_create", new=dummy_pn
    ), patch.object(
        options_flow, "validate_credentials", new=AsyncMock(return_value=[{}])
    ), patch.object(
        options_flow, "run_initial_batches", new=bad_run
    ), patch.object(
        options_flow, "save_initial_jump_flag", new=bad_save
    ), patch.object(
        options_flow, "translate", return_value="ok"
    ):
        result = await handler.async_step_init(user_input)
        if asyncio.iscoroutine(result):
            result = await result

    assert called["pn"] is True
    assert result["type"] == "create_entry"
    assert result["data"] == user_input


@pytest.mark.asyncio
async def test_show_form_initial(hass, dummy_config_entry):
    """Το async_step_init χωρίς user_input πρέπει να εμφανίζει τη φόρμα."""
    handler = options_flow.DeddieOptionsFlowHandler(dummy_config_entry)
    setup_options_flow(handler)
    result = await handler.async_step_init()
    if asyncio.iscoroutine(result):
        result = await result
    assert result["type"] == "form"


@pytest.mark.asyncio
async def test_no_change_creates_entry_without_side_effects(hass, dummy_config_entry):
    """Αν υποβληθούν οι ίδιες τιμές, να δημιουργείται entry χωρίς side-effects."""
    handler = options_flow.DeddieOptionsFlowHandler(dummy_config_entry)
    setup_options_flow(handler)

    # Spy σε functions που δεν πρέπει να κληθούν
    dummy_config_entry.hass.config_entries.async_update_entry = MagicMock()
    with patch.object(
        options_flow,
        "validate_credentials",
        new=AsyncMock(
            side_effect=AssertionError("validate_credentials should NOT be called")
        ),
    ), patch(
        "homeassistant.components.persistent_notification.async_create",
        new=lambda *args, **kwargs: (_ for _ in ()).throw(
            AssertionError("persistent_notification should NOT be called")
        ),
    ), patch.object(
        options_flow,
        "run_initial_batches",
        new=AsyncMock(
            side_effect=AssertionError("run_initial_batches should NOT be called")
        ),
    ), patch.object(
        options_flow,
        "save_initial_jump_flag",
        new=AsyncMock(
            side_effect=AssertionError("save_initial_jump_flag should NOT be called")
        ),
    ):

        user_input = {
            "token": dummy_config_entry.options["token"],
            "interval_hours": dummy_config_entry.options["interval_hours"],
            "initial_time": dummy_config_entry.options["initial_time"],
        }
        result = await handler.async_step_init(user_input)
        if asyncio.iscoroutine(result):
            result = await result

    assert result["type"] == "create_entry"
    assert result["data"] == user_input


@pytest.mark.asyncio
async def test_impossible_date_format_errors(hass, dummy_config_entry):
    """Μη έγκυρο ημερολόγιο όπως '31/02/2024' πρέπει να δίνει invalid_date_format."""
    handler = options_flow.DeddieOptionsFlowHandler(dummy_config_entry)
    setup_options_flow(handler)

    result = await handler.async_step_init({"initial_time": "31/02/2024"})
    if asyncio.iscoroutine(result):
        result = await result

    assert result["type"] == "form"
    assert result["errors"]["initial_time"] == "invalid_date_format"
