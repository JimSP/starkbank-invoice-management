import json
import logging
import queue
import threading
from datetime import datetime, timezone
from typing import Any

import starkbank
from ellipticcurve.ecdsa import Ecdsa
from ellipticcurve.publicKey import PublicKey
from ellipticcurve.signature import Signature

from app.transfers import forward_payment
from app.state import MockEvent, webhook_history, webhook_stats
from app.database import mark_invoice_received

import requests

logger = logging.getLogger(__name__)

event_queue: queue.Queue = queue.Queue()


def _record_and_handle(event: Any) -> None:
    sub = getattr(event, "subscription", "unknown")
    ev_id = getattr(event, "id", "unknown")
    logger.info("Processando evento — subscription=%s id=%s", sub, ev_id)

    if sub == "invoice" and hasattr(event, "log"):
        log = event.log
        inv = getattr(log, "invoice", None)

        inv_id   = getattr(inv, "id", "N/A") if inv else "N/A"
        amt      = getattr(inv, "amount", 0) if inv else 0
        log_type = getattr(log, "type", "unknown")

        webhook_history.appendleft({
            "time": datetime.now(timezone.utc).strftime("%H:%M:%S"),
            "type": f"{sub}.{log_type}",
            "invoice_id": inv_id,
            "amount": amt,
        })

        if log_type == "credited":
            webhook_stats["total_amount_cents"] += amt
            _dispatch_invoice(log)
    else:
        webhook_history.appendleft({
            "time": datetime.now(timezone.utc).strftime("%H:%M:%S"),
            "type": sub,
            "invoice_id": "N/A",
            "amount": 0,
        })


def _dispatch_invoice(log: Any) -> None:
    invoice = log.invoice
    if log.type != "credited":
        logger.debug("Invoice %s — log type '%s' ignorado.", invoice.id, log.type)
        return

    logger.info(
        "Invoice %s credited — amount: %d ¢, fee: %d ¢.",
        invoice.id,
        invoice.amount,
        getattr(invoice, "fee", 0),
    )

    transfer = forward_payment(
        invoice_id=invoice.id,
        credited_amount=invoice.amount,
        fee=getattr(invoice, "fee", 0),
    )

    try:
        transfer_id = transfer.id if transfer else None
        mark_invoice_received(invoice_id=invoice.id, transfer_id=transfer_id)
    except Exception as exc:
        logger.error(
            "Falha ao atualizar status da invoice '%s' no banco: %s",
            invoice.id, exc, exc_info=True,
        )


def _process(item: dict) -> None:
    content: str   = item["content"]
    signature: str = item["signature"]
    is_mock: bool  = item["is_mock"]

    event: Any = None
    try:
        if is_mock:
            resp = requests.get("http://127.0.0.1:9090/v2/public-key").json()
            pub_key_pem = resp["publicKeys"][0]["content"]
            pub_key_obj = PublicKey.fromPem(pub_key_pem)

            try:
                sig_obj = Signature.fromBase64(signature)
            except Exception:
                raise starkbank.error.InvalidSignatureError("Formato de assinatura Base64 inválido no Mock")

            if not Ecdsa.verify(content, sig_obj, pub_key_obj):
                raise starkbank.error.InvalidSignatureError("Assinatura Mock não confere!")

            data = json.loads(content)
            event = MockEvent(data.get("event", data))

        else:
            event = starkbank.event.parse(content=content, signature=signature)

    except starkbank.error.InvalidSignatureError as exc:
        logger.warning("Worker: assinatura inválida — %s", exc)
        return
    except Exception as exc:
        logger.error("Worker: erro ao processar evento — %s", exc, exc_info=True)
        return

    _record_and_handle(event)


def _worker_loop() -> None:
    logger.info("Event queue worker iniciado.")
    while True:
        item = event_queue.get()
        try:
            _process(item)
        except Exception as exc:
            logger.error("Worker: exceção não tratada — %s", exc, exc_info=True)
        finally:
            event_queue.task_done()


def start_worker() -> None:
    t = threading.Thread(target=_worker_loop, daemon=True, name="event-queue-worker")
    t.start()