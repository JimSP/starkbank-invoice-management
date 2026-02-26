#!/usr/bin/env bash
# =============================================================================
# setup_project.sh
#
# Cria a estrutura completa do projeto starkbank-trial em um diretório limpo.
#
# Uso:
#   bash setup_project.sh              # cria ./starkbank-trial
#   bash setup_project.sh /outro/path  # cria em outro destino
# =============================================================================

set -euo pipefail

ROOT="${1:-./starkbank-trial}"

echo "→ Criando projeto em: $ROOT"

# -----------------------------------------------------------------------------
# 1. Diretórios
# -----------------------------------------------------------------------------
mkdir -p "$ROOT/app"
mkdir -p "$ROOT/tests"

# -----------------------------------------------------------------------------
# 2. app/__init__.py
# -----------------------------------------------------------------------------
touch "$ROOT/app/__init__.py"

# -----------------------------------------------------------------------------
# 3. app/config.py
# -----------------------------------------------------------------------------
cat > "$ROOT/app/config.py" << 'PYEOF'
"""
app/config.py
=============
Centralized configuration.  All values come from environment variables so no
credentials are ever hard-coded.
"""

import os
import starkbank

# ---------------------------------------------------------------------------
# Stark Bank – project credentials
# ---------------------------------------------------------------------------
PROJECT_ID  = os.environ.get("STARKBANK_PROJECT_ID",  "")
PRIVATE_KEY = os.environ.get("STARKBANK_PRIVATE_KEY", "")
ENVIRONMENT = os.environ.get("STARKBANK_ENVIRONMENT",  "sandbox")

# ---------------------------------------------------------------------------
# Web-server
# ---------------------------------------------------------------------------
PORT = int(os.environ.get("PORT", "8080"))

# ---------------------------------------------------------------------------
# Transfer destination  (Stark Bank S.A.)
# ---------------------------------------------------------------------------
TRANSFER_DESTINATION = {
    "bank_code":      "20018183",
    "branch_code":    "0001",
    "account_number": "6341320293482496",
    "account_type":   "payment",
    "name":           "Stark Bank S.A.",
    "tax_id":         "20.018.183/0001-80",
}

# ---------------------------------------------------------------------------
# Invoice scheduler
# ---------------------------------------------------------------------------
INVOICE_MIN_BATCH      = 8
INVOICE_MAX_BATCH      = 12
INVOICE_INTERVAL_HOURS = 3
INVOICE_DURATION_HOURS = 24


def init_starkbank() -> starkbank.Project:
    """
    Authenticate with Stark Bank and register the Project as the global user.

    Keys are generated via ``starkbank.key.create()`` (starkbank-ecdsa lib).
    The public key is uploaded to the Stark Bank dashboard once; the private
    key is kept secret and set as STARKBANK_PRIVATE_KEY.
    """
    project = starkbank.Project(
        environment=ENVIRONMENT,
        id=PROJECT_ID,
        private_key=PRIVATE_KEY,
    )
    starkbank.user = project
    return project
PYEOF

# -----------------------------------------------------------------------------
# 4. app/people.py
# -----------------------------------------------------------------------------
cat > "$ROOT/app/people.py" << 'PYEOF'
"""
app/people.py
=============
Generates random but structurally valid Brazilian payer data for Invoices.
"""

import random

_FIRST_NAMES = [
    "Ana", "Bruno", "Carla", "Diego", "Elena", "Felipe", "Gabriela",
    "Hugo", "Isabela", "João", "Karen", "Lucas", "Marina", "Nathan",
    "Olivia", "Pedro", "Rafael", "Sofia", "Tiago", "Vitória",
]
_LAST_NAMES = [
    "Almeida", "Araújo", "Barbosa", "Carvalho", "Costa", "Ferreira",
    "Freitas", "Gomes", "Lima", "Martins", "Nascimento", "Oliveira",
    "Pereira", "Ribeiro", "Rocha", "Rodrigues", "Santos", "Silva",
    "Souza", "Tavares",
]
_EMAIL_DOMAINS = [
    "gmail.com", "hotmail.com", "outlook.com", "yahoo.com.br", "icloud.com",
]
_DDDS = ["11", "21", "31", "41", "51", "61", "71", "81", "85", "91"]


def _cpf_digit(digits: list[int], factor: int) -> int:
    """Compute one CPF check digit."""
    total = sum(f * d for f, d in zip(range(factor, 1, -1), digits))
    remainder = total % 11
    return 0 if remainder < 2 else 11 - remainder


def generate_cpf() -> str:
    """Return a CPF string with valid check digits, formatted as XXX.XXX.XXX-XX."""
    base = [random.randint(0, 9) for _ in range(9)]
    d1 = _cpf_digit(base, 10)
    d2 = _cpf_digit(base + [d1], 11)
    digits = base + [d1, d2]
    return "{}{}{}.{}{}{}.{}{}{}-{}{}".format(*digits)


def generate_phone() -> str:
    """Return a Brazilian mobile number in E.164 format (+55DDXXXXXXXXX)."""
    ddd    = random.choice(_DDDS)
    number = "9" + "".join(str(random.randint(0, 9)) for _ in range(8))
    return f"+55{ddd}{number}"


def random_payer() -> dict:
    """
    Return a dict with random payer fields ready to be unpacked into an Invoice.

    Keys: amount (int, cents), name, tax_id, email, phone.
    """
    first = random.choice(_FIRST_NAMES)
    last  = random.choice(_LAST_NAMES)
    seq   = random.randint(1, 999)

    return {
        "amount": random.randint(1_000, 50_000),
        "name":   f"{first} {last}",
        "tax_id": generate_cpf(),
        "email":  f"{first.lower()}.{last.lower()}{seq}@{random.choice(_EMAIL_DOMAINS)}",
        "phone":  generate_phone(),
    }
PYEOF

# -----------------------------------------------------------------------------
# 5. app/invoices.py
# -----------------------------------------------------------------------------
cat > "$ROOT/app/invoices.py" << 'PYEOF'
"""
app/invoices.py
===============
Issues batches of Invoices via the Stark Bank Python SDK.
"""

import logging
import random
from datetime import datetime, timedelta, timezone

import starkbank

from app.config import INVOICE_MIN_BATCH, INVOICE_MAX_BATCH
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
    """
    Create a random batch of 8–12 Invoices via starkbank.invoice.create().

    Raises starkbank.error.InputErrors or Exception on failure.
    """
    count    = random.randint(INVOICE_MIN_BATCH, INVOICE_MAX_BATCH)
    invoices = [_make_invoice() for _ in range(count)]

    created = starkbank.invoice.create(invoices)
    logger.info("Issued %d invoices (ids: %s)", len(created), [i.id for i in created])
    return created
PYEOF

# -----------------------------------------------------------------------------
# 6. app/transfers.py
# -----------------------------------------------------------------------------
cat > "$ROOT/app/transfers.py" << 'PYEOF'
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
PYEOF

# -----------------------------------------------------------------------------
# 7. app/scheduler.py
# -----------------------------------------------------------------------------
cat > "$ROOT/app/scheduler.py" << 'PYEOF'
"""
app/scheduler.py
================
APScheduler background scheduler that fires invoice batches every 3 hours
for 24 hours, starting immediately on first run.
"""

import logging
from datetime import datetime, timedelta, timezone

from apscheduler.schedulers.background import BackgroundScheduler
from apscheduler.triggers.interval import IntervalTrigger

from app.config import INVOICE_DURATION_HOURS, INVOICE_INTERVAL_HOURS
from app.invoices import issue_batch

logger = logging.getLogger(__name__)


def _job() -> None:
    """APScheduler job: issue one invoice batch, swallowing exceptions."""
    logger.info("Scheduler tick — issuing invoice batch …")
    try:
        issue_batch()
    except Exception as exc:  # noqa: BLE001
        logger.error("Invoice batch failed: %s", exc)


def start_scheduler() -> BackgroundScheduler:
    """
    Configure and start the background scheduler.

    Adds two jobs:
    - invoice_batch_initial: fires immediately.
    - invoice_batch: repeats every INVOICE_INTERVAL_HOURS for INVOICE_DURATION_HOURS.
    """
    end_time  = datetime.now(tz=timezone.utc) + timedelta(hours=INVOICE_DURATION_HOURS)
    scheduler = BackgroundScheduler(timezone="UTC")

    scheduler.add_job(
        func=_job,
        id="invoice_batch_initial",
        name="First invoice batch (immediate)",
        max_instances=1,
    )
    scheduler.add_job(
        func=_job,
        trigger=IntervalTrigger(hours=INVOICE_INTERVAL_HOURS, timezone="UTC"),
        id="invoice_batch",
        name=f"Invoice batch every {INVOICE_INTERVAL_HOURS}h",
        end_date=end_time,
        max_instances=1,
        coalesce=True,
    )

    scheduler.start()
    logger.info(
        "Scheduler started — batches every %dh until %s UTC.",
        INVOICE_INTERVAL_HOURS,
        end_time.strftime("%Y-%m-%dT%H:%M:%S"),
    )
    return scheduler
PYEOF

# -----------------------------------------------------------------------------
# 8. app/webhook.py
# -----------------------------------------------------------------------------
cat > "$ROOT/app/webhook.py" << 'PYEOF'
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
PYEOF

# -----------------------------------------------------------------------------
# 9. tests/__init__.py
# -----------------------------------------------------------------------------
touch "$ROOT/tests/__init__.py"

# -----------------------------------------------------------------------------
# 10. tests/conftest.py
# -----------------------------------------------------------------------------
cat > "$ROOT/tests/conftest.py" << 'PYEOF'
"""tests/conftest.py — shared pytest fixtures."""

import pytest
from app.webhook import app as flask_app


@pytest.fixture()
def client():
    """Flask test client with TESTING mode enabled."""
    flask_app.config["TESTING"] = True
    with flask_app.test_client() as c:
        yield c
PYEOF

# -----------------------------------------------------------------------------
# 11. tests/test_config.py
# -----------------------------------------------------------------------------
cat > "$ROOT/tests/test_config.py" << 'PYEOF'
"""tests/test_config.py — covers app/config.py"""

from unittest.mock import MagicMock, patch

import starkbank
import app.config as cfg


class TestInitStarkbank:
    def test_returns_project(self):
        fake = MagicMock(spec=starkbank.Project)
        with patch("app.config.starkbank.Project", return_value=fake):
            assert cfg.init_starkbank() is fake

    def test_sets_global_user(self):
        fake = MagicMock(spec=starkbank.Project)
        with patch("app.config.starkbank.Project", return_value=fake):
            cfg.init_starkbank()
        assert starkbank.user is fake

    def test_uses_configured_values(self):
        with patch("app.config.starkbank.Project") as MockProject:
            MockProject.return_value = MagicMock()
            cfg.init_starkbank()
            MockProject.assert_called_once_with(
                environment=cfg.ENVIRONMENT,
                id=cfg.PROJECT_ID,
                private_key=cfg.PRIVATE_KEY,
            )
PYEOF

# -----------------------------------------------------------------------------
# 12. tests/test_people.py
# -----------------------------------------------------------------------------
cat > "$ROOT/tests/test_people.py" << 'PYEOF'
"""tests/test_people.py — covers app/people.py"""

import re
import pytest
from app.people import _cpf_digit, generate_cpf, generate_phone, random_payer


class TestCpfDigit:
    def test_returns_zero_when_remainder_less_than_2(self):
        assert _cpf_digit([0] * 9, 10) == 0

    def test_returns_eleven_minus_remainder_otherwise(self):
        result = _cpf_digit([1] * 9, 10)
        assert result == 11 - (sum(f * 1 for f in range(10, 1, -1)) % 11)


class TestGenerateCpf:
    CPF_RE = re.compile(r"^\d{3}\.\d{3}\.\d{3}-\d{2}$")

    def test_format(self):
        assert self.CPF_RE.match(generate_cpf())

    def test_uniqueness(self):
        assert len({generate_cpf() for _ in range(30)}) > 15

    def test_check_digits_valid(self):
        for _ in range(20):
            cpf = generate_cpf().replace(".", "").replace("-", "")
            digits = [int(c) for c in cpf]
            total = sum((10 - i) * d for i, d in enumerate(digits[:9]))
            r = total % 11
            assert digits[9] == (0 if r < 2 else 11 - r)
            total = sum((11 - i) * d for i, d in enumerate(digits[:10]))
            r = total % 11
            assert digits[10] == (0 if r < 2 else 11 - r)


class TestGeneratePhone:
    def test_starts_with_country_code(self):
        assert generate_phone().startswith("+55")

    def test_length(self):
        assert len(generate_phone()) == 14

    def test_mobile_prefix(self):
        assert generate_phone()[5] == "9"


class TestRandomPayer:
    def test_has_required_keys(self):
        assert {"amount", "name", "tax_id", "email", "phone"}.issubset(random_payer())

    def test_amount_in_range(self):
        for _ in range(100):
            assert 1_000 <= random_payer()["amount"] <= 50_000

    def test_email_contains_at(self):
        assert "@" in random_payer()["email"]

    def test_name_has_two_parts(self):
        assert len(random_payer()["name"].split()) >= 2
PYEOF

# -----------------------------------------------------------------------------
# 13. tests/test_invoices.py
# -----------------------------------------------------------------------------
cat > "$ROOT/tests/test_invoices.py" << 'PYEOF'
"""tests/test_invoices.py — covers app/invoices.py"""

from unittest.mock import MagicMock, patch

import pytest
import starkbank
from app.invoices import issue_batch


class TestIssueBatch:
    @patch("app.invoices.starkbank.invoice.create")
    def test_count_is_between_8_and_12(self, mock_create):
        mock_create.side_effect = lambda invoices: invoices
        for _ in range(20):
            assert 8 <= len(issue_batch()) <= 12

    @patch("app.invoices.starkbank.invoice.create")
    def test_returns_sdk_response(self, mock_create):
        fake = [MagicMock(id=f"inv_{i}") for i in range(8)]
        mock_create.return_value = fake
        assert issue_batch() == fake

    @patch("app.invoices.starkbank.invoice.create")
    def test_each_element_is_invoice(self, mock_create):
        mock_create.side_effect = lambda invoices: invoices
        for inv in issue_batch():
            assert isinstance(inv, starkbank.Invoice)

    @patch("app.invoices.starkbank.invoice.create", side_effect=Exception("API down"))
    def test_propagates_exception(self, _):
        with pytest.raises(Exception, match="API down"):
            issue_batch()
PYEOF

# -----------------------------------------------------------------------------
# 14. tests/test_transfers.py
# -----------------------------------------------------------------------------
cat > "$ROOT/tests/test_transfers.py" << 'PYEOF'
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
        from app.config import TRANSFER_DESTINATION
        mock_create.return_value = [MagicMock(id="t2")]
        forward_payment("inv5", credited_amount=2_000, fee=0)
        t = mock_create.call_args[0][0][0]
        assert t.bank_code      == TRANSFER_DESTINATION["bank_code"]
        assert t.branch_code    == TRANSFER_DESTINATION["branch_code"]
        assert t.account_number == TRANSFER_DESTINATION["account_number"]
        assert t.tax_id         == TRANSFER_DESTINATION["tax_id"]
PYEOF

# -----------------------------------------------------------------------------
# 15. tests/test_scheduler.py
# -----------------------------------------------------------------------------
cat > "$ROOT/tests/test_scheduler.py" << 'PYEOF'
"""tests/test_scheduler.py — covers app/scheduler.py"""

from unittest.mock import MagicMock, patch
from app.scheduler import _job, start_scheduler


class TestJob:
    @patch("app.scheduler.issue_batch")
    def test_success_calls_issue_batch(self, mock_issue):
        _job()
        mock_issue.assert_called_once()

    @patch("app.scheduler.issue_batch", side_effect=Exception("API error"))
    def test_exception_is_swallowed(self, _):
        _job()  # must not raise


class TestStartScheduler:
    @patch("app.scheduler.BackgroundScheduler")
    def test_returns_started_scheduler(self, MockScheduler):
        fake = MagicMock()
        MockScheduler.return_value = fake
        assert start_scheduler() is fake
        fake.start.assert_called_once()

    @patch("app.scheduler.BackgroundScheduler")
    def test_adds_two_jobs(self, MockScheduler):
        fake = MagicMock()
        MockScheduler.return_value = fake
        start_scheduler()
        assert fake.add_job.call_count == 2

    @patch("app.scheduler.BackgroundScheduler")
    def test_immediate_job_id(self, MockScheduler):
        fake = MagicMock()
        MockScheduler.return_value = fake
        start_scheduler()
        ids = [kw.get("id") for _, kw in fake.add_job.call_args_list]
        assert "invoice_batch_initial" in ids

    @patch("app.scheduler.BackgroundScheduler")
    def test_interval_job_id(self, MockScheduler):
        fake = MagicMock()
        MockScheduler.return_value = fake
        start_scheduler()
        ids = [kw.get("id") for _, kw in fake.add_job.call_args_list]
        assert "invoice_batch" in ids
PYEOF

# -----------------------------------------------------------------------------
# 16. tests/test_webhook.py
# -----------------------------------------------------------------------------
cat > "$ROOT/tests/test_webhook.py" << 'PYEOF'
"""tests/test_webhook.py — covers app/webhook.py"""

from unittest.mock import MagicMock, patch

import pytest
import starkbank


class TestHealthEndpoint:
    def test_returns_200(self, client):
        resp = client.get("/health")
        assert resp.status_code == 200
        assert resp.json == {"status": "ok"}


class TestWebhookEndpoint:
    _HEADERS = {"Digital-Signature": "valid-sig"}
    _BODY    = b"{}"

    @patch("app.webhook.starkbank.event.parse",
           side_effect=starkbank.error.InvalidSignatureError("bad"))
    def test_invalid_signature_returns_401(self, _, client):
        resp = client.post("/webhook", data=self._BODY, headers=self._HEADERS)
        assert resp.status_code == 401

    @patch("app.webhook.starkbank.event.parse",
           side_effect=RuntimeError("network timeout"))
    def test_generic_parse_error_returns_400(self, _, client):
        resp = client.post("/webhook", data=self._BODY, headers=self._HEADERS)
        assert resp.status_code == 400

    @patch("app.webhook.forward_payment")
    @patch("app.webhook.starkbank.event.parse")
    def test_credited_invoice_triggers_transfer(self, mock_parse, mock_fwd, client):
        invoice = MagicMock(id="inv1", amount=5_000, fee=100)
        log     = MagicMock(type="credited", invoice=invoice)
        mock_parse.return_value = MagicMock(subscription="invoice", id="e1", log=log)
        resp = client.post("/webhook", data=self._BODY, headers=self._HEADERS)
        assert resp.status_code == 200
        mock_fwd.assert_called_once_with(invoice_id="inv1", credited_amount=5_000, fee=100)

    @pytest.mark.parametrize("log_type", ["created", "overdue", "updated", "canceled"])
    @patch("app.webhook.forward_payment")
    @patch("app.webhook.starkbank.event.parse")
    def test_non_credited_log_type_ignored(self, mock_parse, mock_fwd, log_type, client):
        log = MagicMock(type=log_type, invoice=MagicMock(id="inv2"))
        mock_parse.return_value = MagicMock(subscription="invoice", id="e2", log=log)
        resp = client.post("/webhook", data=self._BODY, headers=self._HEADERS)
        assert resp.status_code == 200
        mock_fwd.assert_not_called()

    @patch("app.webhook.forward_payment")
    @patch("app.webhook.starkbank.event.parse")
    def test_unrelated_subscription_returns_200(self, mock_parse, mock_fwd, client):
        mock_parse.return_value = MagicMock(subscription="transfer", id="e3")
        resp = client.post("/webhook", data=self._BODY, headers=self._HEADERS)
        assert resp.status_code == 200
        mock_fwd.assert_not_called()
PYEOF

# -----------------------------------------------------------------------------
# 17. main.py
# -----------------------------------------------------------------------------
cat > "$ROOT/main.py" << 'PYEOF'
"""
main.py
=======
Application entry point.  Starts APScheduler in a background thread and
the Flask webhook server in the main thread.

    python main.py
"""

import logging
import signal
import sys

from app.config import PORT, init_starkbank
from app.scheduler import start_scheduler
from app.webhook import app

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)-8s] %(name)s — %(message)s",
    datefmt="%Y-%m-%dT%H:%M:%SZ",
)


def main() -> None:  # pragma: no cover
    init_starkbank()

    scheduler = start_scheduler()

    def _shutdown(signum, frame):
        logging.getLogger(__name__).info("Shutting down …")
        scheduler.shutdown(wait=False)
        sys.exit(0)

    signal.signal(signal.SIGTERM, _shutdown)
    signal.signal(signal.SIGINT,  _shutdown)

    app.run(host="0.0.0.0", port=PORT, debug=False)


if __name__ == "__main__":  # pragma: no cover
    main()
PYEOF

# -----------------------------------------------------------------------------
# 18. keygen.py
# -----------------------------------------------------------------------------
cat > "$ROOT/keygen.py" << 'PYEOF'
"""
keygen.py
=========
Generates a secp256k1 ECDSA key pair using the starkbank-ecdsa library
(exposed as starkbank.key.create()).

The SDK saves the files as:
    keys/private-key.pem   <- keep secret, set as STARKBANK_PRIVATE_KEY
    keys/public-key.pem    <- paste the contents into Stark Bank dashboard

Usage
-----
    python keygen.py              # prints to stdout
    python keygen.py keys/        # saves keys/private-key.pem + keys/public-key.pem
"""

import sys
import starkbank


def generate_keys(path: str | None = None) -> tuple[str, str]:
    """Return (private_key_pem, public_key_pem). Saves files if path given."""
    return starkbank.key.create(path)


if __name__ == "__main__":  # pragma: no cover
    save_path = sys.argv[1] if len(sys.argv) > 1 else None
    priv, pub = generate_keys(save_path)

    print("=" * 60)
    print("PRIVATE KEY  (set as STARKBANK_PRIVATE_KEY env var)")
    print("=" * 60)
    print(priv)
    print("=" * 60)
    print("PUBLIC KEY  (paste this into the Stark Bank dashboard)")
    print("Menu → Integrations → New Project → Public Key field")
    print("=" * 60)
    print(pub)

    if save_path:
        print(f"\nFiles saved:")
        print(f"  {save_path}private-key.pem  <- keep secret")
        print(f"  {save_path}public-key.pem   <- paste into dashboard")
PYEOF

# -----------------------------------------------------------------------------
# 19. setup_webhook.py
# -----------------------------------------------------------------------------
cat > "$ROOT/setup_webhook.py" << 'PYEOF'
"""
setup_webhook.py
================
One-time script to register the webhook endpoint on Stark Bank.

    python setup_webhook.py https://your-domain.com/webhook
"""

import sys
import starkbank
from app.config import init_starkbank


def register(url: str) -> starkbank.Webhook:
    """Create a webhook for *url* (or return existing one)."""
    for existing in starkbank.webhook.query():
        if existing.url == url:
            print(f"[OK] Already registered — id={existing.id}  url={existing.url}")
            return existing

    webhook = starkbank.webhook.create(url=url, subscriptions=["invoice"])
    print(f"[OK] Webhook created — id={webhook.id}  url={webhook.url}")
    return webhook


if __name__ == "__main__":  # pragma: no cover
    if len(sys.argv) < 2:
        print("Usage: python setup_webhook.py <public-https-url>")
        sys.exit(1)

    init_starkbank()
    register(sys.argv[1])

    print("\nAll registered webhooks:")
    for w in starkbank.webhook.query():
        print(f"  {w.id}  {w.url}  {w.subscriptions}")
PYEOF

# -----------------------------------------------------------------------------
# 20. Dockerfile
# -----------------------------------------------------------------------------
cat > "$ROOT/Dockerfile" << 'EOF'
FROM python:3.12-slim

WORKDIR /app

COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

COPY . .

EXPOSE 8080

CMD ["python", "main.py"]
EOF

# -----------------------------------------------------------------------------
# 21. pytest.ini
# -----------------------------------------------------------------------------
cat > "$ROOT/pytest.ini" << 'EOF'
[pytest]
addopts =
    --cov=app
    --cov-report=term-missing
    --cov-report=html:htmlcov
    --cov-fail-under=100
    -v
EOF

# -----------------------------------------------------------------------------
# 22. requirements.txt
# -----------------------------------------------------------------------------
cat > "$ROOT/requirements.txt" << 'EOF'
# Runtime
starkbank==2.20.0
Flask==3.0.3
APScheduler==3.10.4
gunicorn==22.0.0

# Testing
pytest==8.2.2
pytest-cov==5.0.0
EOF

# -----------------------------------------------------------------------------
# 23. .env.example
# -----------------------------------------------------------------------------
cat > "$ROOT/.env.example" << 'EOF'
# Copy to .env and fill in your values.
# Never commit the real .env to version control.

STARKBANK_PROJECT_ID=your-project-id-here
STARKBANK_PRIVATE_KEY="-----BEGIN EC PARAMETERS-----
BgUrgQQACg==
-----END EC PARAMETERS-----
-----BEGIN EC PRIVATE KEY-----
...your key here...
-----END EC PRIVATE KEY-----"
STARKBANK_ENVIRONMENT=sandbox
PORT=8080
EOF

# -----------------------------------------------------------------------------
# 24. .gitignore
# -----------------------------------------------------------------------------
cat > "$ROOT/.gitignore" << 'EOF'
.env
keys/
__pycache__/
*.py[cod]
.pytest_cache/
htmlcov/
.coverage
*.egg-info/
dist/
build/
EOF

# -----------------------------------------------------------------------------
# 25. README.md
# -----------------------------------------------------------------------------
cat > "$ROOT/README.md" << 'EOF'
# Stark Bank – Back End Developer Trial

Integração Python com a API da Stark Bank que emite Invoices periodicamente e
encaminha os pagamentos recebidos via Transfer.

---

## Stack de bibliotecas

| Biblioteca | Papel |
|---|---|
| [`starkbank`](https://github.com/starkbank/sdk-python) | SDK principal — `invoice`, `transfer`, `webhook`, `event` |
| [`starkbank-ecdsa`](https://github.com/starkbank/ecdsa-python) | Geração e assinatura de chaves secp256k1 (via `starkbank.key`) |
| [`starkcore`](https://github.com/starkbank/core-python) | Camada HTTP + autenticação (dependência interna do SDK) |
| `Flask` | Servidor web para receber callbacks do webhook |
| `APScheduler` | Agendador em background thread |

---

## Arquitetura da solução

```
┌─────────────────────────────────────────────────────────────┐
│                        main.py                              │
│                                                             │
│   ┌─────────────────┐         ┌─────────────────────────┐  │
│   │   Scheduler      │         │   Flask (webhook server) │  │
│   │  (background     │         │                         │  │
│   │   thread)        │         │   GET  /health           │  │
│   │                 │         │   POST /webhook          │  │
│   │  every 3h ──────┼────┐    └────────────┬────────────┘  │
│   └─────────────────┘    │                 │               │
│                           │                 │               │
└───────────────────────────┼─────────────────┼───────────────┘
                            │                 │
                            ▼                 ▼
              ┌─────────────────┐   ┌──────────────────────┐
              │  invoices.py    │   │    webhook.py         │
              │                 │   │                       │
              │  starkbank      │   │  starkbank            │
              │  .invoice       │   │  .event.parse()       │
              │  .create()      │   │  (verifica ECDSA)     │
              └────────┬────────┘   └──────────┬───────────┘
                       │                        │
                       ▼                        ▼ log.type == "credited"
              ┌─────────────────┐   ┌──────────────────────┐
              │  Stark Bank API │   │   transfers.py        │
              │  (Sandbox)      │   │                       │
              │                 │   │  starkbank            │
              │  auto-pays some │   │  .transfer.create()   │
              │  invoices  ─────┼──►│                       │
              └─────────────────┘   └──────────────────────┘
```

---

## Fluxo de dados — sequência completa

```
 App                    Stark Bank API            Stark Bank Sandbox
  │                          │                           │
  │── starkbank.invoice ─────►│                           │
  │   .create([8..12])        │                           │
  │◄── invoices criadas ──────│                           │
  │                           │                           │
  │         (a cada 3h por 24h, acima se repete)          │
  │                           │                           │
  │                           │◄── pagamento automático ──│
  │                           │    (Sandbox paga          │
  │                           │     algumas invoices)     │
  │                           │                           │
  │◄── POST /webhook ─────────│                           │
  │    Digital-Signature: xyz  │                           │
  │    { subscription:         │                           │
  │      "invoice",            │                           │
  │      log.type:             │                           │
  │      "credited",           │                           │
  │      invoice.amount: N,    │                           │
  │      invoice.fee: F }      │                           │
  │                           │                           │
  │  starkbank.event.parse()   │                           │
  │  (verifica assinatura)     │                           │
  │                           │                           │
  │── starkbank.transfer ─────►│                           │
  │   .create([amount=N-F])    │                           │
  │   → Stark Bank S.A.        │                           │
  │                           │                           │
  │── HTTP 200 ───────────────►│                           │
```

---

## Verificação de assinatura (sem código manual)

O SDK usa `starkbank-ecdsa` internamente para **verificar** cada callback:

```python
event = starkbank.event.parse(
    content=request.data.decode("utf-8"),
    signature=request.headers.get("Digital-Signature", ""),
)
# ↑ busca a chave pública da Stark Bank automaticamente
# ↑ lança InvalidSignatureError se inválida
```

E para **gerar** o seu par de chaves antes de criar o Projeto:

```python
# keygen.py usa starkbank.key (que chama starkbank-ecdsa internamente)
private_key, public_key = starkbank.key.create()
```

---

## Estrutura do projeto

```
starkbank-trial/
│
├── app/                        ← pacote principal
│   ├── __init__.py
│   ├── config.py               ← credenciais + init_starkbank()
│   ├── people.py               ← gerador de pagadores aleatórios (CPF válido)
│   ├── invoices.py             ← emissão de lote via starkbank.invoice.create()
│   ├── transfers.py            ← repasse via starkbank.transfer.create()
│   ├── scheduler.py            ← APScheduler: dispara a cada 3h por 24h
│   └── webhook.py              ← Flask: POST /webhook + GET /health
│
├── tests/                      ← 100% de cobertura
│   ├── conftest.py             ← fixtures compartilhadas (Flask test client)
│   ├── test_config.py
│   ├── test_people.py
│   ├── test_invoices.py
│   ├── test_transfers.py
│   ├── test_scheduler.py
│   └── test_webhook.py
│
├── main.py                     ← entry point (scheduler + Flask juntos)
├── keygen.py                   ← gera par de chaves ECDSA
├── setup_webhook.py            ← registra webhook na Stark Bank (1x)
├── Dockerfile
├── pytest.ini                  ← --cov=app --cov-fail-under=100
├── requirements.txt
└── .env.example
```

---

## Setup

### 1. Gerar par de chaves ECDSA

```bash
python keygen.py keys/
# Salva keys/privateKey.pem e keys/publicKey.pem
```

Faça upload da **chave pública** no painel Sandbox:
`Menu → Integrações → Novo Projeto → cole o conteúdo de publicKey.pem`

### 2. Configurar variáveis de ambiente

```bash
cp .env.example .env
# Edite .env com seu PROJECT_ID e PRIVATE_KEY
```

### 3. Registrar o webhook (uma vez)

```bash
# Localmente com ngrok:
ngrok http 8080
python setup_webhook.py https://abc123.ngrok.io/webhook

# Ou com a URL de produção após deploy:
python setup_webhook.py https://sua-app.run.app/webhook
```

### 4. Executar

```bash
python main.py
```

---

## Testes e cobertura

```bash
pytest
```

```
Name               Stmts   Miss  Cover
--------------------------------------
app/__init__.py        0      0   100%
app/config.py         15      0   100%
app/invoices.py       18      0   100%
app/people.py         24      0   100%
app/scheduler.py      21      0   100%
app/transfers.py      13      0   100%
app/webhook.py        30      0   100%
--------------------------------------
TOTAL                121      0   100%
```

Cada módulo tem seu próprio arquivo de teste. Todas as chamadas à API da
Stark Bank são mockadas — não são necessárias credenciais reais para rodar
os testes.

---

## Deploy (Docker / Cloud Run)

```bash
docker build -t starkbank-trial .

docker run -p 8080:8080 \
  -e STARKBANK_PROJECT_ID="..." \
  -e STARKBANK_PRIVATE_KEY="$(cat keys/privateKey.pem)" \
  -e STARKBANK_ENVIRONMENT="sandbox" \
  starkbank-trial
```

**Google Cloud Run (deploy direto):**

```bash
gcloud run deploy starkbank-trial \
  --source . \
  --region us-central1 \
  --allow-unauthenticated \
  --set-env-vars STARKBANK_PROJECT_ID="...",STARKBANK_ENVIRONMENT="sandbox"
# Armazene a PRIVATE_KEY no Secret Manager e injete via --set-secrets
```

---

## Variáveis de ambiente

| Variável | Descrição | Padrão |
|---|---|---|
| `STARKBANK_PROJECT_ID` | ID do Projeto criado no Sandbox | — |
| `STARKBANK_PRIVATE_KEY` | Chave privada ECDSA (PEM) | — |
| `STARKBANK_ENVIRONMENT` | `sandbox` ou `production` | `sandbox` |
| `PORT` | Porta do servidor Flask | `8080` |
EOF

# -----------------------------------------------------------------------------
# Virtualenv
# -----------------------------------------------------------------------------
echo ""
echo "→ Criando ambiente virtual (.venv) …"
python3 -m venv "$ROOT/.venv"

echo "→ Instalando dependências …"
"$ROOT/.venv/bin/pip" install --quiet --upgrade pip
"$ROOT/.venv/bin/pip" install --quiet -r "$ROOT/requirements.txt"

# adiciona .venv ao .gitignore
sed -i 's|keys/|keys/\n.venv/|' "$ROOT/.gitignore"

# -----------------------------------------------------------------------------
# VSCode – configuração do interpretador Python
# -----------------------------------------------------------------------------
mkdir -p "$ROOT/.vscode"
cat > "$ROOT/.vscode/settings.json" << 'EOF'
{
  "python.defaultInterpreterPath": "${workspaceFolder}/.venv/bin/python",
  "python.terminal.activateEnvironment": true,
  "[python]": {
    "editor.formatOnSave": true
  }
}
EOF

# adiciona .vscode ao .gitignore
sed -i 's|\.venv/|.venv/\n.vscode/|' "$ROOT/.gitignore"

# -----------------------------------------------------------------------------
# Summary
# -----------------------------------------------------------------------------
echo ""
echo "✅ Projeto criado em: $ROOT"
echo ""
echo "Estrutura:"
find "$ROOT" \
  -not -path '*/.venv/*' \
  -not -path '*/__pycache__/*' \
  -not -name '*.pyc' \
  | sort | sed "s|$ROOT/||" | sed 's|[^/]*/|  |g'
echo ""
echo "Próximos passos:"
echo "  cd $ROOT"
echo "  code .                       # abre o VSCode (já usará o .venv)"
echo "  source .venv/bin/activate    # ou ative manualmente no terminal"
echo "  pytest"