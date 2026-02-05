from datetime import date, datetime, timezone

from sqlalchemy import (
    JSON,
    Boolean,
    Date,
    DateTime,
    Float,
    ForeignKey,
    Index,
    Integer,
    String,
    Text,
    UniqueConstraint,
    text,
)
from sqlalchemy.orm import Mapped, mapped_column, relationship, validates

from app.db import Base


def utcnow_naive() -> datetime:
    """Return current UTC time as timezone-naive datetime."""
    return datetime.now(timezone.utc).replace(tzinfo=None)


def normalize_utc_naive(value: datetime | None) -> datetime | None:
    """Normalize datetime to timezone-naive UTC for DB storage and math."""
    if value is None or value.tzinfo is None:
        return value
    return value.astimezone(timezone.utc).replace(tzinfo=None)


class Server(Base):
    __tablename__ = "servers"
    __table_args__ = (UniqueConstraint("host", "port", name="uq_server_host_port"),)

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    name: Mapped[str] = mapped_column(String(255), nullable=False)
    host: Mapped[str] = mapped_column(String(255), nullable=False)
    port: Mapped[int] = mapped_column(Integer, nullable=False)
    enabled: Mapped[bool] = mapped_column(Boolean, default=True, nullable=False)
    metadata_json: Mapped[dict | None] = mapped_column("metadata", JSON, nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=utcnow_naive, nullable=False)
    updated_at: Mapped[datetime] = mapped_column(
        DateTime, default=utcnow_naive, onupdate=utcnow_naive, nullable=False
    )

    aliases: Mapped[list["ServerAlias"]] = relationship(back_populates="server", cascade="all, delete-orphan")
    checks: Mapped[list["Check"]] = relationship(back_populates="server", cascade="all, delete-orphan")
    daily_aggregates: Mapped[list["DailyAggregate"]] = relationship(
        back_populates="server",
        cascade="all, delete-orphan",
    )

    @validates("created_at", "updated_at")
    def _normalize_datetimes(self, _key: str, value: datetime) -> datetime:
        normalized = normalize_utc_naive(value)
        if normalized is None:
            raise ValueError("created_at/updated_at cannot be None")
        return normalized


class ServerAlias(Base):
    __tablename__ = "server_aliases"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    server_id: Mapped[int] = mapped_column(ForeignKey("servers.id", ondelete="CASCADE"), nullable=False)
    alias: Mapped[str] = mapped_column(String(255), nullable=False, unique=True)
    source: Mapped[str | None] = mapped_column(String(100), nullable=True)

    server: Mapped[Server] = relationship(back_populates="aliases")


class Check(Base):
    __tablename__ = "checks"
    __table_args__ = (Index("ix_checks_server_checked_at", "server_id", "checked_at"),)

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    server_id: Mapped[int] = mapped_column(ForeignKey("servers.id", ondelete="CASCADE"), nullable=False)
    status: Mapped[str] = mapped_column(String(50), nullable=False)
    latency_ms: Mapped[float | None] = mapped_column(Float, nullable=True)
    error_message: Mapped[str | None] = mapped_column(Text, nullable=True)
    details_json: Mapped[dict | None] = mapped_column("details", JSON, nullable=True)
    score: Mapped[int | None] = mapped_column(Integer, nullable=True)
    confidence: Mapped[float | None] = mapped_column(Float, nullable=True)
    checked_at: Mapped[datetime] = mapped_column(DateTime, default=utcnow_naive, nullable=False)

    server: Mapped[Server] = relationship(back_populates="checks")

    @validates("checked_at")
    def _normalize_checked_at(self, _key: str, value: datetime) -> datetime:
        normalized = normalize_utc_naive(value)
        if normalized is None:
            raise ValueError("checked_at cannot be None")
        return normalized


class Job(Base):
    __tablename__ = "jobs"
    __table_args__ = (
        Index(
            "uq_jobs_running_scan",
            "kind",
            unique=True,
            sqlite_where=text("status = 'running' AND kind = 'scan'"),
        ),
    )

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    kind: Mapped[str] = mapped_column(String(100), nullable=False)
    status: Mapped[str] = mapped_column(String(50), nullable=False, default="pending")
    payload: Mapped[dict | None] = mapped_column(JSON, nullable=True)
    result: Mapped[dict | None] = mapped_column(JSON, nullable=True)
    started_at: Mapped[datetime | None] = mapped_column(DateTime, nullable=True)
    finished_at: Mapped[datetime | None] = mapped_column(DateTime, nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=utcnow_naive, nullable=False)

    @validates("started_at", "finished_at", "created_at")
    def _normalize_datetimes(self, _key: str, value: datetime | None) -> datetime | None:
        return normalize_utc_naive(value)


class DailyAggregate(Base):
    __tablename__ = "daily_aggregates"
    __table_args__ = (UniqueConstraint("server_id", "day", name="uq_daily_server_day"),)

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    server_id: Mapped[int] = mapped_column(ForeignKey("servers.id", ondelete="CASCADE"), nullable=False)
    day: Mapped[date] = mapped_column(Date, nullable=False)
    checks_total: Mapped[int] = mapped_column(Integer, default=0, nullable=False)
    success_total: Mapped[int] = mapped_column(Integer, default=0, nullable=False)
    latency_samples_total: Mapped[int] = mapped_column(Integer, default=0, nullable=False)
    avg_latency_ms: Mapped[float | None] = mapped_column(Float, nullable=True)

    server: Mapped[Server] = relationship(back_populates="daily_aggregates")
