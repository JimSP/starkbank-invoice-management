import logging
from contextlib import contextmanager
from datetime import datetime, timezone

from app.config import config

from sqlalchemy import create_engine, func
from sqlalchemy.orm import DeclarativeBase, Mapped, mapped_column, Session

logger = logging.getLogger(__name__)

engine = create_engine(
    config.DATABASE_URL,
    connect_args={"check_same_thread": False},  # necessário para SQLite + Flask
    echo=False,
)


class Base(DeclarativeBase):
    pass


class InvoiceRecord(Base):
    __tablename__ = "invoices"

    id: Mapped[str] = mapped_column(primary_key=True)
    amount: Mapped[int]
    name: Mapped[str]
    tax_id: Mapped[str]
    status: Mapped[str] = mapped_column(default="enviado")
    created_at: Mapped[str]
    received_at: Mapped[str | None] = mapped_column(nullable=True, default=None)
    transfer_id: Mapped[str | None] = mapped_column(nullable=True, default=None)

    def __repr__(self) -> str:  # pragma: no cover
        return f"<InvoiceRecord id={self.id} status={self.status} amount={self.amount}>"


def init_db() -> None:
    Base.metadata.create_all(engine)
    logger.info("Banco de dados inicializado em '%s'.", config.DATABASE_URL)


@contextmanager
def get_session():
    with Session(engine) as session:
        try:
            yield session
            session.commit()
        except Exception:
            session.rollback()
            raise


def save_invoices(invoices: list) -> None:
    now = datetime.now(timezone.utc).isoformat().replace("+00:00", "Z")
    records = [
        InvoiceRecord(
            id=str(inv.id),
            amount=int(inv.amount),
            name=getattr(inv, "name", ""),
            tax_id=getattr(inv, "tax_id", ""),
            status="enviado",
            created_at=now,
        )
        for inv in invoices
    ]

    with get_session() as session:
        for record in records:
            existing = session.get(InvoiceRecord, record.id)
            if existing is None:
                session.add(record)

    logger.info("Salvas %d invoice(s) com status='enviado'.", len(records))


def mark_invoice_received(invoice_id: str, transfer_id: str | None = None) -> None:
    now = datetime.now(timezone.utc).isoformat().replace("+00:00", "Z")

    with get_session() as session:
        record = session.get(InvoiceRecord, str(invoice_id))
        if record is None:
            logger.warning(
                "mark_invoice_received: invoice '%s' não encontrada no banco.",
                invoice_id,
            )
            return

        record.status = "recebido"
        record.received_at = now
        if transfer_id:
            record.transfer_id = str(transfer_id)

    logger.info(
        "Invoice '%s' marcada como 'recebido' (transfer_id=%s).",
        invoice_id,
        transfer_id,
    )


def get_invoice_stats() -> dict:
    with get_session() as session:
        total_enviado = session.query(func.count(InvoiceRecord.id)).filter(
            InvoiceRecord.status == "enviado"
        ).scalar() or 0

        total_recebido = session.query(func.count(InvoiceRecord.id)).filter(
            InvoiceRecord.status == "recebido"
        ).scalar() or 0

        volume_cents = session.query(func.sum(InvoiceRecord.amount)).filter(
            InvoiceRecord.status == "recebido"
        ).scalar() or 0

    return {
        "total_enviado": total_enviado,
        "total_recebido": total_recebido,
        "volume_cents": volume_cents,
    }