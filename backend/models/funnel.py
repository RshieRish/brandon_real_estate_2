from datetime import datetime

from sqlalchemy import Boolean, DateTime, Integer, String, Text, func
from sqlalchemy.orm import Mapped, mapped_column

from database import Base


class Funnel(Base):
    __tablename__ = "funnels"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    title: Mapped[str] = mapped_column(String(255))
    slug: Mapped[str] = mapped_column(String(255), unique=True)
    audience: Mapped[str] = mapped_column(String(50), default="general")
    event_date: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    description: Mapped[str] = mapped_column(Text, default="")
    cta_text: Mapped[str] = mapped_column(String(255), default="Register Now")
    video_url: Mapped[str | None] = mapped_column(String(500))
    lead_routing: Mapped[str] = mapped_column(String(50), default="dashboard")
    status: Mapped[str] = mapped_column(String(50), default="draft")
    generated_content: Mapped[str] = mapped_column(Text, default="{}")
    registrations: Mapped[int] = mapped_column(Integer, default=0)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now()
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), onupdate=func.now()
    )
