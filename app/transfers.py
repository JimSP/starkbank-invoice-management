import logging

import starkbank

from app.config import config

logger = logging.getLogger(__name__)

PLATFORM_FEE = config.PLATFORM_FEE 
TRANSFER_FEE = config.TRANSFER_FEE


def forward_payment(
    invoice_id: str,
    credited_amount: int,
    fee: int,
) -> starkbank.Transfer | None:
    net = credited_amount - fee - PLATFORM_FEE - TRANSFER_FEE

    if net <= 0:
        logger.warning(
            "Invoice %s: net %d <= 0 after fee %d, platform_fee %d, transfer_fee %d — transfer skipped.",
            invoice_id, net, fee, PLATFORM_FEE, TRANSFER_FEE,
        )
        return None

    transfer = starkbank.Transfer(
        amount=net,
        bank_code=config.BANK_CODE,
        branch_code=config.BRANCH_CODE,
        account_number=config.ACCOUNT_NUMBER,
        account_type=config.ACCOUNT_TYPE,
        name=config.NAME,
        tax_id=config.TAX_ID,
    )

    created = starkbank.transfer.create([transfer])
    logger.info(
        "Invoice %s: transferred %d cents (gross %d − invoice fee %d − platform fee %d). Transfer id=%s",
        invoice_id, net, credited_amount, fee, PLATFORM_FEE, created[0].id,
    )
    return created[0]
