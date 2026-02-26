import logging
import random
from datetime import datetime, timedelta, timezone

import starkbank

from app.config import config
from app.people import random_payer

logger = logging.getLogger(__name__)

_EXPIRATION_SECONDS = int(timedelta(hours=1).total_seconds())


def _make_invoice() -> starkbank.Invoice:
    """Build one Invoice for a random payer due in one hour."""
    payer = random_payer()
    due   = datetime.now(tz=timezone.utc) + timedelta(hours=1)

    return starkbank.Invoice(
        amount=payer["amount"],
        name=payer["name"],
        tax_id=payer["tax_id"],
        due=due.isoformat(),
        expiration=_EXPIRATION_SECONDS,
        tags=[payer["email"], payer["phone"]],
        descriptions=[{"key": "Service", "value": "Trial payment"}],
    )


def issue_batch() -> list[starkbank.Invoice]:
    count    = random.randint(config.INVOICE_MIN_BATCH, config.INVOICE_MAX_BATCH)
    invoices = [_make_invoice() for _ in range(count)]

    created = starkbank.invoice.create(invoices)
    logger.info("Issued %d invoices (ids: %s)", len(created), [i.id for i in created])
    return created
