"""CRS parsing, reprojection, and choosing the projected CRS used for measuring.

Latitude/longitude degrees are not a unit of length (a degree of longitude is ~111 km at the
equator and 0 km at the poles), so every geometry is reprojected into a metric projected CRS
before it is measured. The projected CRS is chosen *per feature* from the feature's location,
by a pluggable :class:`ProjectionStrategy`.
"""

from __future__ import annotations

from dataclasses import dataclass
from functools import lru_cache
from typing import Any, Protocol

import numpy as np
import shapely
from pyproj import CRS, Transformer
from pyproj.exceptions import CRSError, ProjError
from shapely.geometry import mapping, shape
from shapely.geometry.base import BaseGeometry

from app.geo.errors import InvalidCRSError

WGS84 = CRS.from_epsg(4326)

# UTM is only defined between these latitudes; polar regions use UPS instead.
UTM_MIN_LAT = -80.0
UTM_MAX_LAT = 84.0


class ProjectionError(Exception):
    """A geometry could not be transformed between coordinate reference systems."""


@lru_cache(maxsize=256)
def parse_crs(value: str) -> CRS:
    """Parse any CRS definition pyproj understands (``EPSG:4326``, WKT, PROJ string, ...)."""
    try:
        return CRS.from_user_input(value)
    except CRSError as exc:
        raise InvalidCRSError(f"Unrecognised CRS {value!r}: {exc}") from exc


@lru_cache(maxsize=256)
def crs_to_string(crs: CRS) -> str:
    """A short identifier for ``crs``: its authority code when one matches, otherwise WKT."""
    authority = crs.to_authority(min_confidence=70)
    if authority:
        return f"{authority[0]}:{authority[1]}"
    return crs.to_wkt()


@lru_cache(maxsize=256)
def get_transformer(source: CRS, target: CRS) -> Transformer:
    # always_xy: coordinates are (x=longitude/easting, y=latitude/northing) whatever axis order
    # the CRS officially declares. Shapefile and KML both store lon/lat in that order, while
    # EPSG:4326 is officially lat/lon - without this flag the axes would be silently swapped.
    return Transformer.from_crs(source, target, always_xy=True)


def _transform_coords(coords: np.ndarray, transformer: Transformer) -> np.ndarray:
    try:
        x, y = transformer.transform(coords[:, 0], coords[:, 1], errcheck=True)
    except ProjError as exc:
        raise ProjectionError(f"Coordinates could not be transformed: {exc}") from exc
    result = np.column_stack((x, y))
    if not np.isfinite(result).all():
        raise ProjectionError("Coordinates could not be transformed: result is not finite.")
    return result


def project_geometry(geometry: BaseGeometry, transformer: Transformer) -> BaseGeometry:
    """Reproject ``geometry`` in 2D. Z values are dropped: measurements are planimetric."""
    return shapely.transform(geometry, lambda coords: _transform_coords(coords, transformer))


def reproject_geojson(geometry: dict[str, Any], source: CRS, target: CRS) -> dict[str, Any]:
    """Reproject a GeoJSON geometry dict (2D output)."""
    return mapping(project_geometry(shape(geometry), get_transformer(source, target)))


def normalize_lon(lon: float) -> float:
    """Wrap a longitude into [-180, 180)."""
    return (lon + 180.0) % 360.0 - 180.0


@dataclass(frozen=True, slots=True)
class LonLatExtent:
    """WGS 84 bounding box of a geometry.

    For a geometry crossing the antimeridian the longitudes are unwrapped so the box still
    describes the narrow extent; ``max_lon`` can then exceed 180.
    """

    min_lon: float
    min_lat: float
    max_lon: float
    max_lat: float

    @property
    def center_lon(self) -> float:
        return normalize_lon((self.min_lon + self.max_lon) / 2)

    @property
    def center_lat(self) -> float:
        return (self.min_lat + self.max_lat) / 2


def lonlat_extent(geometry: BaseGeometry, source_crs: CRS) -> LonLatExtent:
    """Locate ``geometry`` on the globe, validating that the declared CRS is plausible."""
    coords = shapely.get_coordinates(geometry)
    lonlat = _transform_coords(coords, get_transformer(source_crs, WGS84))
    lons, lats = lonlat[:, 0], lonlat[:, 1]

    eps = 1e-9
    if (np.abs(lats) > 90 + eps).any() or (np.abs(lons) > 180 + eps).any():
        # Typical cause: projected coordinates (metres) in a file whose .prj claims lon/lat.
        raise ProjectionError(
            f"Coordinates are outside the valid longitude/latitude range when interpreted in "
            f"{crs_to_string(source_crs)}; the declared CRS probably does not match the data."
        )

    min_lon, max_lon = float(lons.min()), float(lons.max())
    if max_lon - min_lon > 180:
        # Probably crosses the antimeridian: measure the extent the short way round.
        shifted = np.where(lons < 0, lons + 360, lons)
        if shifted.max() - shifted.min() < max_lon - min_lon:
            min_lon, max_lon = float(shifted.min()), float(shifted.max())

    return LonLatExtent(min_lon, float(lats.min()), max_lon, float(lats.max()))


@dataclass(frozen=True, slots=True)
class MeasurementCRS:
    crs: CRS
    label: str  # how the CRS is reported by the API, e.g. "EPSG:32643"


class ProjectionStrategy(Protocol):
    name: str

    def select(self, extent: LonLatExtent) -> MeasurementCRS: ...


@lru_cache(maxsize=512)
def _cached_crs(definition: str) -> CRS:
    return CRS.from_user_input(definition)


class LocalEqualAreaStrategy:
    """Lambert Azimuthal Equal-Area projection centred on the feature.

    Equal-area, so areas are preserved exactly wherever the feature is on the globe. Length
    scale error grows only with distance from the centre (< 0.01 % within ~150 km), so lengths of
    survey-scale features are also accurate. Works everywhere, including the poles.
    """

    name = "laea"

    def select(self, extent: LonLatExtent) -> MeasurementCRS:
        lat = round(extent.center_lat, 4)
        lon = round(extent.center_lon, 4)
        definition = (
            f"+proj=laea +lat_0={lat:g} +lon_0={lon:g} +x_0=0 +y_0=0 +datum=WGS84 +units=m +no_defs"
        )
        return MeasurementCRS(_cached_crs(definition), definition)


def utm_zone(lon: float) -> int:
    return int((normalize_lon(lon) + 180) // 6) % 60 + 1


def utm_central_meridian(zone: int) -> float:
    return zone * 6.0 - 183.0


class UTMStrategy:
    """WGS 84 / UTM zone containing the feature's centre, with a fallback where UTM fits poorly.

    UTM is the conventional choice for survey-scale data and yields a standard EPSG code that
    can be checked in any GIS. Its scale factor is 0.9996 on the central meridian and grows
    away from it, so while the whole feature stays within ``max_offset_deg`` of the central
    meridian the area error is bounded to roughly -0.08 % ... +0.3 %. Features outside UTM's
    latitude band, or extending further from the central meridian (very large features,
    features straddling zones), are measured with ``fallback`` instead.
    """

    name = "utm"

    def __init__(
        self, max_offset_deg: float = 3.5, fallback: ProjectionStrategy | None = None
    ) -> None:
        self.max_offset_deg = max_offset_deg
        self.fallback = fallback or LocalEqualAreaStrategy()

    def select(self, extent: LonLatExtent) -> MeasurementCRS:
        if extent.min_lat < UTM_MIN_LAT or extent.max_lat > UTM_MAX_LAT:
            return self.fallback.select(extent)

        zone = utm_zone(extent.center_lon)
        central_meridian = utm_central_meridian(zone)
        offset = max(
            abs(normalize_lon(extent.min_lon - central_meridian)),
            abs(normalize_lon(extent.max_lon - central_meridian)),
        )
        if offset > self.max_offset_deg:
            return self.fallback.select(extent)

        epsg = (32600 if extent.center_lat >= 0 else 32700) + zone
        return MeasurementCRS(_cached_crs(f"EPSG:{epsg}"), f"EPSG:{epsg}")


STRATEGIES: dict[str, ProjectionStrategy] = {
    UTMStrategy.name: UTMStrategy(),
    LocalEqualAreaStrategy.name: LocalEqualAreaStrategy(),
}


def get_strategy(name: str) -> ProjectionStrategy:
    try:
        return STRATEGIES[name]
    except KeyError:
        raise ValueError(f"Unknown measurement CRS strategy {name!r}") from None
