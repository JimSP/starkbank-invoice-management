import json
import pytest
from unittest.mock import MagicMock, patch
import starkbank

from app.config import AppConfig, config


def test_load_strict_json_file_not_found():
    with pytest.raises(FileNotFoundError, match="não encontrado em"):
        AppConfig._load_strict_json("arquivo_que_nao_existe.json", "contexto_teste")


def test_load_strict_json_invalid_format(tmp_path):
    d = tmp_path / "bad.json"
    d.write_text("{ invalid json")
    with pytest.raises(ValueError, match="JSON inválido"):
        AppConfig._load_strict_json(str(d), "contexto_teste")


def test_load_strict_json_empty_file(tmp_path):
    p = tmp_path / "empty.json"
    p.write_text("{}")
    with pytest.raises(ValueError, match="está vazio"):
        AppConfig._load_strict_json(str(p), "Teste")


def test_load_strict_json_invalid_decode(tmp_path):
    p = tmp_path / "corrupt.json"
    p.write_text("isso_nao_e_um_json")
    with pytest.raises(ValueError, match="JSON inválido em"):
        AppConfig._load_strict_json(str(p), "Teste")


def test_get_env_or_raise_exception(monkeypatch):
    monkeypatch.delenv("STARKBANK_PROJECT_ID", raising=False)
    with pytest.raises(KeyError, match="obrigatória no .env"):
        AppConfig._get_env_or_raise("STARKBANK_PROJECT_ID")


def test_validate_keys_missing_key():
    data = {"existing_key": "value"}
    with pytest.raises(KeyError, match="ausente no arquivo"):
        AppConfig._validate_keys(data, ["missing_key"], "test_file.json")


def test_parse_log_level_invalid(monkeypatch):
    monkeypatch.setenv("LOG_LEVEL", "NIVEL_INVENTADO")
    dummy = object.__new__(AppConfig)
    with pytest.raises(ValueError, match="inválido no .env"):
        dummy._parse_log_level()


def test_config_invoice_int_conversion_error(tmp_path, monkeypatch):
    monkeypatch.setenv("STARKBANK_PROJECT_ID", "dummy_id")
    
    key_file = tmp_path / "private_key.pem"
    key_file.write_text("conteudo_da_chave_falsa")
    monkeypatch.setenv("STARKBANK_PRIVATE_KEY", str(key_file))

    t = tmp_path / "transfer.json"
    t.write_text(json.dumps({
        "bank_code": "1", "branch_code": "1", "account_number": "1", 
        "account_type": "1", "name": "1", "tax_id": "1"
    }))
    monkeypatch.setenv("STARKBANK_TRANSFER_CONFIG_PATH", str(t))

    p = tmp_path / "bad_invoice.json"
    p.write_text('{"min_batch": "TEXTO_NO_LUGAR_DE_NUMERO", "max_batch": 12, "interval_hours": 3, "duration_hours": 24}')
    
    monkeypatch.setenv("INVOICE_SCHEDULER_CONFIG_PATH", str(p))

    from app.config import AppConfig
    with pytest.raises(ValueError):
        AppConfig(env_file=".env.test")


class TestInitStarkbank:
    def test_returns_project(self):
        fake = MagicMock(spec=starkbank.Project)
        with patch("app.config.starkbank.Project", return_value=fake):
            assert config.init_starkbank() is fake


    def test_sets_global_user(self):
        fake = MagicMock(spec=starkbank.Project)
        with patch("app.config.starkbank.Project", return_value=fake):
            config.init_starkbank()
        assert starkbank.user is fake


    def test_uses_configured_values(self):
        with patch("app.config.starkbank.Project") as MockProject:
            MockProject.return_value = MagicMock()
            config.init_starkbank()
            MockProject.assert_called_once_with(
                environment=config.STARKBANK_ENVIRONMENT,
                id=config.STARKBANK_PROJECT_ID,
                private_key=config.STARKBANK_PRIVATE_KEY,
            )