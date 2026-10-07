"""Area / length measurement of a single geometry."""

from __future__ import annotations

from collections.abc import Iterator
from dataclasses import dataclass
from enum import StrEnum

import shapely
from pyproj import CRS
from shapely.geometry import GeometryCollection, MultiPolygon, Polygon
from shapely.geometry.base import BaseGeometry, BaseMultipartGeometry

from app.geo.crs import (
    ProjectionError,
    ProjectionStrategy,
    get_transformer,
    lonlat_extent,
    project_geometry,
)

# Measurements are reported to the millimetre / square millimetre; source data is never more
# precise than that.
DECIMALS = 3

_AREAL = frozenset({"Polygon"})
_LINEAR = frozenset({"LineString", "LinearRing"})
_PUNTAL = frozenset({"Point"})


class MeasurementStatus(StrEnum):
    MEASURED = "MEASURED"
    NOT_APPLICABLE = "NOT_APPLICABLE"  # points: nothing to measure
    UNSUPPORTED = "UNSUPPORTED"  # a geometry type we cannot measure
    NO_GEOMETRY = "NO_GEOMETRY"  # null or empty geometry
    FAILED = "FAILED"  # measurable, but measuring failed (unknown CRS, bad coordinates, ...)


@dataclass(frozen=True, slots=True)
class Measurement:
    status: MeasurementStatus
    area_m2: float | None = None
    perimeter_m: float | None = None
    length_m: float | None = None
    measurement_crs: str | None = None
    message: str | None = None


def _simple_parts(geometry: BaseGeometry) -> Iterator[BaseGeometry]:
    """Yield the single-part components of a (possibly nested) multi-part geometry."""
    if isinstance(geometry, BaseMultipartGeometry):
        for part in geometry.geoms:
            yield from _simple_parts(part)
    elif not geometry.is_empty:
        yield geometry


def _polygonal(geometry: BaseGeometry) -> MultiPolygon:
    return MultiPolygon([p for p in _simple_parts(geometry) if isinstance(p, Polygon)])


def measure_geometry(
    geometry: BaseGeometry | None, source_crs: CRS | None, strategy: ProjectionStrategy
) -> Measurement:
    """Measure ``geometry`` (given in ``source_crs``) in a projected CRS chosen by ``strategy``.

    Polygons get area and perimeter, lines get length, points get nothing. Multi-part geometries
    and collections are measured as the sum of their parts. Never raises for bad data: problems
    are reported through the returned status and message.
    """
    if geometry is None or geometry.is_empty:
        return Measurement(MeasurementStatus.NO_GEOMETRY, message="Feature has no geometry.")

    parts = list(_simple_parts(geometry))
    unsupported = sorted({p.geom_type for p in parts} - _AREAL - _LINEAR - _PUNTAL)
    if unsupported:
        return Measurement(
            MeasurementStatus.UNSUPPORTED,
            message=f"Measurement is not supported for {', '.join(unsupported)} geometries.",
        )

    measurable = [p for p in parts if p.geom_type not in _PUNTAL]
    if not measurable:
        return Measurement(
            MeasurementStatus.NOT_APPLICABLE,
            message=f"{geometry.geom_type} geometries have no area or length.",
        )

    if source_crs is None:
        return Measurement(
            MeasurementStatus.FAILED,
            message=(
                "The source CRS is unknown, so the geometry cannot be projected for measurement. "
                "Re-upload the file with the `source_crs` form field."
            ),
        )

    to_measure = GeometryCollection(measurable)
    try:
        target = strategy.select(lonlat_extent(to_measure, source_crs))
        projected = project_geometry(to_measure, get_transformer(source_crs, target.crs))
    except ProjectionError as exc:
        return Measurement(MeasurementStatus.FAILED, message=str(exc))

    notes: list[str] = []
    area = perimeter = length = None

    polygons = _polygonal(projected)
    if not polygons.is_empty:
        if not polygons.is_valid:
            # e.g. "Self-intersection[x y]"; the location is in projected coordinates, drop it.
            reason = shapely.is_valid_reason(polygons).split("[")[0]
            polygons = _polygonal(shapely.make_valid(polygons))
            notes.append(f"Invalid polygon geometry ({reason}) was repaired before measuring.")
        area = round(polygons.area, DECIMALS)
        perimeter = round(polygons.length, DECIMALS)

    lines = [p for p in projected.geoms if p.geom_type in _LINEAR]
    if lines:
        length = round(sum(line.length for line in lines), DECIMALS)

    return Measurement(
        MeasurementStatus.MEASURED,
        area_m2=area,
        perimeter_m=perimeter,
        length_m=length,
        measurement_crs=target.label,
        message=" ".join(notes) or None,
    )
