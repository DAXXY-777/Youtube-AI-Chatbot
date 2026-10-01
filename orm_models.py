"""The few SQLAlchemy tables needed by the local livestream bot."""

from __future__ import annotations

from datetime import UTC, datetime

from sqlalchemy import Boolean, DateTime, ForeignKey, Integer, String, Text
from sqlalchemy.orm import Mapped, mapped_column

from database import Base


def utc_now() -> datetime:
    return datetime.now(UTC)


class RuntimeConfiguration(Base):
    __tablename__ = "runtime_configurations"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, default=1)
    active_mode: Mapped[str] = mapped_column(String(10), nullable=False, default="local")
    local_preset_label: Mapped[str] = mapped_column(
        String(100), nullable=False, default="Qwen 3.5"
    )
    cloud_base_url: Mapped[str | None] = mapped_column(Text, nullable=True)
    cloud_model_id: Mapped[str | None] = mapped_column(String(255), nullable=True)
    cloud_api_key_configured: Mapped[bool] = mapped_column(
        Boolean, nullable=False, default=False
    )
    active_stream_id: Mapped[int | None] = mapped_column(
        ForeignKey("stream_contexts.id"), nullable=True
    )
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, default=utc_now
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, default=utc_now, onupdate=utc_now
    )


class StreamContext(Base):
    __tablename__ = "stream_contexts"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    kind: Mapped[str] = mapped_column(String(20), nullable=False)
    label: Mapped[str] = mapped_column(String(255), nullable=False)
    youtube_url: Mapped[str | None] = mapped_column(Text, nullable=True, unique=True)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, default=utc_now
    )


class Viewer(Base):
    __tablename__ = "viewers"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    identity_key: Mapped[str] = mapped_column(String(512), nullable=False, unique=True)
    provider: Mapped[str | None] = mapped_column(String(100), nullable=True)
    provider_id: Mapped[str | None] = mapped_column(String(255), nullable=True)
    username: Mapped[str | None] = mapped_column(String(255), nullable=True)
    display_name: Mapped[str | None] = mapped_column(String(255), nullable=True)
    user_level: Mapped[str | None] = mapped_column(String(100), nullable=True)
    first_seen_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, default=utc_now
    )
    last_seen_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, default=utc_now
    )


class NightbotRequest(Base):
    __tablename__ = "nightbot_requests"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    viewer_id: Mapped[int] = mapped_column(ForeignKey("viewers.id"), nullable=False)
    stream_context_id: Mapped[int] = mapped_column(
        ForeignKey("stream_contexts.id"), nullable=False
    )
    mode: Mapped[str] = mapped_column(String(10), nullable=False)
    prompt: Mapped[str] = mapped_column(String(1500), nullable=False)
    response: Mapped[str] = mapped_column(String(400), nullable=False)
    received_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, default=utc_now
    )
