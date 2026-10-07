from __future__ import annotations

import math
import zipfile
from abc import ABC, abstractmethod
from collections.abc import Iterator
from dataclasses import dataclass
from datetime import date, datetime, time
from pathlib import Path, PurePosixPath
from typing import Any, Self

import numpy as np
from pyproj import CRS

from app.geo.errors import InvalidGeoFileError
from app.geo.types import SourceFeature


@dataclass(frozen=True, slots=True)
class ArchiveLimits:
    """Limits applied to zip-based uploads, to guard against zip bombs."""

    max_members: int = 1000
    max_total_bytes: int = 500 * 1024 * 1024


class FeatureReader(ABC):
    """Streams :class:`SourceFeature` objects out of one uploaded file.

    Readers are context managers so they can hold temporary resources (such as an extracted
    archive) for the duration of a read. While iterating they record per-layer CRS information
    in ``layers`` and non-fatal problems in ``warnings``.
    """

    def __init__(self, path: Path, limits: ArchiveLimits | None = None) -> None:
        self.path = path
        self.limits = limits or ArchiveLimits()
        self.layers: dict[str, CRS | None] = {}
        self.warnings: list[str] = []

    @classmethod
    @abstractmethod
    def validate(cls, path: Path, limits: ArchiveLimits) -> None:
        """Cheap structural check, run at upload time so broken files get an immediate 4xx.

        Raises :class:`InvalidGeoFileError`.
        """

    @abstractmethod
    def features(self) -> Iterator[SourceFeature]:
        """Yield every feature in the file. Raises :class:`InvalidGeoFileError`."""

    def close(self) -> None:  # noqa: B027 - optional hook, most readers hold no resources
        """Release temporary resources."""

    def warn(self, message: str) -> None:
        if message not in self.warnings:
            self.warnings.append(message)

    def __enter__(self) -> Self:
        return self

    def __exit__(self, *exc_info: object) -> None:
        self.close()


def open_zip(path: Path) -> zipfile.ZipFile:
    try:
        return zipfile.ZipFile(path)
    except (zipfile.BadZipFile, OSError) as exc:
        raise InvalidGeoFileError(f"Not a valid zip archive: {exc}") from exc


def _is_junk(member: PurePosixPath) -> bool:
    # macOS Finder adds __MACOSX/ resource forks and ._* / .DS_Store files to zips.
    return member.parts[0] == "__MACOSX" or member.name.startswith(".")


def archive_members(archive: zipfile.ZipFile, limits: ArchiveLimits) -> list[zipfile.ZipInfo]:
    """The archive's real files (no directories or OS junk), after enforcing ``limits``.

    ``ZipInfo.file_size`` can be trusted for this check because ``zipfile`` never decompresses
    more than the declared size of a member.
    """
    members = [
        info for info in archive.infolist() if not info.is_dir() and not _is_junk(member_path(info))
    ]
    if len(members) > limits.max_members:
        raise InvalidGeoFileError(
            f"Archive contains {len(members)} files; the limit is {limits.max_members}."
        )
    total = sum(info.file_size for info in members)
    if total > limits.max_total_bytes:
        raise InvalidGeoFileError(
            f"Archive expands to {total} bytes; the limit is {limits.max_total_bytes}."
        )
    return members


def member_path(info: zipfile.ZipInfo) -> PurePosixPath:
    # Some Windows tools write backslash separators despite the zip specification.
    return PurePosixPath(info.filename.replace("\\", "/"))


def json_safe(value: Any) -> Any:
    """Convert an attribute value read from a file into something JSON can represent."""
    if isinstance(value, np.generic):
        value = value.item()
    if value is None or isinstance(value, bool | int | str):
        return value
    if isinstance(value, float):
        return value if math.isfinite(value) else None
    if isinstance(value, datetime | date | time):
        return value.isoformat()
    if isinstance(value, bytes):
        return value.hex()
    if isinstance(value, list | tuple):
        return [json_safe(v) for v in value]
    if isinstance(value, dict):
        return {str(k): json_safe(v) for k, v in value.items()}
    return str(value)
