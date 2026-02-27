"""
Estado compartilhado entre app.webhook e app.queue_worker.

Mantido em módulo separado para evitar importação circular.
"""

from collections import deque


# ── Histórico e estatísticas de webhooks ─────────────────────────────────────

webhook_history: deque = deque(maxlen=50)

webhook_stats: dict = {
    "total_received": 0,
    "total_amount_cents": 0,
    "errors": 0,
    "last_event_time": None,
}


# ── Dataclasses para modo Mock ────────────────────────────────────────────────

class MockInvoice:
    id: str
    amount: int
    fee: int

    def __init__(self, data: dict):
        self.id = str(data.get("id", ""))
        self.amount = int(data.get("amount", 0))
        self.fee = int(data.get("fee", 0))


class MockLog:
    type: str
    invoice: MockInvoice

    def __init__(self, data: dict):
        self.type = str(data.get("type", ""))
        self.invoice = MockInvoice(data.get("invoice", {}))


class MockEvent:
    subscription: str
    id: str
    log: MockLog

    def __init__(self, data: dict):
        self.subscription = str(data.get("subscription", ""))
        self.id = str(data.get("id", ""))
        self.log = MockLog(data.get("log", {}))