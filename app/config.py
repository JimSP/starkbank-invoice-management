import os
import json
import logging
import starkbank
from dotenv import load_dotenv


class AppConfig:
    def __init__(self, env_file=".env"):
        load_dotenv(env_file)

        self.LOG_LEVEL = self._parse_log_level()
        self.DATABASE_URL = os.environ.get("DATABASE_URL", "sqlite:///data/invoices.db")
        self.APP_PORT  = int(os.environ.get("APP_PORT", 8080))
        self.STARKBANK_PROJECT_ID  = self._get_env_or_raise("STARKBANK_PROJECT_ID")

        starkbank_private_key_path = self._get_env_or_raise("STARKBANK_PRIVATE_KEY")
        with open(starkbank_private_key_path, "r") as f:
            self.STARKBANK_PRIVATE_KEY = f.read()
        
        starkbank_public_key_path = self._get_env_or_raise("STARKBANK_PUBLIC_KEY")
        with open(starkbank_public_key_path, "r") as f:
            self.STARKBANK_PUBLIC_KEY = f.read()

        self.STARKBANK_ENVIRONMENT = os.environ.get("STARKBANK_ENVIRONMENT", "sandbox")
        self.USE_MOCK_API = os.environ.get("USE_MOCK_API", "false").lower() == "true"
        
        self._load_transfer_config()
        self._load_invoice_config()


    @staticmethod
    def _get_env_or_raise(key):
        value = os.environ.get(key)
        if not value or not value.strip():
            raise KeyError(f"❌ CONFIG_ERROR: Variável de ambiente '{key}' é obrigatória no .env")
        return value


    @staticmethod
    def _load_strict_json(path, context_name):
        if not os.path.exists(path):
            raise FileNotFoundError(f"❌ CONFIG_ERROR: Arquivo '{context_name}' não encontrado em: {path}")
        try:
            with open(path, 'r') as f:
                data = json.load(f)
                if not data:
                    raise ValueError(f"❌ CONFIG_ERROR: Arquivo '{path}' está vazio.")
                return data
        except json.JSONDecodeError as e:
            raise ValueError(f"❌ CONFIG_ERROR: JSON inválido em '{path}': {e}")


    @staticmethod
    def _validate_keys(data, required_keys, source_name):
        for key in required_keys:
            if key not in data or data[key] is None:
                raise KeyError(f"❌ CONFIG_ERROR: Chave '{key}' ausente no arquivo '{source_name}'")


    def _parse_log_level(self):
        raw_level = os.environ.get("LOG_LEVEL", "INFO").upper()
        level_map = {
            "DEBUG": logging.DEBUG,
            "INFO": logging.INFO,
            "WARNING": logging.WARNING,
            "ERROR": logging.ERROR,
            "CRITICAL": logging.CRITICAL
        }
        if raw_level not in level_map:
            raise ValueError(f"❌ CONFIG_ERROR: LOG_LEVEL '{raw_level}' inválido no .env. "
                             f"Use: DEBUG, INFO, WARNING, ERROR ou CRITICAL.")
        return level_map[raw_level]


    def _load_transfer_config(self):
        path = os.environ.get("STARTBANK_TRANSFER_CONFIG_PATH", "config/transfer_destination.json")
        data = self._load_strict_json(path, "Transfer Destination")
        self._validate_keys(data, 
            ["bank_code", "branch_code", "account_number", "account_type", "name", "tax_id"], 
            path
        )
        self.BANK_CODE      = data["bank_code"]
        self.BRANCH_CODE    = data["branch_code"]
        self.ACCOUNT_NUMBER = data["account_number"]
        self.ACCOUNT_TYPE   = data["account_type"]
        self.NAME           = data["name"]
        self.TAX_ID         = data["tax_id"]
        self.PLATFORM_FEE   = int(float(data.get("platform_fee", 2.00)) * 100)
        self.TRANSFER_FEE    = int(float(data.get("transfer_fee", 0.05)) * 100)


    def _load_invoice_config(self):
        path = os.environ.get("INVOICE_SCHEDULER_CONFIG_PATH", "config/invoice_scheduler_config.json")
        data = self._load_strict_json(path, "Invoice Scheduler")
        self._validate_keys(data, 
            ["min_batch", "max_batch", "interval_hours", "duration_hours"], 
            path
        )
        self.INVOICE_MIN_BATCH      = int(data["min_batch"])
        self.INVOICE_MAX_BATCH      = int(data["max_batch"])
        self.INVOICE_INTERVAL_HOURS = int(data["interval_hours"])
        self.INVOICE_DURATION_HOURS = int(data["duration_hours"])
        self.RECONCILIATION_INTERVAL_MINUTES = int(data.get("reconciliation_interval_minutes", 15))


    def init_starkbank(self) -> starkbank.Project:
        project = starkbank.Project(
            environment=self.STARKBANK_ENVIRONMENT,
            id=self.STARKBANK_PROJECT_ID,
            private_key=self.STARKBANK_PRIVATE_KEY,
        )
        starkbank.user = project
        return project

config = AppConfig()