import logging
from datetime import datetime, timezone

import starkbank

from app.database import get_session, InvoiceRecord, mark_invoice_received
from app.transfers import forward_payment

logger = logging.getLogger(__name__)


def reconcile_paid_invoices() -> None:
    logger.info("Reconciliation job iniciado.")

    processed = 0
    skipped = 0
    errors = 0

    try:
        paid_invoices = list(starkbank.invoice.query(status="paid", limit=100))
    except Exception as exc:
        logger.error("Reconciliation: falha ao consultar invoices na Stark Bank — %s", exc, exc_info=True)
        return

    logger.info("Reconciliation: %d invoice(s) com status 'paid' encontradas.", len(paid_invoices))

    for invoice in paid_invoices:
        invoice_id = str(invoice.id)

        try:
            with get_session() as session:
                record = session.get(InvoiceRecord, invoice_id)

                if record is None:
                    logger.warning(
                        "Reconciliation: invoice '%s' paga na Stark Bank mas não encontrada no banco local — ignorando.",
                        invoice_id,
                    )
                    skipped += 1
                    continue

                if record.status == "recebido":
                    logger.debug(
                        "Reconciliation: invoice '%s' já processada — pulando.",
                        invoice_id,
                    )
                    skipped += 1
                    continue

            logger.warning(
                "Reconciliation: invoice '%s' paga sem processamento anterior (webhook perdido) — processando agora.",
                invoice_id,
            )

            fee = getattr(invoice, "fee", 0) or 0
            amount = getattr(invoice, "amount", 0) or 0

            transfer = forward_payment(
                invoice_id=invoice_id,
                credited_amount=amount,
                fee=fee,
            )

            transfer_id = transfer.id if transfer else None
            mark_invoice_received(invoice_id=invoice_id, transfer_id=transfer_id)

            logger.info(
                "Reconciliation: invoice '%s' processada com sucesso (transfer_id=%s).",
                invoice_id,
                transfer_id,
            )
            processed += 1

        except Exception as exc:
            logger.error(
                "Reconciliation: erro ao processar invoice '%s' — %s",
                invoice_id, exc, exc_info=True,
            )
            errors += 1

    logger.info(
        "Reconciliation job concluído — processadas=%d, ignoradas=%d, erros=%d, timestamp=%s",
        processed,
        skipped,
        errors,
        datetime.now(timezone.utc).isoformat().replace("+00:00", "Z"),
    )
