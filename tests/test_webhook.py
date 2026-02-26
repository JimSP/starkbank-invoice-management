"""tests/test_webhook.py — covers app/webhook.py"""

from unittest.mock import MagicMock, patch

import pytest
import starkbank


class TestHealthEndpoint:
    def test_returns_200(self, client):
        resp = client.get("/health")
        assert resp.status_code == 200
        assert resp.json == {"status": "ok"}


class TestWebhookEndpoint:
    _HEADERS = {"Digital-Signature": "valid-sig"}
    _BODY    = b"{}"

    @patch("app.webhook.starkbank.event.parse",
           side_effect=starkbank.error.InvalidSignatureError("bad"))
    def test_invalid_signature_returns_401(self, _, client):
        resp = client.post("/webhook", data=self._BODY, headers=self._HEADERS)
        assert resp.status_code == 401

    @patch("app.webhook.starkbank.event.parse",
           side_effect=RuntimeError("network timeout"))
    def test_generic_parse_error_returns_400(self, _, client):
        resp = client.post("/webhook", data=self._BODY, headers=self._HEADERS)
        assert resp.status_code == 400

    @patch("app.webhook.forward_payment")
    @patch("app.webhook.starkbank.event.parse")
    def test_credited_invoice_triggers_transfer(self, mock_parse, mock_fwd, client):
        invoice = MagicMock(id="inv1", amount=5_000, fee=100)
        log     = MagicMock(type="credited", invoice=invoice)
        mock_parse.return_value = MagicMock(subscription="invoice", id="e1", log=log)
        resp = client.post("/webhook", data=self._BODY, headers=self._HEADERS)
        assert resp.status_code == 200
        mock_fwd.assert_called_once_with(invoice_id="inv1", credited_amount=5_000, fee=100)

    @pytest.mark.parametrize("log_type", ["created", "overdue", "updated", "canceled"])
    @patch("app.webhook.forward_payment")
    @patch("app.webhook.starkbank.event.parse")
    def test_non_credited_log_type_ignored(self, mock_parse, mock_fwd, log_type, client):
        log = MagicMock(type=log_type, invoice=MagicMock(id="inv2"))
        mock_parse.return_value = MagicMock(subscription="invoice", id="e2", log=log)
        resp = client.post("/webhook", data=self._BODY, headers=self._HEADERS)
        assert resp.status_code == 200
        mock_fwd.assert_not_called()

    @patch("app.webhook.forward_payment")
    @patch("app.webhook.starkbank.event.parse")
    def test_unrelated_subscription_returns_200(self, mock_parse, mock_fwd, client):
        mock_parse.return_value = MagicMock(subscription="transfer", id="e3")
        resp = client.post("/webhook", data=self._BODY, headers=self._HEADERS)
        assert resp.status_code == 200
        mock_fwd.assert_not_called()
