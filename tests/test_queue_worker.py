import json
import logging
from types import SimpleNamespace
from unittest.mock import MagicMock, patch

import pytest
import starkbank.error
from ellipticcurve.ecdsa import Ecdsa as _Ecdsa
from ellipticcurve.privateKey import PrivateKey

import app.queue_worker as worker_module
from app.queue_worker import (
    _dispatch_invoice,
    _process,
    _record_and_handle,
    start_worker,
)


def _make_log(log_type="credited", invoice_id="inv_001", amount=10_000, fee=200):
    invoice = SimpleNamespace(id=invoice_id, amount=amount, fee=fee)
    return SimpleNamespace(type=log_type, invoice=invoice)


def _make_event(subscription="invoice", log=None, event_id="evt_001"):
    event = SimpleNamespace(subscription=subscription, id=event_id)
    if log is not None:
        event.log = log
    return event


VALID_INVOICE_PAYLOAD = {
    "event": {
        "subscription": "invoice",
        "id": "evt_mock_001",
        "log": {
            "type": "credited",
            "invoice": {"id": "inv_mock_001", "amount": 10_000, "fee": 200},
        },
    }
}


@pytest.fixture()
def keypair(tmp_path):
    priv = PrivateKey()
    pub = priv.publicKey()
    pem_file = tmp_path / "public-key.pem"
    pem_file.write_text(pub.toPem())
    return priv, pem_file


class TestDispatchInvoice:
    def test_chama_forward_payment_com_valores_corretos(self):
        log = _make_log()
        mock_transfer = MagicMock(id="transf_abc")

        with patch("app.queue_worker.forward_payment", return_value=mock_transfer) as mock_fp, \
             patch("app.queue_worker.mark_invoice_received") as mock_mark:
            _dispatch_invoice(log)

        mock_fp.assert_called_once_with(
            invoice_id="inv_001",
            credited_amount=10_000,
            fee=200,
        )
        mock_mark.assert_called_once_with(invoice_id="inv_001", transfer_id="transf_abc")


    def test_transfer_id_nulo_quando_forward_retorna_none(self):
        log = _make_log()

        with patch("app.queue_worker.forward_payment", return_value=None), \
             patch("app.queue_worker.mark_invoice_received") as mock_mark:
            _dispatch_invoice(log)

        mock_mark.assert_called_once_with(invoice_id="inv_001", transfer_id=None)


    def test_ignora_log_type_diferente_de_credited(self):
        log = _make_log(log_type="created")

        with patch("app.queue_worker.forward_payment") as mock_fp:
            _dispatch_invoice(log)

        mock_fp.assert_not_called()


    def test_falha_no_banco_nao_propaga_excecao(self):
        log = _make_log()

        with patch("app.queue_worker.forward_payment", return_value=MagicMock(id="t1")), \
             patch("app.queue_worker.mark_invoice_received", side_effect=Exception("db error")):
            _dispatch_invoice(log)


    def test_falha_no_banco_loga_erro(self, caplog):
        log = _make_log()

        with caplog.at_level(logging.ERROR, logger="app.queue_worker"), \
             patch("app.queue_worker.forward_payment", return_value=MagicMock(id="t1")), \
             patch("app.queue_worker.mark_invoice_received", side_effect=Exception("db error")):
            _dispatch_invoice(log)

        assert "Falha ao atualizar status da invoice" in caplog.text
        assert "inv_001" in caplog.text


class TestRecordAndHandle:
    def test_invoice_credited_aciona_dispatch(self):
        log = _make_log(log_type="credited")
        event = _make_event(log=log)

        with patch("app.queue_worker._dispatch_invoice") as mock_dispatch:
            _record_and_handle(event)

        mock_dispatch.assert_called_once_with(log)


    def test_invoice_nao_credited_nao_aciona_dispatch(self):
        log = _make_log(log_type="created")
        event = _make_event(log=log)

        with patch("app.queue_worker._dispatch_invoice") as mock_dispatch:
            _record_and_handle(event)

        mock_dispatch.assert_not_called()


    def test_invoice_credited_incrementa_total_amount(self):
        log = _make_log(log_type="credited", amount=5_000)
        event = _make_event(log=log)

        before = worker_module.webhook_stats["total_amount_cents"]
        with patch("app.queue_worker._dispatch_invoice"):
            _record_and_handle(event)

        assert worker_module.webhook_stats["total_amount_cents"] == before + 5_000


    def test_evento_desconhecido_registrado_no_historico(self):
        event = _make_event(subscription="transfer")
        worker_module.webhook_history.clear()

        _record_and_handle(event)

        assert worker_module.webhook_history[0]["type"] == "transfer"
        assert worker_module.webhook_history[0]["invoice_id"] == "N/A"


    def test_invoice_sem_log_registrado_no_historico(self):
        event = SimpleNamespace(subscription="invoice", id="evt_x")
        worker_module.webhook_history.clear()

        _record_and_handle(event)

        assert worker_module.webhook_history[0]["type"] == "invoice"


class TestProcess:
    @patch("requests.get")
    def test_mock_valido_aciona_record_and_handle(self, mock_get, keypair):
        priv, _ = keypair
        mock_resp = MagicMock()
        mock_resp.json.return_value = {"publicKeys": [{"content": priv.publicKey().toPem()}]}
        mock_get.return_value = mock_resp

        content = json.dumps(VALID_INVOICE_PAYLOAD)
        signature = _Ecdsa.sign(content, priv).toBase64()

        with patch("app.queue_worker._record_and_handle") as mock_rh:
            _process({"content": content, "signature": signature, "is_mock": True})

        mock_rh.assert_called_once()

    @patch("requests.get")
    def test_mock_assinatura_base64_invalida_loga_warning(self, mock_get, caplog, keypair):
        priv, _ = keypair
        mock_resp = MagicMock()
        mock_resp.json.return_value = {"publicKeys": [{"content": priv.publicKey().toPem()}]}
        mock_get.return_value = mock_resp

        with caplog.at_level(logging.WARNING, logger="app.queue_worker"), \
             patch("app.queue_worker._record_and_handle") as mock_rh:
            _process({"content": "{}", "signature": "!!!not_base64!!!", "is_mock": True})

        assert "assinatura inválida" in caplog.text
        mock_rh.assert_not_called()

    @patch("requests.get")
    def test_mock_assinatura_de_outra_chave_loga_warning(self, mock_get, caplog, keypair):
        priv, _ = keypair
        mock_resp = MagicMock()
        mock_resp.json.return_value = {"publicKeys": [{"content": priv.publicKey().toPem()}]}
        mock_get.return_value = mock_resp

        priv_signer = PrivateKey()
        content = json.dumps(VALID_INVOICE_PAYLOAD)
        signature = _Ecdsa.sign(content, priv_signer).toBase64()

        with caplog.at_level(logging.WARNING, logger="app.queue_worker"), \
             patch("app.queue_worker._record_and_handle") as mock_rh:
            _process({"content": content, "signature": signature, "is_mock": True})

        assert "assinatura inválida" in caplog.text
        mock_rh.assert_not_called()


    def test_real_mode_chama_starkbank_event_parse(self):
        mock_event = MagicMock()

        with patch("starkbank.event.parse", return_value=mock_event) as mock_parse, \
             patch("app.queue_worker._record_and_handle") as mock_rh:
            _process({"content": "payload", "signature": "sig", "is_mock": False})

        mock_parse.assert_called_once_with(content="payload", signature="sig")
        mock_rh.assert_called_once_with(mock_event)


    def test_real_mode_assinatura_invalida_loga_warning(self, caplog):
        with caplog.at_level(logging.WARNING, logger="app.queue_worker"), \
             patch("starkbank.event.parse", side_effect=starkbank.error.InvalidSignatureError("bad")), \
             patch("app.queue_worker._record_and_handle") as mock_rh:
            _process({"content": "x", "signature": "y", "is_mock": False})

        assert "assinatura inválida" in caplog.text
        mock_rh.assert_not_called()


    def test_excecao_generica_loga_error(self, caplog):
        with caplog.at_level(logging.ERROR, logger="app.queue_worker"), \
             patch("starkbank.event.parse", side_effect=RuntimeError("boom")), \
             patch("app.queue_worker._record_and_handle") as mock_rh:
            _process({"content": "x", "signature": "y", "is_mock": False})

        assert "erro ao processar evento" in caplog.text
        mock_rh.assert_not_called()


class TestStartWorker:
    def test_inicia_thread_daemon(self):
        with patch("threading.Thread") as mock_thread_cls:
            mock_thread = MagicMock()
            mock_thread_cls.return_value = mock_thread
            start_worker()

        mock_thread_cls.assert_called_once()
        _, kwargs = mock_thread_cls.call_args
        assert kwargs["daemon"] is True
        assert kwargs["name"] == "event-queue-worker"
        mock_thread.start.assert_called_once()