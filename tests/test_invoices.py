from unittest.mock import MagicMock, patch

import pytest
import starkbank
from app.invoices import issue_batch


class TestIssueBatch:
    @patch("app.invoices.starkbank.invoice.create")
    def test_count_is_between_8_and_12(self, mock_create):
        mock_create.side_effect = lambda invoices: invoices
        for _ in range(20):
            assert 8 <= len(issue_batch()) <= 12

    @patch("app.invoices.starkbank.invoice.create")
    def test_returns_sdk_response(self, mock_create):
        fake = [MagicMock(id=f"inv_{i}") for i in range(8)]
        mock_create.return_value = fake
        assert issue_batch() == fake

    @patch("app.invoices.starkbank.invoice.create")
    def test_each_element_is_invoice(self, mock_create):
        mock_create.side_effect = lambda invoices: invoices
        for inv in issue_batch():
            assert isinstance(inv, starkbank.Invoice)

    @patch("app.invoices.starkbank.invoice.create", side_effect=Exception("API down"))
    def test_propagates_exception(self, _):
        with pytest.raises(Exception, match="API down"):
            issue_batch()
