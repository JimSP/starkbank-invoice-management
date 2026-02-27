"""tests/test_transfers.py — covers app/transfers.py"""

from unittest.mock import MagicMock, patch

import pytest
from app.transfers import forward_payment


class TestForwardPayment:
    @patch("app.transfers.starkbank.transfer.create")
    def test_net_amount_equals_credited_minus_fee(self, mock_create):
        mock_create.return_value = [MagicMock(id="t1")]
        forward_payment("inv1", credited_amount=10_000, fee=250)
        assert mock_create.call_args[0][0][0].amount == 9_750


    @patch("app.transfers.starkbank.transfer.create")
    def test_returns_first_created_transfer(self, mock_create):
        fake = MagicMock(id="t1")
        mock_create.return_value = [fake]
        assert forward_payment("inv1", credited_amount=5_000, fee=100) is fake


    @patch("app.transfers.starkbank.transfer.create")
    def test_zero_net_skips_api(self, mock_create):
        assert forward_payment("inv2", credited_amount=500, fee=500) is None
        mock_create.assert_not_called()


    @patch("app.transfers.starkbank.transfer.create")
    def test_negative_net_skips_api(self, mock_create):
        assert forward_payment("inv3", credited_amount=100, fee=500) is None
        mock_create.assert_not_called()


    @patch("app.transfers.starkbank.transfer.create", side_effect=Exception("timeout"))
    def test_propagates_api_exception(self, _):
        with pytest.raises(Exception, match="timeout"):
            forward_payment("inv4", credited_amount=5_000, fee=100)


    @patch("app.transfers.starkbank.transfer.create")
    def test_uses_correct_destination(self, mock_create):
        from app.config import config
        mock_create.return_value = [MagicMock(id="t2")]
        forward_payment("inv5", credited_amount=2_000, fee=0)
        t = mock_create.call_args[0][0][0]
        assert t.bank_code      == config.BANK_CODE
        assert t.branch_code    == config.BRANCH_CODE
        assert t.account_number == config.ACCOUNT_NUMBER
        assert t.tax_id         == config.TAX_ID
