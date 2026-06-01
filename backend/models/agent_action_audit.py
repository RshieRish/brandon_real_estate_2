from datetime import datetime

from sqlalchemy import Boolean, DateTime, Integer, String, Text, func
from sqlalchemy.orm import Mapped, mapped_column

from database import Base


class AgentActionAudit(Base):
    __tablename__ = "agent_action_audits"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), index=True
    )
    actor: Mapped[str] = mapped_column(String(80), default="hermes")
    action_id: Mapped[str] = mapped_column(String(120), index=True)
    method: Mapped[str] = mapped_column(String(12))
    path: Mapped[str] = mapped_column(String(255))
    status_code: Mapped[int] = mapped_column(Integer)
    allowed: Mapped[bool] = mapped_column(Boolean, default=True)
    request_meta_json: Mapped[str] = mapped_column("request_meta", Text, default="{}")
    response_meta_json: Mapped[str] = mapped_column("response_meta", Text, default="{}")
