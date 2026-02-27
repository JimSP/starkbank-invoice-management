import logging
from unittest.mock import MagicMock, patch

from app.reconciliation import reconcile_paid_invoices


def _make_paid_invoice(inv_id="inv_001", amount=10_000, fee=200):
    inv = MagicMock()
    inv.id = inv_id
    inv.amount = amount
    inv.fee = fee
    return inv


def _make_session_mock(record=None):
    session = MagicMock()
    session.get.return_value = record
    cm = MagicMock()
    cm.__enter__ = MagicMock(return_value=session)
    cm.__exit__ = MagicMock(return_value=False)
    return cm


class TestReconcileApiFailure:
    @patch("app.reconciliation.starkbank.invoice.query", side_effect=Exception("timeout"))
    def test_api_error_is_swallowed(self, _):
        reconcile_paid_invoices()


    @patch("app.reconciliation.starkbank.invoice.query", side_effect=Exception("timeout"))
    def test_api_error_is_logged(self, _, caplog):
        with caplog.at_level(logging.ERROR, logger="app.reconciliation"):
            reconcile_paid_invoices()
        assert "falha ao consultar invoices" in caplog.text.lower()



class TestReconcileNoPaidInvoices:
    @patch("app.reconciliation.starkbank.invoice.query", return_value=[])
    @patch("app.reconciliation.forward_payment")
    def test_no_invoices_no_forward(self, mock_fwd, _):
        reconcile_paid_invoices()
        mock_fwd.assert_not_called()


class TestReconcileAlreadyProcessed:
    @patch("app.reconciliation.starkbank.invoice.query")
    @patch("app.reconciliation.forward_payment")
    @patch("app.reconciliation.get_session")
    def test_already_received_is_skipped(self, mock_gs, mock_fwd, mock_query):
        existing = MagicMock()
        existing.status = "recebido"
        mock_gs.return_value = _make_session_mock(record=existing)
        mock_query.return_value = [_make_paid_invoice()]

        reconcile_paid_invoices()

        mock_fwd.assert_not_called()


    @patch("app.reconciliation.starkbank.invoice.query")
    @patch("app.reconciliation.forward_payment")
    @patch("app.reconciliation.get_session")
    def test_already_received_is_logged_as_debug(self, mock_gs, mock_fwd, mock_query, caplog):
        existing = MagicMock()
        existing.status = "recebido"
        mock_gs.return_value = _make_session_mock(record=existing)
        mock_query.return_value = [_make_paid_invoice()]

        with caplog.at_level(logging.DEBUG, logger="app.reconciliation"):
            reconcile_paid_invoices()

        assert "já processada" in caplog.text.lower()


class TestReconcileNotInLocalDb:
    @patch("app.reconciliation.starkbank.invoice.query")
    @patch("app.reconciliation.forward_payment")
    @patch("app.reconciliation.get_session")
    def test_unknown_invoice_is_skipped(self, mock_gs, mock_fwd, mock_query):
        mock_gs.return_value = _make_session_mock(record=None)
        mock_query.return_value = [_make_paid_invoice()]

        reconcile_paid_invoices()

        mock_fwd.assert_not_called()


    @patch("app.reconciliation.starkbank.invoice.query")
    @patch("app.reconciliation.forward_payment")
    @patch("app.reconciliation.get_session")
    def test_unknown_invoice_logs_warning(self, mock_gs, mock_fwd, mock_query, caplog):
        mock_gs.return_value = _make_session_mock(record=None)
        mock_query.return_value = [_make_paid_invoice("inv_unknown")]

        with caplog.at_level(logging.WARNING, logger="app.reconciliation"):
            reconcile_paid_invoices()

        assert "inv_unknown" in caplog.text
        assert "não encontrada no banco local" in caplog.text.lower()


class TestReconcileWebhookMissed:
    def _setup(self, mock_gs, mock_query, inv_id="inv_001", amount=10_000, fee=200):
        record = MagicMock()
        record.status = "enviado"
        mock_gs.return_value = _make_session_mock(record=record)
        mock_query.return_value = [_make_paid_invoice(inv_id, amount, fee)]


    @patch("app.reconciliation.starkbank.invoice.query")
    @patch("app.reconciliation.forward_payment")
    @patch("app.reconciliation.mark_invoice_received")
    @patch("app.reconciliation.get_session")
    def test_missed_invoice_calls_forward_payment(self, mock_gs, mock_mark, mock_fwd, mock_query):
        self._setup(mock_gs, mock_query)
        mock_fwd.return_value = MagicMock(id="transf_xyz")

        reconcile_paid_invoices()

        mock_fwd.assert_called_once_with(
            invoice_id="inv_001",
            credited_amount=10_000,
            fee=200,
        )


    @patch("app.reconciliation.starkbank.invoice.query")
    @patch("app.reconciliation.forward_payment")
    @patch("app.reconciliation.mark_invoice_received")
    @patch("app.reconciliation.get_session")
    def test_missed_invoice_calls_mark_received(self, mock_gs, mock_mark, mock_fwd, mock_query):
        self._setup(mock_gs, mock_query)
        mock_fwd.return_value = MagicMock(id="transf_xyz")

        reconcile_paid_invoices()

        mock_mark.assert_called_once_with(
            invoice_id="inv_001",
            transfer_id="transf_xyz",
        )


    @patch("app.reconciliation.starkbank.invoice.query")
    @patch("app.reconciliation.forward_payment")
    @patch("app.reconciliation.mark_invoice_received")
    @patch("app.reconciliation.get_session")
    def test_missed_invoice_with_none_transfer(self, mock_gs, mock_mark, mock_fwd, mock_query):
        """forward_payment pode retornar None (valor líquido <= 0)."""
        self._setup(mock_gs, mock_query)
        mock_fwd.return_value = None

        reconcile_paid_invoices()

        mock_mark.assert_called_once_with(invoice_id="inv_001", transfer_id=None)


    @patch("app.reconciliation.starkbank.invoice.query")
    @patch("app.reconciliation.forward_payment")
    @patch("app.reconciliation.mark_invoice_received")
    @patch("app.reconciliation.get_session")
    def test_missed_invoice_logs_warning(self, mock_gs, mock_mark, mock_fwd, mock_query, caplog):
        self._setup(mock_gs, mock_query)
        mock_fwd.return_value = MagicMock(id="t1")

        with caplog.at_level(logging.WARNING, logger="app.reconciliation"):
            reconcile_paid_invoices()

        assert "webhook perdido" in caplog.text.lower()


    @patch("app.reconciliation.starkbank.invoice.query")
    @patch("app.reconciliation.forward_payment")
    @patch("app.reconciliation.mark_invoice_received")
    @patch("app.reconciliation.get_session")
    def test_missed_invoice_logs_success(self, mock_gs, mock_mark, mock_fwd, mock_query, caplog):
        self._setup(mock_gs, mock_query)
        mock_fwd.return_value = MagicMock(id="transf_xyz")

        with caplog.at_level(logging.INFO, logger="app.reconciliation"):
            reconcile_paid_invoices()

        assert "processada com sucesso" in caplog.text.lower()


class TestReconcilePerInvoiceError:
    @patch("app.reconciliation.starkbank.invoice.query")
    @patch("app.reconciliation.forward_payment", side_effect=Exception("transfer failed"))
    @patch("app.reconciliation.mark_invoice_received")
    @patch("app.reconciliation.get_session")
    def test_per_invoice_error_is_swallowed(self, mock_gs, mock_mark, mock_fwd, mock_query):
        record = MagicMock()
        record.status = "enviado"
        mock_gs.return_value = _make_session_mock(record=record)
        mock_query.return_value = [_make_paid_invoice()]

        reconcile_paid_invoices()


    @patch("app.reconciliation.starkbank.invoice.query")
    @patch("app.reconciliation.forward_payment", side_effect=Exception("transfer failed"))
    @patch("app.reconciliation.mark_invoice_received")
    @patch("app.reconciliation.get_session")
    def test_per_invoice_error_is_logged(self, mock_gs, mock_mark, mock_fwd, mock_query, caplog):
        record = MagicMock()
        record.status = "enviado"
        mock_gs.return_value = _make_session_mock(record=record)
        mock_query.return_value = [_make_paid_invoice("inv_fail")]

        with caplog.at_level(logging.ERROR, logger="app.reconciliation"):
            reconcile_paid_invoices()

        assert "inv_fail" in caplog.text


    @patch("app.reconciliation.starkbank.invoice.query")
    @patch("app.reconciliation.forward_payment", side_effect=Exception("boom"))
    @patch("app.reconciliation.mark_invoice_received")
    @patch("app.reconciliation.get_session")
    def test_error_on_one_does_not_skip_others(self, mock_gs, mock_mark, mock_fwd, mock_query):
        """Erro em uma invoice não deve impedir o processamento das demais."""
        record = MagicMock()
        record.status = "enviado"
        mock_gs.return_value = _make_session_mock(record=record)
        mock_query.return_value = [
            _make_paid_invoice("inv_a"),
            _make_paid_invoice("inv_b"),
        ]

        reconcile_paid_invoices()


class TestReconcileSummaryLog:
    @patch("app.reconciliation.starkbank.invoice.query", return_value=[])
    def test_completion_log_is_emitted(self, _, caplog):
        with caplog.at_level(logging.INFO, logger="app.reconciliation"):
            reconcile_paid_invoices()
        assert "concluído" in caplog.text.lower()