import json
from unittest.mock import MagicMock, patch

import pytest

from app.webhook import app
from app.state import MockInvoice, MockLog, MockEvent, webhook_history, webhook_stats
from app.database import Base, engine


@pytest.fixture()
def client():
    app.config["TESTING"] = True
    Base.metadata.create_all(engine)
    with app.test_client() as c:
        webhook_history.clear()
        webhook_stats.update(
            total_received=0,
            total_amount_cents=0,
            errors=0,
            last_event_time=None,
        )
        yield c
    Base.metadata.drop_all(engine)


class TestMockDataclasses:
    def test_mock_invoice_parses_fields(self):
        inv = MockInvoice({"id": "inv_x", "amount": 1500, "fee": 30})
        assert inv.id == "inv_x"
        assert inv.amount == 1500
        assert inv.fee == 30


    def test_mock_invoice_defaults_on_empty_dict(self):
        inv = MockInvoice({})
        assert inv.id == ""
        assert inv.amount == 0
        assert inv.fee == 0


    def test_mock_log_parses_fields_and_nests_invoice(self):
        log = MockLog({"type": "credited", "invoice": {"id": "inv_y", "amount": 2000, "fee": 10}})
        assert log.type == "credited"
        assert isinstance(log.invoice, MockInvoice)
        assert log.invoice.id == "inv_y"
        assert log.invoice.amount == 2000


    def test_mock_log_defaults_on_empty_dict(self):
        log = MockLog({})
        assert log.type == ""
        assert log.invoice.id == ""


    def test_mock_event_parses_fields_and_nests_log(self):
        data = {
            "subscription": "invoice",
            "id": "evt_z",
            "log": {
                "type": "credited",
                "invoice": {"id": "inv_z", "amount": 500, "fee": 5},
            },
        }
        event = MockEvent(data)
        assert event.subscription == "invoice"
        assert event.id == "evt_z"
        assert isinstance(event.log, MockLog)
        assert event.log.type == "credited"
        assert event.log.invoice.id == "inv_z"


    def test_mock_event_defaults_on_empty_dict(self):
        event = MockEvent({})
        assert event.subscription == ""
        assert event.id == ""
        assert event.log.type == ""


class TestHealthEndpoint:
    def test_returns_200_with_required_keys(self, client):
        resp = client.get("/health")
        assert resp.status_code == 200
        data = resp.get_json()
        assert data["status"] in ("ok", "warning")
        assert data["timestamp"].endswith("Z")
        telemetry = data["telemetry"]
        assert "uptime_seconds" in telemetry
        assert "cpu" in telemetry
        assert "memory" in telemetry
        assert "disk" in telemetry


    @patch("app.webhook.psutil.virtual_memory")
    def test_high_memory_triggers_warning(self, mock_mem, client):
        mock_mem.return_value = MagicMock(total=8 * 1024**3, available=100, percent=96.0)
        data = client.get("/health").get_json()
        assert data["status"] == "warning"
        assert "message" in data


    @patch("app.webhook.psutil.cpu_percent", return_value=97.0)
    def test_high_cpu_triggers_warning(self, _, client):
        assert client.get("/health").get_json()["status"] == "warning"


    @patch("app.webhook.psutil.cpu_percent", return_value=10.0)
    @patch("app.webhook.psutil.virtual_memory")
    def test_normal_resources_return_ok(self, mock_mem, _, client):
        mock_mem.return_value = MagicMock(total=8 * 1024**3, available=4 * 1024**3, percent=50.0)
        assert client.get("/health").get_json()["status"] == "ok"


class TestWebhookEndpoint:
    _HEADERS = {"Digital-Signature": "any-sig"}
    _BODY = json.dumps({"event": {}})


    def test_valid_payload_returns_200_queued(self, client):
        resp = client.post("/webhook", data=self._BODY, headers=self._HEADERS)
        assert resp.status_code == 200
        assert resp.get_json() == {"status": "queued"}


    def test_valid_payload_increments_total_received(self, client):
        client.post("/webhook", data=self._BODY, headers=self._HEADERS)
        assert webhook_stats["total_received"] == 1


    def test_valid_payload_sets_last_event_time(self, client):
        assert webhook_stats["last_event_time"] is None
        client.post("/webhook", data=self._BODY, headers=self._HEADERS)
        assert webhook_stats["last_event_time"] is not None
    

    def test_empty_body_returns_400(self, client):
        resp = client.post("/webhook", data="", headers=self._HEADERS)
        assert resp.status_code == 400
        assert resp.get_json() == {"error": "empty body"}


    def test_empty_body_increments_errors(self, client):
        client.post("/webhook", data="", headers=self._HEADERS)
        assert webhook_stats["errors"] == 1


class TestQueueWorkerRealMode:
    def _item(self, content=json.dumps({}), signature="sig"):
        return {"content": content, "signature": signature, "is_mock": False}


class TestQueueWorkerMockMode:
    def _item(self, content=json.dumps({}), signature="dummysig"):
        return {"content": content, "signature": signature, "is_mock": True}
    

class TestRecordAndHandle:
    def setup_method(self):
        webhook_history.clear()
        webhook_stats.update(
            total_received=0, total_amount_cents=0, errors=0, last_event_time=None
        )


class TestDispatchInvoice:
    @patch("app.queue_worker.forward_payment")
    def test_non_credited_log_does_not_forward(self, mock_fwd):
        from app.queue_worker import _dispatch_invoice
        invoice = MagicMock(id="inv_x", amount=1000, fee=10)
        log = MagicMock(type="created", invoice=invoice)
        _dispatch_invoice(log)
        mock_fwd.assert_not_called()


    @patch("app.queue_worker.forward_payment")
    def test_credited_log_forwards_payment(self, mock_fwd):
        from app.queue_worker import _dispatch_invoice
        invoice = MagicMock(id="inv_y", amount=3000, fee=30)
        log = MagicMock(type="credited", invoice=invoice)
        _dispatch_invoice(log)
        mock_fwd.assert_called_once_with(
            invoice_id="inv_y", credited_amount=3000, fee=30
        )


class TestProcessExceptionBranch:
    def _item(self, is_mock=False):
        return {"content": json.dumps({}), "signature": "sig", "is_mock": is_mock}


class TestWorkerLoop:
    def _make_get_side_effect(self, *items):
        seq = list(items)

        def fake_get():
            if seq:
                return seq.pop(0)
            raise SystemExit("stop loop")

        return fake_get


    def test_worker_loop_processes_item(self):
        from app.queue_worker import _worker_loop
        item = {"content": "{}", "signature": "", "is_mock": False}

        with patch("app.queue_worker.event_queue.get",
                   side_effect=self._make_get_side_effect(item)):
            with patch("app.queue_worker._process") as mock_proc:
                with patch("app.queue_worker.event_queue.task_done"):
                    with pytest.raises(SystemExit):
                        _worker_loop()

        mock_proc.assert_called_once_with(item)


    def test_worker_loop_calls_task_done_after_process(self):
        from app.queue_worker import _worker_loop
        item = {"content": "{}", "signature": "", "is_mock": False}

        with patch("app.queue_worker.event_queue.get",
                   side_effect=self._make_get_side_effect(item)):
            with patch("app.queue_worker._process"):
                with patch("app.queue_worker.event_queue.task_done") as mock_done:
                    with pytest.raises(SystemExit):
                        _worker_loop()

        mock_done.assert_called_once()


    def test_worker_loop_calls_task_done_even_when_process_raises(self):
        """finally garante task_done mesmo se _process explodir."""
        from app.queue_worker import _worker_loop
        item = {"content": "{}", "signature": "", "is_mock": False}

        with patch("app.queue_worker.event_queue.get",
                   side_effect=self._make_get_side_effect(item)):
            with patch("app.queue_worker._process", side_effect=RuntimeError("boom")):
                with patch("app.queue_worker.event_queue.task_done") as mock_done:
                    with pytest.raises(SystemExit):
                        _worker_loop()

        mock_done.assert_called_once()


    def test_worker_loop_logs_unhandled_exception(self, caplog):
        from app.queue_worker import _worker_loop
        import logging
        item = {"content": "{}", "signature": "", "is_mock": False}

        with patch("app.queue_worker.event_queue.get",
                   side_effect=self._make_get_side_effect(item)):
            with patch("app.queue_worker._process", side_effect=RuntimeError("boom")):
                with patch("app.queue_worker.event_queue.task_done"):
                    with caplog.at_level(logging.ERROR, logger="app.queue_worker"):
                        with pytest.raises(SystemExit):
                            _worker_loop()

        assert "exceção não tratada" in caplog.text.lower()


    def test_worker_loop_processes_multiple_items(self):
        from app.queue_worker import _worker_loop
        items = [
            {"content": "{}", "signature": "", "is_mock": False},
            {"content": "{}", "signature": "", "is_mock": False},
        ]

        with patch("app.queue_worker.event_queue.get",
                   side_effect=self._make_get_side_effect(*items)):
            with patch("app.queue_worker._process") as mock_proc:
                with patch("app.queue_worker.event_queue.task_done"):
                    with pytest.raises(SystemExit):
                        _worker_loop()

        assert mock_proc.call_count == 2


    def test_start_worker_creates_daemon_thread(self):
        from app.queue_worker import start_worker, _worker_loop
        with patch("app.queue_worker.threading.Thread") as mock_thread:
            mock_instance = MagicMock()
            mock_thread.return_value = mock_instance
            start_worker()

        mock_thread.assert_called_once_with(
            target=_worker_loop, daemon=True, name="event-queue-worker"
        )
        mock_instance.start.assert_called_once()


class TestDashboard:
    def test_mock_mode_banner(self, client, monkeypatch):
        monkeypatch.setenv("USE_MOCK_API", "true")
        resp = client.get("/")
        assert resp.status_code == 200
        assert b"MODO MOCK ATIVO" in resp.data


    def test_sandbox_banner(self, client, monkeypatch):
        monkeypatch.setenv("USE_MOCK_API", "false")
        resp = client.get("/")
        assert resp.status_code == 200
        assert b"SANDBOX REAL" in resp.data


    def test_webhook_history_row_rendered(self, client, monkeypatch):
        monkeypatch.setenv("USE_MOCK_API", "false")
        webhook_history.appendleft(
            {"time": "12:00:00", "type": "invoice.credited", "invoice_id": "inv_render", "amount": 9900}
        )
        resp = client.get("/")
        assert b"inv_render" in resp.data


    def test_scheduler_history_row_rendered(self, client, monkeypatch):
        from app.scheduler import job_history
        monkeypatch.setenv("USE_MOCK_API", "false")
        job_history.append(
            {"timestamp": "12:00:00", "status": "success", "invoices_issued": 2, "ids": ["id1", "id2"], "error": None}
        )
        resp = client.get("/")
        assert b"id1" in resp.data
        job_history.clear()


    def test_scheduler_error_row_rendered(self, client, monkeypatch):
        from app.scheduler import job_history
        monkeypatch.setenv("USE_MOCK_API", "false")
        job_history.append(
            {"timestamp": "12:00:00", "status": "error", "invoices_issued": 0, "ids": [], "error": "timeout"}
        )
        resp = client.get("/")
        assert b"timeout" in resp.data
        job_history.clear()


    @patch("app.webhook.get_invoice_stats")
    def test_stats_volume_displayed(self, mock_stats, client, monkeypatch):
        monkeypatch.setenv("USE_MOCK_API", "false")
        
        mock_stats.return_value = {
            "total_enviado": 10,
            "total_recebido": 5,
            "volume_cents": 123456
        }
        
        resp = client.get("/")
        assert b"1234.56" in resp.data