import asyncio
import pytest
from datetime import datetime
import deddie_metering.statistics_helper as statistics_helper


@pytest.mark.asyncio
async def test_update_future_statistics_no_entries(monkeypatch, hass):
    """
    Should return 0 when there are no future records.
    """
    # Patch hass.async_add_executor_job to return an awaitable
    hass.async_add_executor_job = lambda fn, *args: asyncio.sleep(0, fn(*args))

    # Fake instance returns no timestamps
    fake_instance = type("FakeInstance", (), {})()
    fake_engine = type("FakeEngine", (), {})()

    class FakeConnection:
        def __init__(self):
            self.closed = False

        def execute(self, stmt, params):
            class Result:
                def fetchall(self):
                    return []

            return Result()

        def close(self):
            self.closed = True

    fake_engine.connect = lambda: FakeConnection()
    fake_instance.engine = fake_engine
    # Return an awaitable to avoid 'await' errors
    fake_instance.async_add_executor_job = lambda fn, *args: asyncio.sleep(0, fn(*args))
    monkeypatch.setattr(
        statistics_helper, "get_instance", lambda hass_arg: fake_instance
    )

    count = await statistics_helper.update_future_statistics(
        hass, "123", datetime.now(), 10.0
    )
    assert count == 0


@pytest.mark.asyncio
async def test_update_future_statistics_with_entries(monkeypatch, hass):
    """
    Should return correct count and call import_statistics when future records exist.
    """
    import types

    # Patch hass.async_add_executor_job to return an awaitable
    hass.async_add_executor_job = lambda fn, *args: asyncio.sleep(0, fn(*args))

    # Prepare fake timestamps
    base_ts = datetime.now().timestamp()
    rows = [(base_ts + 3600,), (base_ts + 7200,), (base_ts + 10800,)]

    fake_instance = types.SimpleNamespace()
    fake_engine = types.SimpleNamespace()

    class FakeConnection:
        def __init__(self, rows):
            self._rows = rows
            self.closed = False

        def execute(self, stmt, params):
            class Result:
                def __init__(self, rows):
                    self._rows = rows

                def fetchall(self):
                    return self._rows

            return Result(self._rows)

        def close(self):
            self.closed = True

    fake_engine.connect = lambda: FakeConnection(rows)
    fake_instance.engine = fake_engine
    fake_instance.async_add_executor_job = lambda fn, *args: asyncio.sleep(0, fn(*args))
    monkeypatch.setattr(
        statistics_helper, "get_instance", lambda hass_arg: fake_instance
    )

    calls = []

    def fake_import(hass_arg, metadata, data_list):
        calls.append((metadata.statistic_id, len(data_list)))

    monkeypatch.setattr(statistics_helper, "async_import_statistics", fake_import)

    last_dt = datetime.fromtimestamp(base_ts)
    result = await statistics_helper.update_future_statistics(hass, "456", last_dt, 5.0)
    assert result == 3
    # The statistic_id is a MagicMock due to testing environment;
    # ensure the import was called once with correct count
    assert len(calls) == 1
    _, count_val = calls[0]
    assert count_val == 3


@pytest.mark.asyncio
async def test_update_future_statistics_connect_error(monkeypatch, hass):
    """
    Should return 0 on database connection errors.
    """
    import types

    # Patch hass.async_add_executor_job
    hass.async_add_executor_job = lambda fn, *args: asyncio.sleep(0, fn(*args))

    # Create fake instance whose connect raises
    fake_instance = types.SimpleNamespace()
    fake_engine = types.SimpleNamespace()

    def raise_connect():
        raise Exception("connection failed")

    fake_engine.connect = raise_connect
    fake_instance.engine = fake_engine
    fake_instance.async_add_executor_job = lambda fn, *args: asyncio.sleep(0, fn(*args))
    monkeypatch.setattr(
        statistics_helper, "get_instance", lambda hass_arg: fake_instance
    )

    # Call update_future_statistics
    result = await statistics_helper.update_future_statistics(
        hass, "789", datetime.now(), 0.0
    )
    assert result == 0


@pytest.mark.asyncio
async def test_purge_flat_states_with_keep_days(monkeypatch, hass):
    """
    Should call recorder.purge_entities with custom keep_days.
    """
    called = {}

    async def fake_call(domain, service, service_data, blocking):
        called["args"] = (domain, service, service_data, blocking)

    hass.services.async_call = fake_call

    # Call with non-default keep_days
    await statistics_helper.purge_flat_states(hass, "sensor.keep", "123", keep_days=7)
    assert called["args"][2]["entity_id"] == ["sensor.keep"]
    assert called["args"][2]["keep_days"] == 7


@pytest.mark.asyncio
async def test_purge_flat_states_default_keep_days(monkeypatch, hass, caplog):
    """
    Η purge_flat_states καλεί τον recorder.purge_entities με
    keep_days=0 όταν δεν το δίνουμε.
    """
    called = {}

    async def fake_call(domain, service, service_data, blocking):
        called["args"] = (domain, service, service_data, blocking)

    hass.services.async_call = fake_call

    # Καλούμε χωρίς keep_days
    await statistics_helper.purge_flat_states(hass, "sensor.flat", "123")
    domain, service, data, blocking = called["args"]
    assert domain == "recorder"
    assert service == "purge_entities"
    assert data == {"entity_id": ["sensor.flat"], "keep_days": 0}
    assert blocking is True


@pytest.mark.asyncio
async def test_purge_flat_states_service_error(monkeypatch, hass, caplog):
    """
    Αν η services.async_call πετάει, δεν γίνεται crash και γράφεται error log.
    """

    async def fake_call(domain, service, service_data, blocking):
        raise RuntimeError("oops")

    hass.services.async_call = fake_call

    caplog.set_level("ERROR")
    # Δεν πρέπει να κάνουμε raise
    await statistics_helper.purge_flat_states(hass, "sensor.err", "456", keep_days=3)
    # Βεβαιωνόμαστε ότι γράφτηκε το error
    assert "Σφάλμα κατά τη διαγραφή των flat state εγγραφών" in caplog.text


@pytest.mark.asyncio
async def test_run_update_future_statistics_logs(monkeypatch, hass, caplog):
    """
    Η run_update_future_statistics καλεί update_future_statistics
    και, αν επιστρέψει >0, γράφει info στο log.
    """

    # Monkeypatch του update_future_statistics για να επιστρέφει 2
    async def fake_update(h, supply, last_dt, total):
        return 2

    monkeypatch.setattr(statistics_helper, "update_future_statistics", fake_update)

    caplog.set_level("INFO")
    # Καλούμε με τυχαίες παραμέτρους
    await statistics_helper.run_update_future_statistics(
        hass, "789", datetime.now(), 42.0
    )
    # Ελέγχουμε ότι γράφτηκε το μήνυμα που αναφέρει 2 εγγραφές
    assert "Ενημερώθηκαν στη βάση δεδομένων HA 2 ασυνεπείς εγγραφές" in caplog.text


@pytest.mark.asyncio
async def test_run_update_future_statistics_no_logs_when_zero(
    monkeypatch, hass, caplog
):
    """
    Αν η update_future_statistics επιστρέφει 0, η
    run_update_future_statistics ΔΕΝ γράφει τίποτα στο log.
    """

    # Monkeypatch ώστε update_future_statistics να επιστρέφει 0
    async def fake_update(h, supply, last_dt, total):
        return 0

    monkeypatch.setattr(statistics_helper, "update_future_statistics", fake_update)

    caplog.set_level("INFO")
    await statistics_helper.run_update_future_statistics(
        hass, "000", datetime.now(), 0.0
    )
    # Δεν πρέπει να υπάρχει το info μήνυμα για ενημέρωση εγγραφών
    assert "Ενημερώθηκαν στη βάση δεδομένων HA" not in caplog.text
