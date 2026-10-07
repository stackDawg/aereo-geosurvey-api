import pytest
from pyproj import CRS
from shapely.geometry import LineString, Point, box

from app.geo.crs import (
    LocalEqualAreaStrategy,
    LonLatExtent,
    ProjectionError,
    UTMStrategy,
    crs_to_string,
    get_transformer,
    lonlat_extent,
    parse_crs,
    utm_zone,
)
from app.geo.errors import InvalidCRSError

WGS84 = CRS.from_epsg(4326)


@pytest.mark.parametrize(
    ("lon", "zone"),
    [(-180, 1), (-177.1, 1), (-174, 2), (0.5, 31), (77.59, 43), (179.99, 60), (180, 1)],
)
def test_utm_zone(lon, zone):
    assert utm_zone(lon) == zone


@pytest.mark.parametrize(
    ("lon", "lat", "expected"),
    [
        (77.59, 12.97, "EPSG:32643"),  # Bengaluru
        (151.21, -33.87, "EPSG:32756"),  # Sydney (southern hemisphere)
        (-74.0, 40.7, "EPSG:32618"),  # New York
    ],
)
def test_utm_strategy_picks_zone_of_feature(lon, lat, expected):
    extent = LonLatExtent(lon, lat, lon + 0.01, lat + 0.01)
    assert UTMStrategy().select(extent).label == expected


def test_utm_strategy_falls_back_outside_utm_latitudes():
    extent = LonLatExtent(10.0, 85.0, 10.1, 85.1)
    assert UTMStrategy().select(extent).label.startswith("+proj=laea")


def test_utm_strategy_falls_back_for_features_far_from_central_meridian():
    # 10 degrees wide: no single UTM zone represents this without large distortion.
    extent = LonLatExtent(70.0, 20.0, 80.0, 21.0)
    assert UTMStrategy().select(extent).label.startswith("+proj=laea")


def test_laea_is_centred_on_feature():
    selected = LocalEqualAreaStrategy().select(LonLatExtent(77.0, 12.0, 78.0, 13.0))
    assert "+lat_0=12.5" in selected.label
    assert "+lon_0=77.5" in selected.label
    assert selected.crs.is_projected


def test_lonlat_extent_unwraps_antimeridian():
    crossing = LineString([(179.9, -17.0), (-179.9, -17.1)])  # Fiji
    extent = lonlat_extent(crossing, WGS84)
    assert extent.max_lon - extent.min_lon == pytest.approx(0.2)
    assert abs(extent.center_lon) == pytest.approx(180.0)


def test_lonlat_extent_from_projected_crs():
    utm43 = CRS.from_epsg(32643)
    x, y = get_transformer(WGS84, utm43).transform(77.59, 12.97)

    extent = lonlat_extent(box(x - 500, y - 500, x + 500, y + 500), utm43)

    assert extent.center_lon == pytest.approx(77.59, abs=1e-4)
    assert extent.center_lat == pytest.approx(12.97, abs=1e-4)


def test_lonlat_extent_rejects_coordinates_that_do_not_fit_the_crs():
    # UTM metres in a file whose .prj claims WGS 84 degrees.
    with pytest.raises(ProjectionError, match="declared CRS"):
        lonlat_extent(Point(776_000, 1_434_000), WGS84)


def test_transformer_uses_lon_lat_axis_order():
    # EPSG:4326 officially declares lat/lon; files store lon/lat. Easting must come from lon.
    easting, northing = get_transformer(WGS84, CRS.from_epsg(32643)).transform(77.59, 12.97)
    assert 700_000 < easting < 800_000
    assert 1_400_000 < northing < 1_500_000


def test_parse_crs_accepts_common_forms():
    assert parse_crs("EPSG:32643").to_epsg() == 32643
    assert parse_crs("epsg:4326").to_epsg() == 4326
    assert parse_crs(CRS.from_epsg(27700).to_wkt()).to_epsg() == 27700


def test_parse_crs_rejects_garbage():
    with pytest.raises(InvalidCRSError):
        parse_crs("not a crs")


def test_crs_to_string_identifies_esri_wkt():
    esri_prj = (
        'PROJCS["WGS_1984_UTM_Zone_43N",GEOGCS["GCS_WGS_1984",DATUM["D_WGS_1984",'
        'SPHEROID["WGS_1984",6378137.0,298.257223563]],PRIMEM["Greenwich",0.0],'
        'UNIT["Degree",0.0174532925199433]],PROJECTION["Transverse_Mercator"],'
        'PARAMETER["False_Easting",500000.0],PARAMETER["False_Northing",0.0],'
        'PARAMETER["Central_Meridian",75.0],PARAMETER["Scale_Factor",0.9996],'
        'PARAMETER["Latitude_Of_Origin",0.0],UNIT["Meter",1.0]]'
    )
    assert crs_to_string(parse_crs(esri_prj)) == "EPSG:32643"
