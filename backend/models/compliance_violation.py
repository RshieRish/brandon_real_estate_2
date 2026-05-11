"""Audit table for every compliance scanner hit + rewriter outcome.

One row per violation (not per report). A report with 4 violations writes 4
rows so queries like "all FH hits this month" don't need to unpack JSON.
"""

from datetime import datetime

from sqlalchemy import DateTime, ForeignKey, Integer, String, Text, func
from sqlalchemy.orm import Mapped, mapped_column

from database import Base


class ComplianceViolation(Base):
    __tablename__ = "compliance_violations"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), index=True
    )

    lead_id: Mapped[int | None] = mapped_column(
        Integer, ForeignKey("leads.id"), nullable=True, index=True
    )
    source: Mapped[str] = mapped_column(String(50), default="investor_report")
    rule_id: Mapped[str] = mapped_column(String(50))
    category: Mapped[str] = mapped_column(String(50))
    severity: Mapped[str] = mapped_column(String(10))
    field_path: Mapped[str] = mapped_column(String(100))
    matched_text: Mapped[str] = mapped_column(Text)
    original_text: Mapped[str] = mapped_column(Text)
    final_text: Mapped[str] = mapped_column(Text)
    rewrite_attempts: Mapped[int] = mapped_column(Integer, default=0)
    resolution: Mapped[str] = mapped_column(String(50))
