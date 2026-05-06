from datetime import datetime

from sqlalchemy import (
    JSON,
    Boolean,
    DateTime,
    ForeignKey,
    Integer,
    LargeBinary,
    String,
    Text,
    func,
)
from sqlalchemy.orm import Mapped, mapped_column, relationship, backref

from database import Base


class LinkPack(Base):
    __tablename__ = "link_pack"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)

    profile_name: Mapped[str] = mapped_column(String(255), default="")
    profile_bio: Mapped[str] = mapped_column(Text, default="")
    profile_photo_data: Mapped[bytes | None] = mapped_column(LargeBinary)
    profile_photo_mime: Mapped[str | None] = mapped_column(String(100))
    is_verified: Mapped[bool] = mapped_column(Boolean, default=False)

    social_phone: Mapped[str | None] = mapped_column(String(50))
    social_email: Mapped[str | None] = mapped_column(String(255))
    social_instagram: Mapped[str | None] = mapped_column(String(255))
    social_facebook: Mapped[str | None] = mapped_column(String(255))
    social_youtube: Mapped[str | None] = mapped_column(String(255))
    social_website: Mapped[str | None] = mapped_column(String(255))
    social_tiktok: Mapped[str | None] = mapped_column(String(255))
    social_x: Mapped[str | None] = mapped_column(String(255))

    theme: Mapped[dict] = mapped_column(JSON, default=dict)

    background_image_data: Mapped[bytes | None] = mapped_column(LargeBinary)
    background_image_mime: Mapped[str | None] = mapped_column(String(100))

    published_snapshot: Mapped[dict | None] = mapped_column(JSON)
    published_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    has_unpublished_changes: Mapped[bool] = mapped_column(Boolean, default=False)

    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now()
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), onupdate=func.now()
    )


class LinkPackItem(Base):
    __tablename__ = "link_pack_items"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    link_pack_id: Mapped[int] = mapped_column(
        ForeignKey("link_pack.id", ondelete="CASCADE"), default=1
    )
    parent_id: Mapped[int | None] = mapped_column(
        ForeignKey("link_pack_items.id", ondelete="CASCADE")
    )
    position: Mapped[int] = mapped_column(Integer, default=0)

    kind: Mapped[str] = mapped_column(String(20))
    title: Mapped[str] = mapped_column(String(255))
    url: Mapped[str | None] = mapped_column(String(2048))

    thumbnail_data: Mapped[bytes | None] = mapped_column(LargeBinary)
    thumbnail_mime: Mapped[str | None] = mapped_column(String(100))

    gated_file_data: Mapped[bytes | None] = mapped_column(LargeBinary)
    gated_file_mime: Mapped[str | None] = mapped_column(String(100))
    gated_filename: Mapped[str | None] = mapped_column(String(255))
    gate_modal_headline: Mapped[str | None] = mapped_column(String(255))
    gate_modal_subtext: Mapped[str | None] = mapped_column(Text)

    animation: Mapped[str] = mapped_column(String(20), default="none")
    is_active: Mapped[bool] = mapped_column(Boolean, default=True)
    click_count: Mapped[int] = mapped_column(Integer, default=0)

    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now()
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), onupdate=func.now()
    )

    children: Mapped[list["LinkPackItem"]] = relationship(
        "LinkPackItem",
        cascade="all, delete-orphan",
        backref=backref("parent", remote_side="LinkPackItem.id"),
        order_by="LinkPackItem.position",
    )
