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
