from __future__ import annotations

from dataclasses import dataclass, field
from enum import StrEnum
from pathlib import PurePath
from typing import Any

from pyproj import CRS
from shapely.geometry.base import BaseGeometry


class FileType(StrEnum):
    SHAPEFILE = "SHAPEFILE"
    KML = "KML"
    KMZ = "KMZ"

    @classmethod
    def from_filename(cls, filename: str) -> FileType | None:
        return _EXTENSIONS.get(PurePath(filename).suffix.lower())


_EXTENSIONS = {".zip": FileType.SHAPEFILE, ".kml": FileType.KML, ".kmz": FileType.KMZ}
SUPPORTED_EXTENSIONS = tuple(_EXTENSIONS)


@dataclass(frozen=True, slots=True)
class SourceFeature:
    """A feature as read from the source file, before measurement."""

    layer: str
    feature_id: str | None
    geometry: BaseGeometry | None
    # Set even when ``geometry`` is None if the reader recognised a type it cannot represent
    # (e.g. a KML <Model>), so the API can report what the feature was.
    geometry_type: str | None
    properties: dict[str, Any] = field(default_factory=dict)
    crs: CRS | None = None
    # Why the geometry could not be represented, when its type is not supported.
    unsupported_reason: str | None = None
    # Any other problem with this feature that did not stop the rest of the file from being
    # read: invalid geometry (``geometry`` is then None) or parts that were skipped.
    issue: str | None = None
