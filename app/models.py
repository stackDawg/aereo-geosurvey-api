from __future__ import annotations

import uuid
from datetime import UTC, datetime
from enum import StrEnum
from typing import Any

from sqlalchemy import (
    JSON,
    DateTime,
    Enum,
    Float,
    ForeignKey,
    Integer,
    String,
    Text,
    UniqueConstraint,
)
from sqlalchemy.orm import Mapped, mapped_column, relationship
from sqlalchemy.types import TypeDecorator

from app.database import Base
from app.geo.measure import MeasurementStatus
from app.geo.types import FileType


class FileStatus(StrEnum):
    PENDING = "PENDING"
    PROCESSING = "PROCESSING"
    COMPLETED = "COMPLETED"
    FAILED = "FAILED"


def utcnow() -> datetime:
    return datetime.now(UTC)


class UTCDateTime(TypeDecorator):
    """Timezone-aware datetimes, also on SQLite (which stores them without an offset)."""

    impl = DateTime(timezone=True)
    cache_ok = True

    def process_result_value(self, value: datetime | None, dialect: Any) -> datetime | None:
        if value is not None and value.tzinfo is None:
            return value.replace(tzinfo=UTC)
        return value


def _enum(enum_cls: type[StrEnum]) -> Enum:
    # Stored as plain strings so adding a member does not need a database migration.
    return Enum(enum_cls, native_enum=False, length=32, validate_strings=True)


def _new_id() -> str:
    return uuid.uuid4().hex


class ApiClient(Base):
    """A consumer of the API, identified by an API key. Files belong to the client that
    uploaded them."""

    __tablename__ = "api_clients"

    id: Mapped[str] = mapped_column(String(32), primary_key=True, default=_new_id)
    name: Mapped[str] = mapped_column(String(100))
    # SHA-256 of the key; the key itself is shown once at creation and never stored.
    key_hash: Mapped[str] = mapped_column(String(64), unique=True)
    # The key's first characters, so a client can tell its keys apart.
    key_prefix: Mapped[str] = mapped_column(String(16))
    created_at: Mapped[datetime] = mapped_column(UTCDateTime, default=utcnow)


class GeoFile(Base):
    __tablename__ = "geo_files"

    id: Mapped[str] = mapped_column(String(32), primary_key=True, default=_new_id)
    owner_id: Mapped[str] = mapped_column(
        ForeignKey("api_clients.id", ondelete="CASCADE"), index=True
    )
    filename: Mapped[str] = mapped_column(String(255))
    file_type: Mapped[FileType] = mapped_column(_enum(FileType))
    size_bytes: Mapped[int] = mapped_column(Integer)
    storage_path: Mapped[str] = mapped_column(String(1024))
    status: Mapped[FileStatus] = mapped_column(_enum(FileStatus), default=FileStatus.PENDING)

    # CRS supplied by the client for files that do not declare one.
    source_crs: Mapped[str | None] = mapped_column(Text)
    # Effective CRS of the file's features (None when unknown or when layers differ).
    crs: Mapped[str | None] = mapped_column(Text)
    feature_count: Mapped[int | None] = mapped_column(Integer)
    layers: Mapped[list[dict[str, Any]]] = mapped_column(JSON, default=list)
    warnings: Mapped[list[str]] = mapped_column(JSON, default=list)
    error: Mapped[str | None] = mapped_column(Text)

    created_at: Mapped[datetime] = mapped_column(UTCDateTime, default=utcnow, index=True)
    processed_at: Mapped[datetime | None] = mapped_column(UTCDateTime)

    features: Mapped[list[Feature]] = relationship(
        back_populates="file", cascade="all, delete-orphan", passive_deletes=True
    )


class Feature(Base):
    __tablename__ = "features"
    __table_args__ = (UniqueConstraint("file_id", "feature_index"),)

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    file_id: Mapped[str] = mapped_column(ForeignKey("geo_files.id", ondelete="CASCADE"))
    feature_index: Mapped[int] = mapped_column(Integer)  # 0-based position in the file

    # Text rather than VARCHAR(n): both come from user files, and PostgreSQL enforces lengths.
    layer: Mapped[str] = mapped_column(Text)
    feature_id: Mapped[str | None] = mapped_column(Text)  # ID from the source file
    geometry_type: Mapped[str | None] = mapped_column(String(64))
    crs: Mapped[str | None] = mapped_column(Text)
    geometry: Mapped[dict[str, Any] | None] = mapped_column(JSON)  # GeoJSON, in `crs`
    properties: Mapped[dict[str, Any]] = mapped_column(JSON, default=dict)

    measurement_status: Mapped[MeasurementStatus] = mapped_column(_enum(MeasurementStatus))
    area_m2: Mapped[float | None] = mapped_column(Float)
    perimeter_m: Mapped[float | None] = mapped_column(Float)
    length_m: Mapped[float | None] = mapped_column(Float)
    measurement_crs: Mapped[str | None] = mapped_column(Text)
    measurement_message: Mapped[str | None] = mapped_column(Text)

    file: Mapped[GeoFile] = relationship(back_populates="features")
