"""
app/webhook.py
==============
Flask application that receives and processes Stark Bank webhook events.

starkbank.event.parse() automatically fetches Stark Bank's public key and
verifies the Digital-Signature header using the starkbank-ecdsa library.
"""

import logging

import starkbank
from flask import Flask, jsonify, request

from app.transfers import forward_payment

logger = logging.getLogger(__name__)

app = Flask(__name__)


@app.get("/health")
def health():
    """Liveness probe for load-balancers and Cloud Run."""
    return jsonify({"status": "ok"}), 200


@app.post("/webhook")
def webhook():
    """
    Entry point for all Stark Bank event callbacks.

    Always returns 200 OK for valid requests so Stark Bank does not retry
    already-processed events.
    """
    try:
        event = starkbank.event.parse(
            content=request.data.decode("utf-8"),
            signature=request.headers.get("Digital-Signature", ""),
        )
    except starkbank.error.InvalidSignatureError:
        logger.warning("Webhook rejected — invalid Digital-Signature header.")
        return jsonify({"error": "invalid signature"}), 401
    except Exception as exc:  # noqa: BLE001
        logger.error("Failed to parse webhook event: %s", exc)
        return jsonify({"error": "parse error"}), 400

    logger.info("Event received — subscription=%s id=%s", event.subscription, event.id)

    if event.subscription == "invoice":
        _handle_invoice_event(event.log)

    return jsonify({"status": "received"}), 200


def _handle_invoice_event(log) -> None:
    """React to invoice log entries; only 'credited' triggers a Transfer."""
    invoice = log.invoice

    if log.type != "credited":
        logger.debug("Invoice %s — log type '%s' ignored.", invoice.id, log.type)
        return

    logger.info(
        "Invoice %s credited — amount: %d ¢, fee: %d ¢.",
        invoice.id, invoice.amount, invoice.fee,
    )
    forward_payment(
        invoice_id=invoice.id,
        credited_amount=invoice.amount,
        fee=invoice.fee,
    )
