"""tests/test_webhook.py — covers app/webhook.py"""

from unittest.mock import MagicMock, patch

import pytest
import starkbank

from unittest.mock import patch

class TestHealthEndpoint:

    def test_health_high_resource_usage_returns_warning(self, client, mocker):
        mocker.patch("app.webhook.psutil.cpu_percent", return_value=99.0)
        
        mock_memory = mocker.Mock()
        mock_memory.total = 1024 * 1024 * 1024
        mock_memory.available = 1024 * 1024 * 512
        mock_memory.percent = 50.0
        mocker.patch("app.webhook.psutil.virtual_memory", return_value=mock_memory)

        mock_disk = mocker.Mock()
        mock_disk.free = 1024**3
        mock_disk.percent = 50.0
        mocker.patch("app.webhook.psutil.disk_usage", return_value=mock_disk)

        resp = client.get("/health")
        data = resp.json
        
        assert resp.status_code == 200
        assert data["status"] == "warning"
        assert data["message"] == "High resource usage detected"


    def test_health_detailed_telemetry(self, client):
        resp = client.get("/health")
        data = resp.json
        
        assert resp.status_code == 200
        assert "status" in data
        assert "telemetry" in data
        assert "timestamp" in data
        assert data["service"] == "starkbank-webhook-manager"

        telemetry = data["telemetry"]
        
        assert "cpu" in telemetry
        assert isinstance(telemetry["cpu"]["usage_percent"], (int, float))
        
        assert "memory" in telemetry
        assert telemetry["memory"]["total_mb"] > 0
        assert 0 <= telemetry["memory"]["used_percent"] <= 100
        
        assert "uptime_seconds" in telemetry
        assert telemetry["uptime_seconds"] >= 0


    def test_health_timestamp_format(self, client):
        resp = client.get("/health")
        assert resp.json["timestamp"].endswith("Z")


class TestWebhookEndpoint:
    _HEADERS = {"Digital-Signature": "valid-sig"}
    _BODY    = b"{}"

    @patch("app.webhook.starkbank.event.parse",
           side_effect=starkbank.error.InvalidSignatureError("bad"))
    def test_invalid_signature_returns_401(self, _, client):
        resp = client.post("/webhook", data=self._BODY, headers=self._HEADERS)
        assert resp.status_code == 401


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


    @patch("app.webhook.starkbank.event.parse",
        side_effect=ValueError("invalid json payload"))
    def test_generic_parse_error_returns_400(self, _, client):
        resp = client.post("/webhook", data=self._BODY, headers=self._HEADERS)
        assert resp.status_code == 400


    def test_generic_internal_error_returns_500(self, client, mocker):
        mocker.patch(
            "app.webhook.starkbank.event.parse", 
            side_effect=TypeError("Erro interno imprevisto na biblioteca")
        )
        
        resp = client.post("/webhook", data=self._BODY, headers=self._HEADERS)
        
        assert resp.status_code == 500
        assert resp.json["status"] == "internal_error"