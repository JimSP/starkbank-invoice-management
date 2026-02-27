import os
import time
import json
import logging
import psutil
from datetime import datetime, timezone
from typing import Any

from flask import Flask, jsonify, request, render_template_string

import starkbank

from app.transfers import forward_payment
from app.config import config
from app.state import MockEvent, MockInvoice, MockLog, webhook_history, webhook_stats


logger = logging.getLogger(__name__)

app = Flask(__name__)

START_TIME = time.time()


@app.get("/health")
def health():
    uptime_seconds = int(time.time() - START_TIME)
    cpu_usage = psutil.cpu_percent(interval=None)
    memory = psutil.virtual_memory()
    disk = psutil.disk_usage('/')

    payload = {
        "status": "ok",
        "timestamp": datetime.now(timezone.utc).isoformat().replace("+00:00", "Z"),
        "service": "starkbank-webhook-manager",
        "telemetry": {
            "uptime_seconds": uptime_seconds,
            "cpu": {"usage_percent": cpu_usage, "cores": psutil.cpu_count()},
            "memory": {"total_mb": memory.total // (1024 * 1024), "available_mb": memory.available // (1024 * 1024), "used_percent": memory.percent},
            "disk": {"free_gb": round(disk.free / (1024**3), 2), "used_percent": disk.percent}
        }
    }

    if memory.percent > 95 or cpu_usage > 95:
        payload["status"] = "warning"
        payload["message"] = "High resource usage detected"

    return jsonify(payload), 200


@app.post("/webhook")
def webhook():
    """Recebe o callback, enfileira e responde imediatamente."""
    # Import local para evitar importação circular no nível do módulo
    from app.queue_worker import event_queue

    webhook_stats["total_received"] += 1
    webhook_stats["last_event_time"] = datetime.now(timezone.utc).isoformat()

    content = request.data.decode("utf-8")
    signature = request.headers.get("Digital-Signature", "")

    if not content:
        webhook_stats["errors"] += 1
        return jsonify({"error": "empty body"}), 400

    event_queue.put({
        "content": content,
        "signature": signature,
        "is_mock": os.environ.get("USE_MOCK_API", "false").lower() == "true",
    })

    return jsonify({"status": "queued"}), 200


def _handle_invoice_event(log) -> None:
    invoice = log.invoice

    if log.type != "credited":
        logger.debug("Invoice %s — log type '%s' ignored.", invoice.id, log.type)
        return

    logger.info("Invoice %s credited — amount: %d ¢, fee: %d ¢.", invoice.id, invoice.amount, getattr(invoice, 'fee', 0))
    forward_payment(invoice_id=invoice.id, credited_amount=invoice.amount, fee=getattr(invoice, 'fee', 0))


@app.get("/")
def dashboard():
    from app.scheduler import job_history

    mock_active = os.environ.get("USE_MOCK_API", "false").lower() == "true"

    html_template = """
    <!DOCTYPE html>
    <html lang="pt-br">
    <head>
        <meta charset="UTF-8">
        <title>Stark Bank Ops Dashboard</title>
        <script src="https://cdn.tailwindcss.com"></script>
    </head>
    <body class="bg-slate-900 text-slate-100 p-8 font-sans">
        <div class="max-w-6xl mx-auto">
            <div class="flex justify-between items-center mb-8 border-b border-slate-700 pb-4">
                <h1 class="text-3xl font-bold">Stark Bank Dashboard</h1>
                <span class="px-3 py-1 rounded-full text-xs font-bold {{ 'bg-amber-500/20 text-amber-500 border border-amber-500/50' if mock_active else 'bg-emerald-500/20 text-emerald-500 border border-emerald-500/50' }}">
                    {{ 'MODO MOCK ATIVO' if mock_active else 'SANDBOX REAL' }}
                </span>
            </div>

            <div class="grid grid-cols-1 md:grid-cols-3 gap-6 mb-8">
                <div class="bg-slate-800 p-6 rounded-xl border border-slate-700 shadow-lg">
                    <p class="text-slate-400 text-sm mb-2">Webhooks Recebidos</p>
                    <p class="text-4xl font-mono">{{ stats.total_received }}</p>
                </div>
                <div class="bg-slate-800 p-6 rounded-xl border border-slate-700 shadow-lg">
                    <p class="text-slate-400 text-sm mb-2">Volume Processado</p>
                    <p class="text-4xl font-mono text-emerald-400">R$ {{ "%.2f"|format(stats.total_amount_cents / 100) }}</p>
                </div>
                <div class="bg-slate-800 p-6 rounded-xl border border-slate-700 shadow-lg">
                    <p class="text-slate-400 text-sm mb-2">Erros e Rejeições</p>
                    <p class="text-4xl font-mono {{ 'text-red-400' if stats.errors > 0 else 'text-slate-100' }}">{{ stats.errors }}</p>
                </div>
            </div>

            <h2 class="text-xl font-bold mb-4 text-blue-400">⚙️ Atividade do Scheduler (Envio)</h2>
            <div class="bg-slate-800 rounded-xl border border-slate-700 overflow-hidden shadow-lg mb-8">
                <table class="w-full text-left text-sm">
                    <thead class="bg-slate-700/50 text-slate-300 uppercase">
                        <tr>
                            <th class="p-4">Horário (UTC)</th>
                            <th class="p-4">Status</th>
                            <th class="p-4">Qtd Invoices</th>
                            <th class="p-4">IDs Gerados / Erros</th>
                        </tr>
                    </thead>
                    <tbody class="divide-y divide-slate-700">
                        {% for run in scheduler_history %}
                        <tr class="hover:bg-slate-700/30">
                            <td class="p-4 font-mono">{{ run.timestamp }}</td>
                            <td class="p-4">
                                <span class="px-2 py-1 rounded text-[10px] font-bold uppercase {{ 'bg-emerald-500/20 text-emerald-400' if run.status == 'success' else 'bg-red-500/20 text-red-400' }}">
                                    {{ run.status }}
                                </span>
                            </td>
                            <td class="p-4 font-mono">{{ run.invoices_issued }}</td>
                            <td class="p-4 text-xs text-slate-400 max-w-md truncate">
                                {{ run.error if run.error else run.ids | join(', ') }}
                            </td>
                        </tr>
                        {% endfor %}
                        {% if not scheduler_history %}
                        <tr><td colspan="4" class="p-4 text-center text-slate-500">Nenhuma execução registrada ainda.</td></tr>
                        {% endif %}
                    </tbody>
                </table>
            </div>

            <h2 class="text-xl font-bold mb-4 text-emerald-400">📥 Eventos do Webhook (Recebimento)</h2>
            <div class="bg-slate-800 rounded-xl border border-slate-700 overflow-hidden shadow-lg mb-12">
                <table class="w-full text-left text-sm">
                    <thead class="bg-slate-700/50 text-slate-300 uppercase">
                        <tr>
                            <th class="p-4">Horário</th>
                            <th class="p-4">Evento (Sub.Type)</th>
                            <th class="p-4">ID Invoice</th>
                            <th class="p-4">Valor</th>
                        </tr>
                    </thead>
                    <tbody class="divide-y divide-slate-700">
                        {% for ev in webhook_history %}
                        <tr class="hover:bg-slate-700/30">
                            <td class="p-4 font-mono">{{ ev.time }}</td>
                            <td class="p-4"><span class="bg-blue-500/10 text-blue-400 px-2 py-1 rounded text-[10px] font-bold">{{ ev.type }}</span></td>
                            <td class="p-4 font-mono text-slate-400">{{ ev.invoice_id }}</td>
                            <td class="p-4 font-mono">R$ {{ "%.2f"|format(ev.amount / 100) }}</td>
                        </tr>
                        {% endfor %}
                        {% if not webhook_history %}
                        <tr><td colspan="4" class="p-4 text-center text-slate-500">Nenhum evento recebido ainda.</td></tr>
                        {% endif %}
                    </tbody>
                </table>
            </div>
        </div>
        <script>setTimeout(() => location.reload(), 15000);</script>
    </body>
    </html>
    """
    return render_template_string(
        html_template,
        stats=webhook_stats,
        webhook_history=list(webhook_history),
        scheduler_history=list(job_history),
        config=config,
        mock_active=mock_active
    )