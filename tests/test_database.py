import pytest
from types import SimpleNamespace
from unittest.mock import patch

from sqlalchemy import create_engine
from sqlalchemy.orm import Session

from app.database import (
    Base,
    InvoiceRecord,
    init_db,
    save_invoices,
    mark_invoice_received
)


@pytest.fixture()
def memory_engine():
    engine = create_engine("sqlite:///:memory:")
    Base.metadata.create_all(engine)
    return engine


@pytest.fixture(autouse=True)
def patch_engine(memory_engine):
    import app.database as db_module
    with patch.object(db_module, "engine", memory_engine):
        yield


def _make_invoice(id="inv_001", amount=10_000, name="Ana Silva", tax_id="123.456.789-09"):
    return SimpleNamespace(id=id, amount=amount, name=name, tax_id=tax_id)


def _fetch(engine, invoice_id: str) -> InvoiceRecord:
    with Session(engine) as s:
        record = s.get(InvoiceRecord, invoice_id)
        assert record is not None, f"InvoiceRecord {invoice_id!r} não encontrado no banco"
        return record


class TestInitDb:
    def test_creates_invoices_table(self, memory_engine):
        Base.metadata.drop_all(memory_engine)
        init_db()
        with Session(memory_engine) as s:
            assert s.query(InvoiceRecord).count() == 0


    def test_is_idempotent(self, memory_engine):
        init_db()
        init_db()


class TestSaveInvoices:
    def test_persiste_com_status_enviado(self, memory_engine):
        save_invoices([_make_invoice()])
        record = _fetch(memory_engine, "inv_001")
        assert record is not None
        assert record.status == "enviado"


    def test_campos_persistidos_corretamente(self, memory_engine):
        save_invoices([_make_invoice(id="inv_002", amount=5_000, name="Bruno Costa", tax_id="000.000.000-00")])
        record = _fetch(memory_engine, "inv_002")
        assert record.amount == 5_000
        assert record.name == "Bruno Costa"
        assert record.tax_id == "000.000.000-00"
        assert record.received_at is None
        assert record.transfer_id is None


    def test_created_at_preenchido(self, memory_engine):
        save_invoices([_make_invoice()])
        record = _fetch(memory_engine, "inv_001")
        assert record.created_at is not None
        assert "Z" in record.created_at


    def test_salva_multiplas_invoices(self, memory_engine):
        invoices = [_make_invoice(id=f"inv_{i}") for i in range(5)]
        save_invoices(invoices)
        with Session(memory_engine) as s:
            assert s.query(InvoiceRecord).count() == 5


    def test_idempotente_em_duplicata(self, memory_engine):
        invoice = _make_invoice()
        save_invoices([invoice])
        save_invoices([invoice])
        with Session(memory_engine) as s:
            assert s.query(InvoiceRecord).count() == 1


    def test_lista_vazia_nao_lanca_excecao(self, memory_engine):
        save_invoices([]) 
        with Session(memory_engine) as s:
            assert s.query(InvoiceRecord).count() == 0


class TestMarkInvoiceReceived:
    def test_atualiza_status_para_recebido(self, memory_engine):
        save_invoices([_make_invoice()])
        mark_invoice_received("inv_001")
        record = _fetch(memory_engine, "inv_001")
        assert record.status == "recebido"


    def test_preenche_received_at(self, memory_engine):
        save_invoices([_make_invoice()])
        mark_invoice_received("inv_001")
        record = _fetch(memory_engine, "inv_001")
        assert record.received_at is not None
        assert "Z" in record.received_at


    def test_salva_transfer_id_quando_fornecido(self, memory_engine):
        save_invoices([_make_invoice()])
        mark_invoice_received("inv_001", transfer_id="transf_abc")
        record = _fetch(memory_engine, "inv_001")
        assert record.transfer_id == "transf_abc"


    def test_transfer_id_permanece_nulo_sem_repasse(self, memory_engine):
        save_invoices([_make_invoice()])
        mark_invoice_received("inv_001", transfer_id=None)
        record = _fetch(memory_engine, "inv_001")
        assert record.transfer_id is None


    def test_invoice_inexistente_loga_warning(self, memory_engine, caplog):
        import logging
        with caplog.at_level(logging.WARNING, logger="app.database"):
            mark_invoice_received("id_que_nao_existe")
        assert "não encontrada no banco" in caplog.text


    def test_invoice_inexistente_nao_lanca_excecao(self, memory_engine):
        mark_invoice_received("id_inexistente")
