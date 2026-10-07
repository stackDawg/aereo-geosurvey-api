"""KML / KMZ reader.

KML is parsed directly rather than through GDAL because GDAL's KML and LIBKML drivers drop
untyped ``<ExtendedData><Data name="...">`` attributes - which is exactly how Google Earth and
Google My Maps store attributes. Parsing uses defusedxml, so entity-expansion ("billion laughs")
and external-entity (XXE) payloads are rejected.
"""

from __future__ import annotations

import xml.etree.ElementTree as ET
import zipfile
from collections.abc import Iterator
from pathlib import Path
from typing import IO, Any

import defusedxml.ElementTree as SafeET
from defusedxml import DefusedXmlException
from pyproj import CRS
from shapely.errors import ShapelyError
from shapely.geometry import (
    GeometryCollection,
    LineString,
    MultiLineString,
    MultiPoint,
    MultiPolygon,
    Point,
    Polygon,
)
from shapely.geometry.base import BaseGeometry, BaseMultipartGeometry

from app.geo.errors import InvalidGeoFileError
from app.geo.readers.base import (
    ArchiveLimits,
    FeatureReader,
    archive_members,
    member_path,
    open_zip,
)
from app.geo.types import SourceFeature

# The KML specification fixes the coordinate reference system to WGS 84 longitude/latitude.
KML_CRS = CRS.from_epsg(4326)

_CONTAINERS = frozenset({"Document", "Folder"})
_GEOMETRIES = frozenset(
    {
        "Point",
        "LineString",
        "LinearRing",
        "Polygon",
        "MultiGeometry",
        "Track",
        "MultiTrack",
        "Model",
    }
)
_INT_TYPES = frozenset({"int", "uint", "short", "ushort"})
_FLOAT_TYPES = frozenset({"float", "double"})


class UnsupportedGeometryError(Exception):
    def __init__(self, geometry_type: str, reason: str) -> None:
        super().__init__(reason)
        self.geometry_type = geometry_type


def _local(tag: Any) -> str:
    """Element name without its namespace, so KML 2.0 / 2.1 / 2.2 and gx: tags all match."""
    if not isinstance(tag, str):
        return ""
    return tag.rpartition("}")[2]


def _children(element: ET.Element, name: str) -> Iterator[ET.Element]:
    return (child for child in element if _local(child.tag) == name)


def _child_text(element: ET.Element, name: str) -> str | None:
    child = next(_children(element, name), None)
    if child is None or child.text is None:
        return None
    return child.text.strip() or None


def _parse_root(stream: IO[bytes]) -> ET.Element:
    try:
        root = SafeET.parse(stream).getroot()
    except DefusedXmlException as exc:
        raise InvalidGeoFileError(
            f"KML contains forbidden XML constructs ({type(exc).__name__})."
        ) from exc
    except ET.ParseError as exc:
        raise InvalidGeoFileError(f"KML is not well-formed XML: {exc}") from exc
    _check_root_tag(root)
    return root


def _check_root(stream: IO[bytes]) -> None:
    """Check the document element without parsing the whole file."""
    try:
        for _event, element in SafeET.iterparse(stream, events=("start",)):
            _check_root_tag(element)
            return
    except DefusedXmlException as exc:
        raise InvalidGeoFileError(
            f"KML contains forbidden XML constructs ({type(exc).__name__})."
        ) from exc
    except ET.ParseError as exc:
        raise InvalidGeoFileError(f"KML is not well-formed XML: {exc}") from exc
    raise InvalidGeoFileError("KML document is empty.")


def _check_root_tag(element: ET.Element) -> None:
    if _local(element.tag) != "kml":
        raise InvalidGeoFileError(
            f"Not a KML document: root element is <{_local(element.tag)}>, expected <kml>."
        )


class KMLReader(FeatureReader):
    """Reads Placemarks from a KML document. Document/Folder nesting becomes the layer name."""

    @classmethod
    def validate(cls, path: Path, limits: ArchiveLimits) -> None:
        with path.open("rb") as stream:
            _check_root(stream)

    def features(self) -> Iterator[SourceFeature]:
        root = self._load_root()
        self._schemas = _read_schemas(root)
        yield from self._walk(root, [])

    def _load_root(self) -> ET.Element:
        with self.path.open("rb") as stream:
            return _parse_root(stream)

    def _walk(self, element: ET.Element, path: list[str]) -> Iterator[SourceFeature]:
        for child in element:
            tag = _local(child.tag)
            if tag in _CONTAINERS:
                yield from self._walk(child, [*path, _child_text(child, "name") or tag])
            elif tag == "Placemark":
                layer = "/".join(path) or "root"
                self.layers.setdefault(layer, KML_CRS)
                yield self._placemark(child, layer)
            elif tag == "NetworkLink":
                self.warn("NetworkLink elements reference external content and were not followed.")

    def _placemark(self, element: ET.Element, layer: str) -> SourceFeature:
        feature_id = element.get("id")
        properties: dict[str, Any] = {}
        for key in ("name", "description"):
            value = _child_text(element, key)
            if value is not None:
                properties[key] = value
        for key, value in self._extended_data(element):
            properties.setdefault(key, value)

        geometry_element = next((c for c in element if _local(c.tag) in _GEOMETRIES), None)
        if geometry_element is None:
            return SourceFeature(layer, feature_id, None, None, properties, KML_CRS)

        skipped: list[str] = []
        try:
            geometry = _parse_geometry(geometry_element, skipped)
        except UnsupportedGeometryError as exc:
            return SourceFeature(
                layer,
                feature_id,
                None,
                exc.geometry_type,
                properties,
                KML_CRS,
                unsupported_reason=str(exc),
            )
        except (ValueError, ShapelyError) as exc:
            tag = _local(geometry_element.tag)
            return SourceFeature(
                layer, feature_id, None, tag, properties, KML_CRS, issue=f"Invalid {tag}: {exc}"
            )

        issue = None
        if skipped:
            issue = f"Ignored unsupported part(s) of MultiGeometry: {', '.join(skipped)}."
        return SourceFeature(
            layer, feature_id, geometry, geometry.geom_type, properties, KML_CRS, issue=issue
        )

    def _extended_data(self, placemark: ET.Element) -> Iterator[tuple[str, Any]]:
        for extended in _children(placemark, "ExtendedData"):
            for child in extended:
                tag = _local(child.tag)
                if tag == "Data" and child.get("name"):
                    yield child.get("name"), _child_text(child, "value")
                elif tag == "SchemaData":
                    schema = self._schemas.get(child.get("schemaUrl", "").rpartition("#")[2], {})
                    for simple in _children(child, "SimpleData"):
                        name = simple.get("name")
                        if name:
                            yield name, _coerce(simple.text, schema.get(name))


class KMZReader(KMLReader):
    """A KMZ is a zip holding a KML document (conventionally doc.kml) plus its resources."""

    @classmethod
    def validate(cls, path: Path, limits: ArchiveLimits) -> None:
        with open_zip(path) as archive, archive.open(_main_document(archive, limits)) as stream:
            _check_root(stream)

    def _load_root(self) -> ET.Element:
        with open_zip(self.path) as archive:
            documents = [i for i in archive_members(archive, self.limits) if _is_kml(i)]
            if len(documents) > 1:
                self.warn(
                    f"KMZ contains {len(documents)} KML documents; only the main one is read."
                )
            with archive.open(_main_document(archive, self.limits)) as stream:
                return _parse_root(stream)


def _is_kml(info: zipfile.ZipInfo) -> bool:
    return member_path(info).suffix.lower() == ".kml"


def _main_document(archive: zipfile.ZipFile, limits: ArchiveLimits) -> zipfile.ZipInfo:
    documents = [info for info in archive_members(archive, limits) if _is_kml(info)]
    if not documents:
        raise InvalidGeoFileError("The KMZ archive does not contain a .kml document.")
    # Google Earth reads doc.kml if present, otherwise the first top-level .kml.
    for info in documents:
        if member_path(info).as_posix().lower() == "doc.kml":
            return info
    top_level = [info for info in documents if len(member_path(info).parts) == 1]
    return (top_level or documents)[0]


def _read_schemas(root: ET.Element) -> dict[str, dict[str, str]]:
    """Map Schema id/name -> {field name: declared type}, used to type <SimpleData> values."""
    schemas: dict[str, dict[str, str]] = {}
    for schema in root.iter():
        if _local(schema.tag) != "Schema":
            continue
        fields = {
            field.get("name"): (field.get("type") or "string").lower()
            for field in _children(schema, "SimpleField")
            if field.get("name")
        }
        for key in (schema.get("id"), schema.get("name")):
            if key:
                schemas[key] = fields
    return schemas


def _coerce(text: str | None, declared_type: str | None) -> Any:
    if text is None:
        return None
    value = text.strip()
    try:
        if declared_type in _INT_TYPES:
            return int(value)
        if declared_type in _FLOAT_TYPES:
            return float(value)
    except ValueError:
        return value
    if declared_type == "bool":
        return value.lower() in ("1", "true")
    return value


def _parse_coordinates(text: str | None) -> list[tuple[float, ...]]:
    """Parse a KML ``<coordinates>`` string: whitespace-separated ``lon,lat[,alt]`` tuples."""
    if not text or not text.strip():
        raise ValueError("no coordinates")
    # Hand-edited files often contain "lon, lat" - glue the tuples back together first.
    tokens = ",".join(part.strip() for part in text.strip().split(",")).split()
    positions = []
    for token in tokens:
        values = token.split(",")
        if len(values) not in (2, 3):
            raise ValueError(f"invalid coordinate tuple {token!r}")
        try:
            positions.append(tuple(float(v) for v in values))
        except ValueError:
            raise ValueError(f"invalid coordinate tuple {token!r}") from None
    if any(len(p) != len(positions[0]) for p in positions):
        positions = [p[:2] for p in positions]  # mixed 2D/3D: keep the common dimensions
    return positions


def _coordinates(element: ET.Element) -> list[tuple[float, ...]]:
    return _parse_coordinates(_child_text(element, "coordinates"))


def _ring(element: ET.Element) -> list[tuple[float, ...]]:
    ring = next(_children(element, "LinearRing"), None)
    if ring is None:
        raise ValueError("boundary without a LinearRing")
    return _coordinates(ring)


def _parse_geometry(element: ET.Element, skipped: list[str]) -> BaseGeometry:
    tag = _local(element.tag)
    if tag == "Point":
        return Point(_coordinates(element)[0])
    if tag == "LineString":
        return LineString(_coordinates(element))
    if tag == "LinearRing":
        return LineString(_coordinates(element))  # a bare ring is measured as a closed line
    if tag == "Polygon":
        outer = next(_children(element, "outerBoundaryIs"), None)
        if outer is None:
            raise ValueError("polygon without an outerBoundaryIs")
        holes = [
            _coordinates(ring)
            for inner in _children(element, "innerBoundaryIs")
            for ring in _children(inner, "LinearRing")
        ]
        return Polygon(_ring(outer), holes)
    if tag == "MultiGeometry":
        parts = []
        for child in element:
            if _local(child.tag) in _GEOMETRIES:
                try:
                    parts.append(_parse_geometry(child, skipped))
                except UnsupportedGeometryError as exc:
                    skipped.append(exc.geometry_type)
        return _combine(parts)
    if tag == "Track":  # gx:Track - a time-stamped path
        return _track(element)
    if tag == "MultiTrack":
        return MultiLineString([_track(track) for track in _children(element, "Track")])
    if tag == "Model":
        raise UnsupportedGeometryError("Model", "3D Model geometries cannot be measured.")
    raise UnsupportedGeometryError(tag, f"{tag} geometries are not supported.")


def _track(element: ET.Element) -> LineString:
    positions = []
    for coord in _children(element, "coord"):
        values = (coord.text or "").split()
        if len(values) not in (2, 3):
            raise ValueError(f"invalid gx:coord {coord.text!r}")
        positions.append(tuple(float(v) for v in values))
    return LineString(positions)


def _flatten(geometry: BaseGeometry) -> Iterator[BaseGeometry]:
    if isinstance(geometry, BaseMultipartGeometry):
        for part in geometry.geoms:
            yield from _flatten(part)
    else:
        yield geometry


def _combine(parts: list[BaseGeometry]) -> BaseGeometry:
    """Build the most specific multi-geometry for the parts of a <MultiGeometry>."""
    flat = [p for part in parts for p in _flatten(part)]
    types = {p.geom_type for p in flat}
    if types == {"Point"}:
        return MultiPoint(flat)
    if types == {"LineString"}:
        return MultiLineString(flat)
    if types == {"Polygon"}:
        return MultiPolygon(flat)
    return GeometryCollection(flat)
