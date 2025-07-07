import asyncio
import pytest
import types
from datetime import datetime
import deddie_metering.helpers.statistics as statistics


# Override StatisticMetaData to preserve passed values in tests
class DummyMetaData:
    def __init__(self, **kwargs):
        self.statistic_id = kwargs.get("statistic_id")
        self.name = kwargs.get("name")


# Apply override
statistics.StatisticMetaData = DummyMetaData


@pytest.mark.asyncio
async def test_run_update_future_statistics_logs(monkeypatch, hass, caplog):
    """
    Η run_update_future_statistics καλεί update_future_statistics
    και, αν επιστρέψει >0, γράφει info στο log.
    """

    # Monkeypatch του update_future_statistics για να επιστρέφει 2
    async def fake_update(h, supply, last_dt, total, class_type):
        return 2

    monkeypatch.setattr(statistics, "update_future_statistics", fake_update)

    caplog.set_level("INFO")
    # Καλούμε με τυχαίες παραμέτρους
    await statistics.run_update_future_statistics(
        hass, "789", datetime.now(), 42.0, "consumption"
    )
    # Ελέγχουμε ότι γράφτηκε το μήνυμα που αναφέρει 2 εγγραφές
    assert "Ενημερώθηκαν στη βάση δεδομένων HA 2 ασυνεπείς εγγραφές" in caplog.text


@pytest.mark.asyncio
async def test_update_future_statistics_production_and_injection(monkeypatch, hass):
    """
    Should return correct count and correct metadata for production and injection.
    """
    hass.async_add_executor_job = lambda fn, *args: asyncio.sleep(0, fn(*args))
    # Prepare fake timestamps
    base_ts = datetime.now().timestamp()
    rows = [(base_ts + 3600,), (base_ts + 7200,)]

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
    monkeypatch.setattr(statistics, "get_instance", lambda hass_arg: fake_instance)

    calls = []

    def fake_import(hass_arg, metadata, data_list):
        calls.append((metadata.statistic_id, metadata.name, len(data_list)))

    monkeypatch.setattr(statistics, "async_import_statistics", fake_import)

    last_dt = datetime.fromtimestamp(base_ts)
    # Test production
    type_key = "production"
    result_prod = await statistics.update_future_statistics(
        hass,
        "prod1",
        last_dt,
        1.0,
        type_key,
    )
    assert result_prod == 2
    stat_id, name, count_list = calls[-1]
    assert stat_id == f"sensor.deddie_{type_key}_prod1"
    assert "Παραγωγή ΔΕΔΔΗΕ" in name
    assert count_list == 2
    # Test injection
    type_key = "injection"
    result_inj = await statistics.update_future_statistics(
        hass,
        "inj2",
        last_dt,
        2.0,
        type_key,
    )
    assert result_inj == 2
    stat_id, name, count_list = calls[-1]
    assert stat_id == f"sensor.deddie_{type_key}_inj2"
    assert "Έγχυση ΔΕΔΔΗΕ" in name
    assert count_list == 2


@pytest.mark.asyncio
async def test_run_update_future_statistics_labels(monkeypatch, hass, caplog):
    """
    run_update_future_statistics logs correct labels for production and injection.
    """

    async def fake_update(h, supply, last_dt, total, class_type):
        return 1

    monkeypatch.setattr(statistics, "update_future_statistics", fake_update)
    caplog.set_level("INFO")
    # Production label
    await statistics.run_update_future_statistics(
        hass, "x", datetime.now(), 3.0, "production"
    )
    assert "παραγωγής ενέργειας" in caplog.text
    caplog.clear()
    # Injection label
    await statistics.run_update_future_statistics(
        hass, "y", datetime.now(), 4.0, "injection"
    )
    assert "έγχυσης ενέργειας" in caplog.text


@pytest.mark.asyncio
async def test_purge_flat_states_success(monkeypatch, hass, caplog):
    """
    purge_flat_states should call recorder.purge_entities and log info on success.
    """
    call_args = {}

    async def fake_call(domain, service, service_data, blocking):
        call_args.update(
            {
                "domain": domain,
                "service": service,
                "service_data": service_data,
                "blocking": blocking,
            }
        )

    monkeypatch.setattr(hass.services, "async_call", fake_call)
    caplog.set_level("INFO")
    await statistics.purge_flat_states(hass, "ent.id", "supplyA", keep_days=5)
    assert call_args["domain"] == "recorder"
    assert call_args["service"] == "purge_entities"
    assert call_args["service_data"] == {"entity_id": ["ent.id"], "keep_days": 5}
    assert call_args["blocking"] is True
    assert "Επιτυχής διαγραφή των flat state εγγραφών" in caplog.text


@pytest.mark.asyncio
async def test_purge_flat_states_error(monkeypatch, hass, caplog):
    """
    purge_flat_states should log error when service call fails.
    """

    async def fake_call(domain, service, service_data, blocking):
        raise Exception("fail")

    monkeypatch.setattr(hass.services, "async_call", fake_call)
    caplog.set_level("ERROR")
    await statistics.purge_flat_states(hass, "ent2", "supplyB")
    assert "Σφάλμα κατά τη διαγραφή των flat state εγγραφών" in caplog.text


@pytest.mark.asyncio
async def test_update_future_statistics_conn_close_warning(monkeypatch, hass, caplog):
    """
    update_future_statistics should log a warning when closing the DB connection fails.
    """
    # Patch hass.async_add_executor_job to be awaitable
    hass.async_add_executor_job = lambda fn, *args: asyncio.sleep(0, fn(*args))

    # Setup fake connection with two timestamps and a close method
    class FakeConn:
        def __init__(self):
            self.closed = False

        def execute(self, stmt, params):
            class Result:
                def fetchall(self_inner):
                    return [(10,), (20,)]

            return Result()

        def close(self):
            self.closed = True
            raise Exception("close failed")

    fake_conn = FakeConn()

    # Stub _connect to return fake_conn
    async def fake_connect(instance, engine):
        return fake_conn

    monkeypatch.setattr(statistics, "_connect", fake_connect)

    # Stub get_instance to return fake instance
    fake_instance = type("FakeInstance", (), {})()
    fake_instance.engine = None

    # Flag to confirm close was called
    called_close = {"called": False}

    async def fake_add_executor_job(fn, *args):
        if getattr(fn, "__name__", "") == "close":
            called_close["called"] = True
        return fn(*args)

    fake_instance.async_add_executor_job = fake_add_executor_job
    monkeypatch.setattr(statistics, "get_instance", lambda hass_arg: fake_instance)

    caplog.set_level("WARNING", logger="deddie_metering")
    result = await statistics.update_future_statistics(
        hass, "connfail", datetime.now(), 0.0, "consumption"
    )
    assert result == 2
    assert called_close["called"] is True
    # Verify warning logged for failed close
    assert any(
        record.levelname == "WARNING"
        and "Σφάλμα στο κλείσιμο της σύνδεσης" in record.message
        for record in caplog.records
    )
