from datetime import datetime
from typing import Any

from sqlalchemy import JSON, DateTime, Float, ForeignKey, Index, String, Text
from sqlalchemy.orm import DeclarativeBase, Mapped, mapped_column


class Base(DeclarativeBase):
    pass


class TenderRow(Base):
    __tablename__ = "tenders"
    tender_id: Mapped[str] = mapped_column(String(64), primary_key=True)
    payload: Mapped[dict[str, Any]] = mapped_column(JSON)


class RunRow(Base):
    __tablename__ = "enrichment_runs"
    run_id: Mapped[str] = mapped_column(String(36), primary_key=True)
    tender_id: Mapped[str] = mapped_column(ForeignKey("tenders.tender_id"))
    status: Mapped[str] = mapped_column(String(32))
    confidence: Mapped[float] = mapped_column(Float)
    processed_at: Mapped[datetime] = mapped_column(DateTime(timezone=True))
    payload: Mapped[dict[str, Any]] = mapped_column(JSON)
    __table_args__ = (Index("ix_runs_tender_processed", "tender_id", "processed_at"),)


class CompanyRow(Base):
    """A verified profile belongs to a run, not an automatically merged global company."""

    __tablename__ = "company_profiles"
    run_id: Mapped[str] = mapped_column(ForeignKey("enrichment_runs.run_id"), primary_key=True)
    company_name: Mapped[str | None] = mapped_column(Text)
    phone: Mapped[str | None] = mapped_column(String(100))
    email: Mapped[str | None] = mapped_column(Text)
    website: Mapped[str | None] = mapped_column(Text)
    address: Mapped[str | None] = mapped_column(Text)
    city: Mapped[str | None] = mapped_column(String(100))
    district: Mapped[str | None] = mapped_column(String(100))
    mersis_no: Mapped[str | None] = mapped_column(String(16))
    trade_registry_no: Mapped[str | None] = mapped_column(String(100))
    trade_registry_office: Mapped[str | None] = mapped_column(Text)
    tax_no: Mapped[str | None] = mapped_column(String(10))
    tax_office: Mapped[str | None] = mapped_column(Text)


class SourceRow(Base):
    __tablename__ = "sources"
    source_id: Mapped[str] = mapped_column(String(36), primary_key=True)
    run_id: Mapped[str] = mapped_column(ForeignKey("enrichment_runs.run_id"))
    payload: Mapped[dict[str, Any]] = mapped_column(JSON)


class EvidenceRow(Base):
    __tablename__ = "evidence"
    evidence_id: Mapped[str] = mapped_column(String(36), primary_key=True)
    run_id: Mapped[str] = mapped_column(ForeignKey("enrichment_runs.run_id"))
    source_id: Mapped[str] = mapped_column(ForeignKey("sources.source_id"))
    field: Mapped[str] = mapped_column(String(64))
    value: Mapped[str] = mapped_column(Text)
    excerpt: Mapped[str] = mapped_column(Text)
    locator: Mapped[str] = mapped_column(Text)
