from pathlib import Path

import pytest
from shapely.geometry import LineString, Point, box

from app.geo.errors import InvalidGeoFileError
from app.geo.readers import ArchiveLimits
from app.geo.readers.shapefile import ShapefileReader
from tests.factories import shapefile_members, shapefile_zip, write_shapefile, zip_files

LIMITS = ArchiveLimits(max_members=20, max_total_bytes=1024 * 1024)


def read(tmp_path: Path, content: bytes):
    path = tmp_path / "upload.zip"
    path.write_bytes(content)
    ShapefileReader.validate(path, LIMITS)
    with ShapefileReader(path, LIMITS) as reader:
        return list(reader.features()), reader


def test_reads_geometry_attributes_and_crs(tmp_path):
    content = shapefile_zip(
        tmp_path,
        geometries=[box(77.0, 12.0, 77.01, 12.01), box(77.1, 12.1, 77.11, 12.11)],
        fields={"name": ["North", "Ünïcödé"], "acres": [2.5, 4.0], "plot": [1, 2]},
    )

    features, reader = read(tmp_path, content)

    assert [f.feature_id for f in features] == ["0", "1"]
    assert features[0].geometry_type == "Polygon"
    assert features[0].layer == "parcels"
    assert features[1].properties == {"name": "Ünïcödé", "acres": 4.0, "plot": 2}
    assert features[0].crs.to_epsg() == 4326
    assert reader.layers["parcels"].to_epsg() == 4326


def test_shapefile_in_subfolder_and_macos_junk_ignored(tmp_path):
    shp = write_shapefile(tmp_path / "src", "roads", [LineString([(0, 0), (1, 1)])])
    members = shapefile_members(shp, prefix="export/data/")
    members["__MACOSX/export/data/._roads.shp"] = b"junk"
    members["export/.DS_Store"] = b"junk"

    [feature], _ = read(tmp_path, zip_files(members))

    assert feature.geometry_type == "LineString"


def test_every_shapefile_in_the_archive_is_a_layer(tmp_path):
    a = write_shapefile(tmp_path / "a", "wells", [Point(77, 12)])
    b = write_shapefile(tmp_path / "b", "roads", [LineString([(77, 12), (77.1, 12)])], "EPSG:32643")
    c = write_shapefile(tmp_path / "c", "wells", [Point(78, 13)])
    members = {
        **shapefile_members(a, "north/"),
        **shapefile_members(b),
        **shapefile_members(c, "south/"),
    }

    features, reader = read(tmp_path, zip_files(members))

    # Unique names are kept; duplicate names are disambiguated by their folder.
    assert list(reader.layers) == ["north/wells", "roads", "south/wells"]
    assert reader.layers["roads"].to_epsg() == 32643
    assert len(features) == 3


def test_missing_prj_means_unknown_crs(tmp_path):
    content = shapefile_zip(tmp_path, geometries=[box(0, 0, 1, 1)], crs=None)

    [feature], reader = read(tmp_path, content)

    assert feature.crs is None
    assert "no .prj" in reader.warnings[0]


def test_null_geometry_is_kept_as_feature(tmp_path):
    content = shapefile_zip(tmp_path, geometries=[box(0, 0, 1, 1), None], geometry_type="Polygon")

    features, _ = read(tmp_path, content)

    assert features[1].geometry is None
    assert features[1].geometry_type is None


@pytest.mark.parametrize("missing", [".shx", ".dbf"])
def test_incomplete_shapefile_is_rejected(tmp_path, missing):
    shp = write_shapefile(tmp_path / "src", "parcels", [box(0, 0, 1, 1)])
    members = {k: v for k, v in shapefile_members(shp).items() if not k.endswith(missing)}

    with pytest.raises(InvalidGeoFileError, match=f"missing \\{missing}"):
        read(tmp_path, zip_files(members))


def test_archive_without_shapefile_is_rejected(tmp_path):
    with pytest.raises(InvalidGeoFileError, match="does not contain a shapefile"):
        read(tmp_path, zip_files({"readme.txt": b"hello"}))


def test_not_a_zip_is_rejected(tmp_path):
    with pytest.raises(InvalidGeoFileError, match="Not a valid zip"):
        read(tmp_path, b"definitely not a zip")


def test_archive_limits_are_enforced(tmp_path):
    many = {f"file{i}.txt": b"x" for i in range(LIMITS.max_members + 1)}
    with pytest.raises(InvalidGeoFileError, match="limit"):
        read(tmp_path, zip_files(many))

    huge = {"big.dbf": b"\0" * (LIMITS.max_total_bytes + 1)}  # compresses to almost nothing
    with pytest.raises(InvalidGeoFileError, match="limit"):
        read(tmp_path, zip_files(huge))
