import sys
import types
import pytest
import asyncio
from typing import List
from datetime import datetime, timedelta
from unittest.mock import MagicMock, patch
import homeassistant.util.dt as dt_util
from deddie_metering.api import client

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


@patch.object(client, "async_get_clientsession")
@pytest.mark.asyncio
async def test_validate_credentials_success(mock_get, hass):
    dummy_curves = [{"meterDate": "01/04/2025 00:00", "consumption": 1}]
    response = DummyResponse(200, {"curves": dummy_curves})
    mock_get.return_value = DummySession(response)
    result = await client.validate_credentials(
        hass, "token", "supply", "tax", client.ATTR_CONSUMPTION
    )
    assert result == dummy_curves
    # Ensure dry-run uses analysisType 4
    sess = mock_get.return_value
    assert sess.last_json["analysisType"] == 4
    assert sess.last_json["supplyNumber"] == "supply"
    assert sess.last_json["taxNumber"] == "tax"


@patch.object(client, "async_get_clientsession")
@pytest.mark.asyncio
async def test_validate_credentials_unauthorized(mock_get, hass):
    response = DummyResponse(401, {}, text_data="Unauthorized")
    mock_get.return_value = DummySession(response)

    with pytest.raises(Exception) as excinfo:
        await client.validate_credentials(
            hass, "token", "supply", "tax", client.ATTR_CONSUMPTION
        )
    assert "Unauthorized" in str(excinfo.value)


@patch.object(client, "async_get_clientsession")
@pytest.mark.asyncio
async def test_validate_credentials_api_error(mock_get, hass):
    response = DummyResponse(500, {}, text_data="Server error")
    mock_get.return_value = DummySession(response)

    with pytest.raises(Exception) as excinfo:
        await client.validate_credentials(
            hass, "token", "supply", "tax", client.ATTR_CONSUMPTION
        )
    assert "status 500" in str(excinfo.value)


@patch.object(client, "async_get_clientsession")
@pytest.mark.asyncio
async def test_validate_credentials_error_field(mock_get, hass):
    response = DummyResponse(200, {"error": "Bad Request"})
    mock_get.return_value = DummySession(response)

    with pytest.raises(Exception) as excinfo:
        await client.validate_credentials(
            hass, "token", "supply", "tax", client.ATTR_CONSUMPTION
        )
    assert "Bad Request" in str(excinfo.value)


# Tests for get_data_from_api
@patch.object(client, "async_get_clientsession")
@pytest.mark.asyncio
async def test_get_data_api_error(mock_get, hass):
    response = DummyResponse(500, {}, text_data="Error")
    mock_get.return_value = DummySession(response)

    from_dt = dt_util.now() - timedelta(days=2)
    to_dt = dt_util.now()
    with pytest.raises(Exception) as excinfo:
        await client.get_data_from_api(
            hass, "token", "supply", "tax", from_dt, to_dt, client.ATTR_CONSUMPTION
        )
    assert "status 500" in str(excinfo.value)


@patch.object(client, "async_get_clientsession")
@pytest.mark.asyncio
async def test_get_data_error_field(mock_get, hass):
    response = DummyResponse(200, {"error": "Bad Request"})
    mock_get.return_value = DummySession(response)

    from_dt = dt_util.now() - timedelta(days=2)
    to_dt = dt_util.now()
    with pytest.raises(Exception) as excinfo:
        await client.get_data_from_api(
            hass, "token", "supply", "tax", from_dt, to_dt, client.ATTR_CONSUMPTION
        )
    assert "Bad Request" in str(excinfo.value)


@patch.object(client, "async_get_clientsession")
@pytest.mark.asyncio
async def test_get_data_empty_curves(mock_get, hass):
    response = DummyResponse(200, {"curves": []})
    mock_get.return_value = DummySession(response)

    from_dt = dt_util.now() - timedelta(days=2)
    to_dt = dt_util.now()
    result = await client.get_data_from_api(
        hass, "token", "supply", "tax", from_dt, to_dt, client.ATTR_CONSUMPTION
    )
    assert result == []


@pytest.mark.asyncio
async def test_get_data_unauthorized_notifies(hass, monkeypatch):
    # 1) Προετοιμασία dummy session που επιστρέφει 401
    response = DummyResponse(401, {}, text_data="Unauthorized")
    session = DummySession(response)
    monkeypatch.setattr(client, "async_get_clientsession", lambda _hass: session)

    # 2) Fake module για το persistent_notification
    notified = {"called": False}
    fake_pn = types.ModuleType("homeassistant.components.persistent_notification")

    def fake_create(hass_arg, msg, title, notification_id):
        # side-effect εκτελείται _αμέσως_
        notified["called"] = True

        # επιστρέφουμε ένα dummy coroutine για να περάσει το asyncio.iscoroutine
        async def _dummy():
            pass

        return _dummy()

    fake_pn.async_create = fake_create
    monkeypatch.setitem(
        sys.modules, "homeassistant.components.persistent_notification", fake_pn
    )
    created = []

    def fake_async_create_task(coro):
        # αποθηκεύουμε για assertion
        created.append(coro)
        # προγραμματίζουμε το coroutine στον loop, ώστε να μην εκπέσει warning
        asyncio.get_event_loop().create_task(coro)

    hass.async_create_task = fake_async_create_task

    # 3) Κλήση της συνάρτησης με το πραγματικό hass
    from_dt = dt_util.now() - timedelta(days=2)
    to_dt = dt_util.now()
    result = await client.get_data_from_api(
        hass, "token", "supply", "tax", from_dt, to_dt, client.ATTR_CONSUMPTION
    )

    # 4) Assertions
    assert result == []  # πρέπει να επιστρέφει κενό list
    assert notified["called"] is True

    # 5) Έλεγχος ότι κλήθηκε το async_create_task με coroutine
    assert len(created) == 1, "αναμενόταν ένα coroutine να προγραμματιστεί"
    assert asyncio.iscoroutine(created[0]), "αναμενόταν coroutine ως όρισμα"


@patch.object(client, "async_get_clientsession")
@pytest.mark.asyncio
async def test_get_data_production_success(mock_get, hass, caplog):
    """Ensure get_data_from_api returns curves and logs the production label."""
    caplog.set_level("DEBUG")
    dummy_curves = [{"meterDate": "02/04/2025 00:00", "consumption": 3}]
    response = DummyResponse(200, {"curves": dummy_curves})
    mock_get.return_value = DummySession(response)

    from_dt = dt_util.now() - timedelta(days=2)
    to_dt = dt_util.now()
    result = await client.get_data_from_api(
        hass, "token", "supply", "tax", from_dt, to_dt, client.ATTR_PRODUCTION
    )
    assert result == dummy_curves
    sess = mock_get.return_value
    assert sess.last_json["classType"] == client.ATTR_PRODUCTION
    # Verify that debug log for listing production appears
    assert "παραγωγής ενέργειας" in caplog.text


@patch.object(client, "async_get_clientsession")
@pytest.mark.asyncio
async def test_get_data_injection_success(mock_get, hass, caplog):
    """Ensure get_data_from_api returns curves and logs the injection label."""
    caplog.set_level("DEBUG")
    dummy_curves = [{"meterDate": "03/04/2025 00:00", "consumption": 4}]
    response = DummyResponse(200, {"curves": dummy_curves})
    mock_get.return_value = DummySession(response)

    from_dt = dt_util.now() - timedelta(days=2)
    to_dt = dt_util.now()
    result = await client.get_data_from_api(
        hass, "token", "supply", "tax", from_dt, to_dt, client.ATTR_INJECTION
    )
    assert result == dummy_curves
    sess = mock_get.return_value
    assert sess.last_json["classType"] == client.ATTR_INJECTION
    assert "έγχυσης ενέργειας" in caplog.text
