"""
app/webhook.py
==============
Flask application that receives and processes Stark Bank webhook events.

starkbank.event.parse() automatically fetches Stark Bank's public key and
verifies the Digital-Signature header using the starkbank-ecdsa library.
"""
import time
import psutil
from datetime import datetime, timezone
import logging
from flask import Flask, jsonify, request

import starkbank

from app.transfers import forward_payment

logger = logging.getLogger(__name__)

app = Flask(__name__)

START_TIME = time.time()


@app.get("/health")
def health():
    # Cálculo de Uptime
    uptime_seconds = int(time.time() - START_TIME)
    
    # Telemetria de Sistema
    cpu_usage = psutil.cpu_percent(interval=None)
    memory = psutil.virtual_memory()
    disk = psutil.disk_usage('/')

    payload = {
        "status": "ok",
        "timestamp": datetime.now(timezone.utc).isoformat().replace("+00:00", "Z"),
        "service": "starkbank-webhook-manager",
        "telemetry": {
            "uptime_seconds": uptime_seconds,
            "cpu": {
                "usage_percent": cpu_usage,
                "cores": psutil.cpu_count()
            },
            "memory": {
                "total_mb": memory.total // (1024 * 1024),
                "available_mb": memory.available // (1024 * 1024),
                "used_percent": memory.percent
            },
            "disk": {
                "free_gb": round(disk.free / (1024**3), 2),
                "used_percent": disk.percent
            }
        }
    }

    # Se a CPU ou Memória estiverem críticas, você pode mudar o status
    # mas ainda retornar 200 para o Load Balancer não matar a máquina precocemente
    if memory.percent > 95 or cpu_usage > 95:
        payload["status"] = "warning"
        payload["message"] = "High resource usage detected"

    return jsonify(payload), 200


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
    except ValueError as exc:
        # Se o JSON estiver quebrado ou o content for inválido
        logger.warning("Webhook rejected — bad payload: %s", exc)
        return jsonify({"error": "parse error"}), 400
    except Exception as exc:
        # Qualquer outro erro: falha de rede do SDK, falta de memória, bugs.
        logger.error("Unexpected internal error during webhook processing: %s", exc, exc_info=True)
        return jsonify({"status": "internal_error"}), 500

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
