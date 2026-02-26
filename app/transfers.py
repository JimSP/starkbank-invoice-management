"""
app/transfers.py
================
Forwards the net amount of a credited Invoice to Stark Bank S.A.
via starkbank.transfer.create().
"""

import logging

import starkbank

from app.config import TRANSFER_DESTINATION

logger = logging.getLogger(__name__)


def forward_payment(
    invoice_id: str,
    credited_amount: int,
    fee: int,
) -> starkbank.Transfer | None:
    """
    Send ``credited_amount - fee`` cents to the configured destination.

    Returns None (and skips the API call) when net amount is <= 0.
    """
    net = credited_amount - fee

    if net <= 0:
        logger.warning(
            "Invoice %s: net %d <= 0 after fee %d — transfer skipped.",
            invoice_id, net, fee,
        )
        return None

    transfer = starkbank.Transfer(
        amount=net,
        bank_code=TRANSFER_DESTINATION["bank_code"],
        branch_code=TRANSFER_DESTINATION["branch_code"],
        account_number=TRANSFER_DESTINATION["account_number"],
        account_type=TRANSFER_DESTINATION["account_type"],
        name=TRANSFER_DESTINATION["name"],
        tax_id=TRANSFER_DESTINATION["tax_id"],
    )

    created = starkbank.transfer.create([transfer])
    logger.info(
        "Invoice %s: transferred %d cents (gross %d − fee %d). Transfer id=%s",
        invoice_id, net, credited_amount, fee, created[0].id,
    )
    return created[0]
