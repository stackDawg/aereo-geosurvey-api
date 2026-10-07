"""Measurement tests.

Accuracy is checked against geodesic measurements on the WGS 84 ellipsoid (pyproj.Geod), which
need no projection and serve as ground truth.
"""

import pytest
import shapely
from pyproj import CRS, Geod
from shapely.geometry import (
    GeometryCollection,
    LineString,
    MultiPoint,
    MultiPolygon,
    Point,
    Polygon,
    box,
)

from app.geo.crs import get_strategy, get_transformer, project_geometry
from app.geo.measure import MeasurementStatus, measure_geometry

WGS84 = CRS.from_epsg(4326)
GEOD = Geod(ellps="WGS84")
UTM = get_strategy("utm")
LAEA = get_strategy("laea")

LOCATIONS = {
    "bengaluru": (77.59, 12.97),
    "equator": (10.0, 0.0),
    "new-york": (-74.0, 40.7),
    "sydney": (151.2, -33.9),
    "tromso": (18.9, 69.6),
}


def geodesic_area(geometry) -> float:
    return abs(GEOD.geometry_area_perimeter(geometry)[0])


def relative_error(measured: float, expected: float) -> float:
    return abs(measured - expected) / expected


@pytest.mark.parametrize("location", LOCATIONS)
def test_polygon_area_matches_geodesic_area_with_utm(location):
    lon, lat = LOCATIONS[location]
    plot = box(lon, lat, lon + 0.01, lat + 0.01)  # roughly 1 km x 1 km

    result = measure_geometry(plot, WGS84, UTM)

    assert result.status == MeasurementStatus.MEASURED
    assert result.measurement_crs.startswith("EPSG:32")
    assert relative_error(result.area_m2, geodesic_area(plot)) < 0.003  # UTM: < 0.3 %


@pytest.mark.parametrize("location", LOCATIONS)
def test_polygon_area_matches_geodesic_area_with_laea(location):
    lon, lat = LOCATIONS[location]
    plot = box(lon, lat, lon + 0.01, lat + 0.01)

    result = measure_geometry(plot, WGS84, LAEA)

    assert relative_error(result.area_m2, geodesic_area(plot)) < 1e-5  # equal-area: exact


def test_line_length_matches_geodesic_length():
    line = LineString([(0, 0), (1, 0)])  # one degree along the equator

    result = measure_geometry(line, WGS84, UTM)

    assert result.status == MeasurementStatus.MEASURED
    assert result.area_m2 is None
    assert relative_error(result.length_m, GEOD.geometry_length(line)) < 0.002
    assert result.length_m == pytest.approx(111_319, rel=0.002)


def test_polar_feature_uses_laea_and_is_accurate():
    plot = box(10.0, 85.0, 10.5, 85.05)

    result = measure_geometry(plot, WGS84, UTM)

    assert result.measurement_crs.startswith("+proj=laea")
    assert relative_error(result.area_m2, geodesic_area(plot)) < 1e-4


def test_antimeridian_crossing_polygon():
    # Coordinates jump from +179.99 to -179.99: a narrow strip, not a band around the globe.
    plot = Polygon([(179.99, -17), (-179.99, -17), (-179.99, -16.99), (179.99, -16.99)])

    result = measure_geometry(plot, WGS84, UTM)

    assert relative_error(result.area_m2, geodesic_area(plot)) < 0.003


def test_projected_source_is_measured_in_metres():
    square = box(776_000, 1_434_000, 776_100, 1_434_100)  # 100 m x 100 m in UTM 43N

    result = measure_geometry(square, CRS.from_epsg(32643), UTM)

    assert result.measurement_crs == "EPSG:32643"
    assert result.area_m2 == pytest.approx(10_000, abs=0.001)
    assert result.perimeter_m == pytest.approx(400, abs=0.001)


def test_projected_source_in_us_survey_feet():
    # NY State Plane Long Island is in US survey feet: 1000 ft x 1000 ft = 92 903.4 m2.
    square = box(1_000_000, 200_000, 1_001_000, 201_000)

    result = measure_geometry(square, CRS.from_epsg(2263), UTM)

    assert result.area_m2 == pytest.approx(1_000_000 * (1200 / 3937) ** 2, rel=0.002)


def test_web_mercator_source_is_not_measured_in_its_own_distorted_units():
    plot = box(10.0, 60.0, 10.02, 60.01)
    mercator = CRS.from_epsg(3857)
    plot_mercator = project_geometry(plot, get_transformer(WGS84, mercator))

    result = measure_geometry(plot_mercator, mercator, UTM)

    # Planar Web Mercator area at 60 degrees N is inflated ~4x; the measured area is not.
    assert plot_mercator.area / geodesic_area(plot) == pytest.approx(4, rel=0.01)
    assert relative_error(result.area_m2, geodesic_area(plot)) < 0.003


def test_polygon_holes_are_excluded_from_area():
    # Placed on the UTM central meridian (easting 500 km), where UTM's scale factor is ~1.
    shell = [(500_000, 0), (500_100, 0), (500_100, 100), (500_000, 100)]
    hole = [(500_010, 10), (500_020, 10), (500_020, 20), (500_010, 20)]

    result = measure_geometry(Polygon(shell, [hole]), CRS.from_epsg(32631), UTM)

    assert result.area_m2 == pytest.approx(10_000 - 100, abs=0.01)
    assert result.perimeter_m == pytest.approx(400 + 40, abs=0.01)


def test_multipolygon_area_is_sum_of_parts():
    parts = MultiPolygon([box(500_000, 0, 500_010, 10), box(500_100, 0, 500_120, 10)])

    result = measure_geometry(parts, CRS.from_epsg(32631), UTM)

    assert result.area_m2 == pytest.approx(300, abs=0.001)


def test_z_coordinates_are_ignored():
    flat = box(77.0, 12.0, 77.01, 12.01)
    raised = shapely.force_3d(flat, 900.0)

    assert measure_geometry(raised, WGS84, UTM) == measure_geometry(flat, WGS84, UTM)


def test_mixed_collection_reports_area_and_length():
    collection = GeometryCollection(
        [
            box(500_000, 0, 500_010, 10),
            LineString([(500_000, 0), (500_050, 0)]),
            Point(500_000, 0),
        ]
    )

    result = measure_geometry(collection, CRS.from_epsg(32631), UTM)

    assert result.status == MeasurementStatus.MEASURED
    assert result.area_m2 == pytest.approx(100, abs=0.001)
    assert result.length_m == pytest.approx(50, abs=0.001)


def test_self_intersecting_polygon_is_repaired():
    bowtie = Polygon([(500_000, 0), (500_010, 10), (500_010, 0), (500_000, 10)])

    result = measure_geometry(bowtie, CRS.from_epsg(32631), UTM)

    assert result.status == MeasurementStatus.MEASURED
    assert result.area_m2 == pytest.approx(50, abs=0.001)  # two 25 m2 triangles, not 0
    assert result.message == (
        "Invalid polygon geometry (Self-intersection) was repaired before measuring."
    )


@pytest.mark.parametrize("geometry", [Point(77, 12), MultiPoint([(77, 12), (77.1, 12.1)])])
def test_points_have_nothing_to_measure(geometry):
    result = measure_geometry(geometry, WGS84, UTM)

    assert result.status == MeasurementStatus.NOT_APPLICABLE
    assert result.area_m2 is None and result.length_m is None


@pytest.mark.parametrize("geometry", [None, Polygon(), GeometryCollection()])
def test_missing_geometry(geometry):
    assert measure_geometry(geometry, WGS84, UTM).status == MeasurementStatus.NO_GEOMETRY


def test_unknown_crs_fails_gracefully():
    result = measure_geometry(box(0, 0, 1, 1), None, UTM)

    assert result.status == MeasurementStatus.FAILED
    assert "source_crs" in result.message


def test_coordinates_outside_declared_crs_fail_gracefully():
    result = measure_geometry(box(776_000, 1_434_000, 776_100, 1_434_100), WGS84, UTM)

    assert result.status == MeasurementStatus.FAILED
    assert "declared CRS" in result.message
