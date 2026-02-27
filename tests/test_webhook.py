"""
Tests for app/webhook.py (receiver) and app/queue_worker.py (processor).

After the queue refactor responsibilities are split:
  webhook endpoint  → enqueue raw payload, return 200 immediately
  queue worker      → verify signature, parse event, update stats/history, forward
"""

import json
from unittest.mock import MagicMock, patch, mock_open

import pytest
import starkbank

from app.webhook import app, _handle_invoice_event
from app.state import MockInvoice, MockLog, MockEvent, webhook_history, webhook_stats
from app.queue_worker import _process, _record_and_handle, event_queue


# ─────────────────────────────────────────────────────────────────────────────
# Helpers
# ─────────────────────────────────────────────────────────────────────────────

_FAKE_PEM = "-----BEGIN PUBLIC KEY-----\nFAKE\n-----END PUBLIC KEY-----\n"
_MOCK_OPEN = mock_open(read_data=_FAKE_PEM)


def _make_invoice_event(log_type: str, inv=None) -> MagicMock:
    invoice = inv or MagicMock(id="inv_001", amount=2500, fee=50)
    log = MagicMock(type=log_type, invoice=invoice)
    return MagicMock(subscription="invoice", id="evt_001", log=log)


# ─────────────────────────────────────────────────────────────────────────────
# Fixtures
# ─────────────────────────────────────────────────────────────────────────────

@pytest.fixture()
def client():
    app.config["TESTING"] = True
    with app.test_client() as c:
        webhook_history.clear()
        webhook_stats.update(
            total_received=0,
            total_amount_cents=0,
            errors=0,
            last_event_time=None,
        )
        yield c


@pytest.fixture(autouse=True)
def _drain_queue():
    """Garante fila vazia antes e depois de cada teste."""
    while not event_queue.empty():
        event_queue.get_nowait()
    yield
    while not event_queue.empty():
        event_queue.get_nowait()


# ─────────────────────────────────────────────────────────────────────────────
# TestMockDataclasses
# ─────────────────────────────────────────────────────────────────────────────

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


# ─────────────────────────────────────────────────────────────────────────────
# TestHealthEndpoint
# ─────────────────────────────────────────────────────────────────────────────

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


# ─────────────────────────────────────────────────────────────────────────────
# TestWebhookEndpoint — contrato do endpoint após o refactor
# O endpoint apenas enfileira e responde imediatamente.
# Validação de assinatura e processamento são responsabilidade do worker.
# ─────────────────────────────────────────────────────────────────────────────

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

    def test_enqueues_correct_item_mock_mode(self, client, monkeypatch):
        monkeypatch.setenv("USE_MOCK_API", "true")
        client.post("/webhook", data=self._BODY, headers=self._HEADERS)
        assert event_queue.qsize() == 1
        item = event_queue.get_nowait()
        assert item["content"] == self._BODY
        assert item["signature"] == "any-sig"
        assert item["is_mock"] is True

    def test_is_mock_flag_false_when_env_not_set(self, client, monkeypatch):
        monkeypatch.setenv("USE_MOCK_API", "false")
        client.post("/webhook", data=self._BODY, headers=self._HEADERS)
        assert event_queue.get_nowait()["is_mock"] is False

    def test_empty_body_returns_400_and_does_not_enqueue(self, client):
        resp = client.post("/webhook", data="", headers=self._HEADERS)
        assert resp.status_code == 400
        assert resp.get_json() == {"error": "empty body"}
        assert event_queue.empty()
        assert webhook_stats["errors"] == 1

    def test_multiple_posts_enqueue_all(self, client):
        for _ in range(3):
            client.post("/webhook", data=self._BODY, headers=self._HEADERS)
        assert event_queue.qsize() == 3
        assert webhook_stats["total_received"] == 3

    def test_missing_signature_header_still_enqueues(self, client):
        """Endpoint é permissivo — a validação de assinatura fica no worker."""
        resp = client.post("/webhook", data=self._BODY)
        assert resp.status_code == 200
        assert event_queue.get_nowait()["signature"] == ""


# ─────────────────────────────────────────────────────────────────────────────
# TestQueueWorkerRealMode — _process com is_mock=False
# ─────────────────────────────────────────────────────────────────────────────

class TestQueueWorkerRealMode:

    def _item(self, content=json.dumps({}), signature="sig"):
        return {"content": content, "signature": signature, "is_mock": False}

    @patch("app.queue_worker._record_and_handle")
    @patch("app.queue_worker.starkbank.event.parse")
    def test_valid_event_calls_record_and_handle(self, mock_parse, mock_record):
        event = MagicMock()
        mock_parse.return_value = event
        _process(self._item())
        mock_record.assert_called_once_with(event)

    @patch("app.queue_worker.starkbank.event.parse",
           side_effect=starkbank.error.InvalidSignatureError("bad"))
    def test_invalid_signature_logs_warning_and_returns(self, _, caplog):
        import logging
        with caplog.at_level(logging.WARNING, logger="app.queue_worker"):
            _process(self._item())
        assert "assinatura inválida" in caplog.text.lower()

    @patch("app.queue_worker._record_and_handle")
    @patch("app.queue_worker.starkbank.event.parse",
           side_effect=starkbank.error.InvalidSignatureError("bad"))
    def test_invalid_signature_does_not_call_record(self, _, mock_record):
        _process(self._item())
        mock_record.assert_not_called()

    @patch("app.queue_worker._record_and_handle")
    @patch("app.queue_worker.starkbank.event.parse",
           side_effect=RuntimeError("boom"))
    def test_unexpected_exception_does_not_propagate(self, _, mock_record):
        """Worker nunca pode crashar — erros inesperados são capturados e logados."""
        _process(self._item())  # não deve levantar
        mock_record.assert_not_called()


# ─────────────────────────────────────────────────────────────────────────────
# TestQueueWorkerMockMode — _process com is_mock=True
# ─────────────────────────────────────────────────────────────────────────────

class TestQueueWorkerMockMode:

    def _item(self, content=json.dumps({}), signature="dummysig"):
        return {"content": content, "signature": signature, "is_mock": True}

    @patch("builtins.open", _MOCK_OPEN)
    @patch("app.queue_worker.PublicKey.fromPem", return_value=MagicMock())
    @patch("app.queue_worker.Signature.fromBase64", return_value=MagicMock())
    @patch("app.queue_worker.Ecdsa.verify", return_value=True)
    @patch("app.queue_worker._record_and_handle")
    def test_valid_mock_signature_calls_record(self, mock_record, *_):
        _process(self._item())
        mock_record.assert_called_once()

    @patch("builtins.open", _MOCK_OPEN)
    @patch("app.queue_worker.PublicKey.fromPem", return_value=MagicMock())
    @patch("app.queue_worker.Signature.fromBase64", return_value=MagicMock())
    @patch("app.queue_worker.Ecdsa.verify", return_value=False)
    @patch("app.queue_worker._record_and_handle")
    def test_ecdsa_verify_false_does_not_call_record(self, mock_record, *_):
        _process(self._item())
        mock_record.assert_not_called()

    @patch("builtins.open", _MOCK_OPEN)
    @patch("app.queue_worker.PublicKey.fromPem", return_value=MagicMock())
    @patch("app.queue_worker.Signature.fromBase64", side_effect=Exception("bad base64"))
    @patch("app.queue_worker._record_and_handle")
    def test_bad_base64_does_not_call_record(self, mock_record, *_):
        _process(self._item(signature="!!!"))
        mock_record.assert_not_called()

    @patch("builtins.open", _MOCK_OPEN)
    @patch("app.queue_worker.PublicKey.fromPem", return_value=MagicMock())
    @patch("app.queue_worker.Signature.fromBase64", return_value=MagicMock())
    @patch("app.queue_worker.Ecdsa.verify", return_value=True)
    @patch("app.queue_worker._record_and_handle")
    def test_mock_event_built_from_json_content(self, mock_record, *_):
        """Verifica que o MockEvent é construído corretamente a partir do JSON."""
        content = json.dumps({
            "subscription": "invoice",
            "id": "evt_mock_01",
            "log": {
                "type": "credited",
                "invoice": {"id": "inv_m1", "amount": 800, "fee": 8},
            },
        })
        _process(self._item(content=content))
        mock_record.assert_called_once()
        event_arg = mock_record.call_args[0][0]
        assert event_arg.subscription == "invoice"
        assert event_arg.id == "evt_mock_01"
        assert event_arg.log.invoice.amount == 800


# ─────────────────────────────────────────────────────────────────────────────
# TestRecordAndHandle — _record_and_handle (lógica de roteamento de eventos)
# ─────────────────────────────────────────────────────────────────────────────

class TestRecordAndHandle:

    def setup_method(self):
        webhook_history.clear()
        webhook_stats.update(
            total_received=0, total_amount_cents=0, errors=0, last_event_time=None
        )

    @patch("app.queue_worker.forward_payment")
    def test_invoice_credited_updates_stats_and_forwards(self, mock_fwd):
        _record_and_handle(_make_invoice_event("credited"))

        assert webhook_stats["total_amount_cents"] == 2500
        assert len(webhook_history) == 1
        assert webhook_history[0]["type"] == "invoice.credited"
        mock_fwd.assert_called_once_with(
            invoice_id="inv_001", credited_amount=2500, fee=50
        )

    @patch("app.queue_worker.forward_payment")
    def test_invoice_non_credited_appends_history_no_forward(self, mock_fwd):
        _record_and_handle(_make_invoice_event("created"))

        assert webhook_stats["total_amount_cents"] == 0
        assert webhook_history[0]["type"] == "invoice.created"
        mock_fwd.assert_not_called()

    def test_invoice_without_log_attr_goes_to_else(self):
        event = MagicMock(subscription="invoice", id="evt_002", spec=["subscription", "id"])
        _record_and_handle(event)

        assert webhook_history[0]["type"] == "invoice"
        assert webhook_history[0]["invoice_id"] == "N/A"

    def test_non_invoice_subscription_goes_to_else(self):
        event = MagicMock(subscription="transfer", id="evt_003")
        _record_and_handle(event)

        assert webhook_history[0]["type"] == "transfer"
        assert webhook_history[0]["invoice_id"] == "N/A"

    def test_invoice_with_none_inv_records_na(self):
        log = MagicMock(type="created")
        log.configure_mock(**{"invoice": None})
        event = MagicMock(subscription="invoice", id="evt_inv_none", log=log)
        _record_and_handle(event)

        entry = webhook_history[0]
        assert entry["invoice_id"] == "N/A"
        assert entry["amount"] == 0

    @patch("app.queue_worker.forward_payment")
    def test_two_credited_events_accumulate_total(self, mock_fwd):
        _record_and_handle(_make_invoice_event("credited"))
        _record_and_handle(
            _make_invoice_event("credited", inv=MagicMock(id="inv_002", amount=1000, fee=10))
        )
        assert webhook_stats["total_amount_cents"] == 3500
        assert mock_fwd.call_count == 2


# ─────────────────────────────────────────────────────────────────────────────
# TestDispatchInvoice — _dispatch_invoice (chamada direta para cobrir branch defensivo)
# ─────────────────────────────────────────────────────────────────────────────

class TestDispatchInvoice:
    """
    _record_and_handle só chama _dispatch_invoice com log_type='credited',
    então o branch `log.type != 'credited'` só é alcançável chamando
    _dispatch_invoice diretamente.
    """

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


# ─────────────────────────────────────────────────────────────────────────────
# TestProcessExceptionBranch — except Exception genérico em _process
# ─────────────────────────────────────────────────────────────────────────────

class TestProcessExceptionBranch:
    """
    O except genérico (linha 114) só é atingido por exceções que não sejam
    InvalidSignatureError. Em modo real, isso acontece quando starkbank.event.parse
    levanta algo inesperado que não é InvalidSignatureError nem ValueError.
    Em modo mock, pode vir do json.loads ou de outra etapa.
    """

    def _item(self, is_mock=False):
        return {"content": json.dumps({}), "signature": "sig", "is_mock": is_mock}

    @patch("app.queue_worker._record_and_handle")
    @patch("app.queue_worker.starkbank.event.parse", side_effect=ConnectionError("timeout"))
    def test_generic_exception_real_mode_does_not_propagate(self, _, mock_record):
        _process(self._item(is_mock=False))  # não deve levantar
        mock_record.assert_not_called()

    @patch("app.queue_worker._record_and_handle")
    @patch("app.queue_worker.starkbank.event.parse", side_effect=ConnectionError("timeout"))
    def test_generic_exception_real_mode_logs_error(self, _, mock_record, caplog):
        import logging
        with caplog.at_level(logging.ERROR, logger="app.queue_worker"):
            _process(self._item(is_mock=False))
        assert "erro ao processar evento" in caplog.text.lower()

    @patch("app.queue_worker._record_and_handle")
    @patch("builtins.open", _MOCK_OPEN)
    @patch("app.queue_worker.PublicKey.fromPem", return_value=MagicMock())
    @patch("app.queue_worker.Signature.fromBase64", return_value=MagicMock())
    @patch("app.queue_worker.Ecdsa.verify", return_value=True)
    @patch("app.queue_worker.json.loads", side_effect=MemoryError("oom"))
    def test_generic_exception_mock_mode_does_not_propagate(self, *_):
        _process(self._item(is_mock=True))  # não deve levantar


# ─────────────────────────────────────────────────────────────────────────────
# TestWorkerLoop — _worker_loop e start_worker
# ─────────────────────────────────────────────────────────────────────────────

class TestWorkerLoop:

    def _make_get_side_effect(self, *items):
        """Retorna os items em sequência, depois levanta SystemExit para sair do loop."""
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


# ─────────────────────────────────────────────────────────────────────────────
# TestBusinessLogic — _handle_invoice_event (lógica pura no webhook.py)
# ─────────────────────────────────────────────────────────────────────────────

class TestBusinessLogic:

    @patch("app.webhook.forward_payment")
    def test_credited_calls_forward_with_correct_args(self, mock_fwd):
        invoice = MagicMock(id="inv_abc", amount=10000, fee=200)
        log = MagicMock(type="credited", invoice=invoice)
        _handle_invoice_event(log)
        mock_fwd.assert_called_once_with(
            invoice_id="inv_abc", credited_amount=10000, fee=200
        )

    @patch("app.webhook.forward_payment")
    def test_credited_with_missing_fee_attribute_defaults_to_zero(self, mock_fwd):
        invoice = MagicMock(spec=["id", "amount"], id="inv_nofee", amount=5000)
        log = MagicMock(type="credited", invoice=invoice)
        _handle_invoice_event(log)
        mock_fwd.assert_called_once_with(
            invoice_id="inv_nofee", credited_amount=5000, fee=0
        )

    @pytest.mark.parametrize("log_type", ["created", "overdue", "updated", "canceled"])
    @patch("app.webhook.forward_payment")
    def test_non_credited_log_types_are_ignored(self, mock_fwd, log_type):
        invoice = MagicMock(id="inv_x", amount=5000, fee=100)
        log = MagicMock(type=log_type, invoice=invoice)
        _handle_invoice_event(log)
        mock_fwd.assert_not_called()


# ─────────────────────────────────────────────────────────────────────────────
# TestDashboard
# ─────────────────────────────────────────────────────────────────────────────

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

    def test_stats_volume_displayed(self, client, monkeypatch):
        monkeypatch.setenv("USE_MOCK_API", "false")
        webhook_stats["total_amount_cents"] = 123456
        resp = client.get("/")
        assert b"1234.56" in resp.data