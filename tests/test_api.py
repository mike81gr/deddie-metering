import sys
import types
import pytest
from typing import List
from datetime import datetime, timedelta
from unittest.mock import MagicMock, patch
import homeassistant.util.dt as dt_util
from deddie_metering import api

pn = sys.modules.get("homeassistant.components.persistent_notification")
# Dummy response and session to simulate aiohttp behaviour
tests_data: List[str] = []


class DummyResponse:
    def __init__(self, status, json_data=None, text_data=None):
        self.status = status
        self._json = json_data or {}
        self._text = text_data or ""

    async def text(self):
        return self._text

    async def json(self):
        return self._json

    async def __aenter__(self):
        return self

    async def __aexit__(self, exc_type, exc, tb):
        return False


class DummySession:
    def __init__(self, response):
        self._response = response
        self.last_url = None
        self.last_json = None
        self.last_headers = None

    def post(self, url, json, headers):
        self.last_url = url
        self.last_json = json
        self.last_headers = headers
        return self._response


@pytest.fixture(autouse=True)
def patch_dt_now(monkeypatch):
    # Freeze now to a constant for tests
    fixed = datetime(2025, 4, 22, 12, 0, 0)
    monkeypatch.setattr(dt_util, "now", lambda: fixed)


@pytest.fixture
def hass():
    # Minimal hass fixture
    hass = MagicMock()
    hass.config = MagicMock()
    hass.config.language = "en"
    return hass


@patch.object(api, "async_get_clientsession")
@pytest.mark.asyncio
async def test_validate_credentials_success(mock_get, hass):
    dummy_curves = [{"meterDate": "01/04/2025 00:00", "consumption": 1}]
    response = DummyResponse(200, {"curves": dummy_curves})
    mock_get.return_value = DummySession(response)
    result = await api.validate_credentials(hass, "token", "supply", "tax")
    assert result == dummy_curves
    # Ensure dry-run uses analysisType 3
    sess = mock_get.return_value
    assert sess.last_json["analysisType"] == 3
    assert sess.last_json["supplyNumber"] == "supply"
    assert sess.last_json["taxNumber"] == "tax"


@patch.object(api, "async_get_clientsession")
@pytest.mark.asyncio
async def test_validate_credentials_unauthorized(mock_get, hass):
    response = DummyResponse(401, {}, text_data="Unauthorized")
    mock_get.return_value = DummySession(response)

    with pytest.raises(Exception) as excinfo:
        await api.validate_credentials(hass, "token", "supply", "tax")
    assert "Unauthorized" in str(excinfo.value)


@patch.object(api, "async_get_clientsession")
@pytest.mark.asyncio
async def test_validate_credentials_api_error(mock_get, hass):
    response = DummyResponse(500, {}, text_data="Server error")
    mock_get.return_value = DummySession(response)

    with pytest.raises(Exception) as excinfo:
        await api.validate_credentials(hass, "token", "supply", "tax")
    assert "status 500" in str(excinfo.value)


@patch.object(api, "async_get_clientsession")
@pytest.mark.asyncio
async def test_validate_credentials_error_field(mock_get, hass):
    response = DummyResponse(200, {"error": "Bad Request"})
    mock_get.return_value = DummySession(response)

    with pytest.raises(Exception) as excinfo:
        await api.validate_credentials(hass, "token", "supply", "tax")
    assert "Bad Request" in str(excinfo.value)


# Tests for get_data_from_api
@patch.object(api, "async_get_clientsession")
@pytest.mark.asyncio
async def test_get_data_success(mock_get, hass):
    dummy_curves = [{"meterDate": "01/04/2025 00:00", "consumption": 2}]
    response = DummyResponse(200, {"curves": dummy_curves})
    mock_get.return_value = DummySession(response)

    from_dt = dt_util.now() - timedelta(days=2)
    to_dt = dt_util.now()
    result = await api.get_data_from_api(hass, "token", "supply", "tax", from_dt, to_dt)
    assert result == dummy_curves
    sess = mock_get.return_value
    # analysisType should be 2
    assert sess.last_json["analysisType"] == 2


@patch.object(api, "async_get_clientsession")
@pytest.mark.asyncio
async def test_get_data_api_error(mock_get, hass):
    response = DummyResponse(500, {}, text_data="Error")
    mock_get.return_value = DummySession(response)

    from_dt = dt_util.now() - timedelta(days=2)
    to_dt = dt_util.now()
    with pytest.raises(Exception) as excinfo:
        await api.get_data_from_api(hass, "token", "supply", "tax", from_dt, to_dt)
    assert "status 500" in str(excinfo.value)


@patch.object(api, "async_get_clientsession")
@pytest.mark.asyncio
async def test_get_data_unauthorized(mock_get, hass, monkeypatch):
    response = DummyResponse(401, {}, text_data="Unauthorized")
    mock_get.return_value = DummySession(response)

    # Track notification
    called = {"pn": False}
    import homeassistant.components.persistent_notification as pn

    monkeypatch.setattr(
        pn,
        "async_create",
        lambda hass_arg, msg, title, notification_id: called.update({"pn": True}),
    )

    from_dt = dt_util.now() - timedelta(days=2)
    to_dt = dt_util.now()
    await api.get_data_from_api(hass, "token", "supply", "tax", from_dt, to_dt)
    # Notification check removed: persistent_notification may not be invoked in tests


@patch.object(api, "async_get_clientsession")
@pytest.mark.asyncio
async def test_get_data_error_field(mock_get, hass):
    response = DummyResponse(200, {"error": "Bad Request"})
    mock_get.return_value = DummySession(response)

    from_dt = dt_util.now() - timedelta(days=2)
    to_dt = dt_util.now()
    with pytest.raises(Exception) as excinfo:
        await api.get_data_from_api(hass, "token", "supply", "tax", from_dt, to_dt)
    assert "Bad Request" in str(excinfo.value)


@patch.object(api, "async_get_clientsession")
@pytest.mark.asyncio
async def test_get_data_empty_curves(mock_get, hass):
    response = DummyResponse(200, {"curves": []})
    mock_get.return_value = DummySession(response)

    from_dt = dt_util.now() - timedelta(days=2)
    to_dt = dt_util.now()
    result = await api.get_data_from_api(hass, "token", "supply", "tax", from_dt, to_dt)
    assert result == []


@pytest.mark.asyncio
async def test_get_data_unauthorized_notifies(hass, monkeypatch):
    # 1) Προετοιμασία dummy session που επιστρέφει 401
    response = DummyResponse(401, {}, text_data="Unauthorized")
    session = DummySession(response)
    monkeypatch.setattr(api, "async_get_clientsession", lambda _hass: session)

    # 2) Fake module για το persistent_notification
    notified = {"called": False}
    fake_pn = types.ModuleType("homeassistant.components.persistent_notification")
    fake_pn.async_create = lambda *args, **kwargs: notified.update(called=True)
    monkeypatch.setitem(
        sys.modules, "homeassistant.components.persistent_notification", fake_pn
    )

    # 3) Κλήση της συνάρτησης με το πραγματικό hass
    from_dt = dt_util.now() - timedelta(days=2)
    to_dt = dt_util.now()
    result = await api.get_data_from_api(hass, "token", "supply", "tax", from_dt, to_dt)

    # 4) Assertions
    assert result == []  # πρέπει να επιστρέφει κενό list
    assert notified["called"] is True  # και να έχει κληθεί το fake async_create
