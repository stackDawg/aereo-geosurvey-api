"""Zipped Shapefile reader, built on GDAL (via pyogrio).

GDAL is the reference Shapefile implementation: it applies the .cpg / DBF code page, assembles
polygon rings and holes, and reads the .prj. This module adds the archive handling around it.
"""

from __future__ import annotations

import shutil
import tempfile
import zipfile
from collections.abc import Iterator
from dataclasses import dataclass
from pathlib import Path

import pyogrio
import shapely
from pyogrio.errors import DataLayerError, DataSourceError
from pyogrio.raw import read
from pyproj import CRS

from app.geo.crs import parse_crs
from app.geo.errors import InvalidCRSError, InvalidGeoFileError
from app.geo.readers.base import (
    ArchiveLimits,
    FeatureReader,
    archive_members,
    json_safe,
    member_path,
    open_zip,
)
from app.geo.types import SourceFeature

REQUIRED_PARTS = (".shp", ".shx", ".dbf")
OPTIONAL_PARTS = (".prj", ".cpg")
BATCH_SIZE = 1000


@dataclass(frozen=True, slots=True)
class _ShapefileEntry:
    layer: str
    parts: dict[str, zipfile.ZipInfo]  # extension -> archive member


def _find_shapefiles(archive: zipfile.ZipFile, limits: ArchiveLimits) -> list[_ShapefileEntry]:
    """Group archive members into shapefiles, matching sidecar files by folder and name."""
    groups: dict[tuple[str, str], dict[str, zipfile.ZipInfo]] = {}
    for info in archive_members(archive, limits):
        path = member_path(info)
        ext = path.suffix.lower()
        if ext in REQUIRED_PARTS or ext in OPTIONAL_PARTS:
            key = (str(path.parent).lower(), path.stem.lower())
            groups.setdefault(key, {})[ext] = info

    entries: list[tuple[str, dict[str, zipfile.ZipInfo]]] = []
    problems: list[str] = []
    for parts in groups.values():
        if ".shp" not in parts:
            continue  # orphaned sidecar files are harmless
        shp = member_path(parts[".shp"])
        missing = [ext for ext in REQUIRED_PARTS if ext not in parts]
        if missing:
            problems.append(f"'{shp}' is missing {', '.join(missing)}")
        else:
            entries.append((str(shp.with_suffix("")), parts))

    if problems:
        raise InvalidGeoFileError("Incomplete shapefile in archive: " + "; ".join(problems) + ".")
    if not entries:
        raise InvalidGeoFileError(
            "The archive does not contain a shapefile (a .shp with matching .shx and .dbf)."
        )

    # Name layers after the file; fall back to the archive path when two share a name.
    stems = [member_path(parts[".shp"]).stem for _, parts in entries]
    return sorted(
        (
            _ShapefileEntry(stem if stems.count(stem) == 1 else full_name, parts)
            for stem, (full_name, parts) in zip(stems, entries, strict=True)
        ),
        key=lambda entry: entry.layer,
    )


class ShapefileReader(FeatureReader):
    """Reads every shapefile in a .zip archive; each shapefile becomes a layer."""

    def __init__(self, path: Path, limits: ArchiveLimits | None = None) -> None:
        super().__init__(path, limits)
        self._workdir: Path | None = None

    @classmethod
    def validate(cls, path: Path, limits: ArchiveLimits) -> None:
        with open_zip(path) as archive:
            _find_shapefiles(archive, limits)

    def features(self) -> Iterator[SourceFeature]:
        self._workdir = Path(tempfile.mkdtemp(prefix="shapefile-"))
        with open_zip(self.path) as archive:
            entries = _find_shapefiles(archive, self.limits)
            extracted = [
                (entry.layer, self._extract(archive, entry, self._workdir / str(i)))
                for i, entry in enumerate(entries)
            ]
        for layer, shp_path in extracted:
            yield from self._read_layer(layer, shp_path)

    def close(self) -> None:
        if self._workdir is not None:
            shutil.rmtree(self._workdir, ignore_errors=True)
            self._workdir = None

    @staticmethod
    def _extract(archive: zipfile.ZipFile, entry: _ShapefileEntry, directory: Path) -> Path:
        # Members are written under names we generate, never the names stored in the archive,
        # so a malicious archive cannot write outside the working directory ("zip slip").
        directory.mkdir(parents=True)
        for ext, info in entry.parts.items():
            with archive.open(info) as src, (directory / f"layer{ext}").open("wb") as dst:
                shutil.copyfileobj(src, dst)
        return directory / "layer.shp"

    def _read_layer(self, layer: str, shp_path: Path) -> Iterator[SourceFeature]:
        try:
            info = pyogrio.read_info(shp_path)
        except (DataSourceError, DataLayerError) as exc:
            raise InvalidGeoFileError(f"Could not read shapefile '{layer}': {exc}") from exc

        crs = self._layer_crs(layer, info["crs"])
        self.layers[layer] = crs
        layer_geometry_type = info["geometry_type"]

        for offset in range(0, info["features"], BATCH_SIZE):
            try:
                meta, fids, geometries, field_data = read(
                    shp_path, skip_features=offset, max_features=BATCH_SIZE, return_fids=True
                )
            except (DataSourceError, DataLayerError) as exc:
                raise InvalidGeoFileError(f"Could not read shapefile '{layer}': {exc}") from exc

            names = list(meta["fields"])
            columns = [column.tolist() for column in field_data]
            for row, (fid, wkb) in enumerate(zip(fids, geometries, strict=True)):
                properties = {
                    name: json_safe(col[row]) for name, col in zip(names, columns, strict=True)
                }
                yield _to_feature(layer, str(fid), wkb, properties, crs, layer_geometry_type)

    def _layer_crs(self, layer: str, definition: str | None) -> CRS | None:
        if not definition:
            self.warn(f"Layer '{layer}' has no .prj file, so its CRS is not declared.")
            return None
        try:
            return parse_crs(definition)
        except InvalidCRSError:
            self.warn(f"Layer '{layer}' has a .prj file that could not be interpreted.")
            return None


def _to_feature(
    layer: str,
    feature_id: str,
    wkb: bytes | None,
    properties: dict,
    crs: CRS | None,
    layer_geometry_type: str,
) -> SourceFeature:
    if wkb is None:  # a shapefile "null shape" record
        return SourceFeature(layer, feature_id, None, None, properties, crs)
    try:
        geometry = shapely.from_wkb(wkb)
    except shapely.errors.ShapelyError as exc:
        # GDAL has already parsed the record, so this is a type Shapely cannot represent
        # (e.g. a MultiPatch read as a TIN) rather than corrupt data.
        return SourceFeature(
            layer,
            feature_id,
            None,
            layer_geometry_type,
            properties,
            crs,
            unsupported_reason=f"Geometry type is not supported: {exc}",
        )
    return SourceFeature(layer, feature_id, geometry, geometry.geom_type, properties, crs)
