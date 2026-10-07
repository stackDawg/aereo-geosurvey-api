from pathlib import Path

import pytest

from app.geo.errors import InvalidGeoFileError
from app.geo.readers import ArchiveLimits
from app.geo.readers.kml import KMLReader, KMZReader
from tests.factories import kml, kml_polygon, placemark, zip_files

LIMITS = ArchiveLimits()
SQUARE = [(77.0, 12.0), (77.01, 12.0), (77.01, 12.01), (77.0, 12.01), (77.0, 12.0)]


def read(tmp_path: Path, content: bytes, reader=KMLReader, suffix=".kml"):
    path = tmp_path / f"input{suffix}"
    path.write_bytes(content)
    reader.validate(path, LIMITS)
    with reader(path) as r:
        return list(r.features()), r


def test_reads_polygon_with_holes_and_attributes(tmp_path):
    hole = [(77.002, 12.002), (77.004, 12.002), (77.004, 12.004), (77.002, 12.002)]
    extra = (
        "<description>North field</description>"
        "<ExtendedData>"
        '<Data name="owner"><value>Ravi</value></Data>'
        '<SchemaData schemaUrl="#plots">'
        '<SimpleData name="crop">ragi</SimpleData><SimpleData name="acres">2.5</SimpleData>'
        '<SimpleData name="plot_no">17</SimpleData>'
        "</SchemaData></ExtendedData>"
    )
    schema = (
        '<Schema name="plots" id="plots"><SimpleField name="acres" type="double"/>'
        '<SimpleField name="plot_no" type="int"/></Schema>'
    )
    content = kml(
        f"<Document>{schema}"
        f"{placemark(kml_polygon(SQUARE, [hole]), 'Plot 17', extra, pm_id='p17')}</Document>"
    )

    [feature], reader = read(tmp_path, content)

    assert feature.feature_id == "p17"
    assert feature.geometry_type == "Polygon"
    assert len(feature.geometry.interiors) == 1
    assert feature.geometry.has_z
    assert feature.properties == {
        "name": "Plot 17",
        "description": "North field",
        "owner": "Ravi",
        "crop": "ragi",
        "acres": 2.5,
        "plot_no": 17,
    }
    assert feature.crs.to_epsg() == 4326
    assert reader.warnings == []


def test_folders_become_layers(tmp_path):
    point = "<Point><coordinates>77,12</coordinates></Point>"
    content = kml(
        "<Document><name>Survey</name>"
        f"{placemark(point, 'a')}"
        f"<Folder><name>Wells</name>{placemark(point, 'b')}"
        f"<Folder>{placemark(point, 'c')}</Folder></Folder>"
        "</Document>"
    )

    features, reader = read(tmp_path, content)

    assert [f.layer for f in features] == ["Survey", "Survey/Wells", "Survey/Wells/Folder"]
    assert list(reader.layers) == ["Survey", "Survey/Wells", "Survey/Wells/Folder"]


def test_multigeometry_is_combined(tmp_path):
    polygons = kml_polygon(SQUARE) * 2
    mixed = (
        kml_polygon(SQUARE) + "<LineString><coordinates>77,12 77.1,12.1</coordinates></LineString>"
    )
    content = kml(
        "<Document>"
        f"{placemark(f'<MultiGeometry>{polygons}</MultiGeometry>', 'multi')}"
        f"{placemark(f'<MultiGeometry>{mixed}</MultiGeometry>', 'mixed')}"
        "</Document>"
    )

    multi, mixed_feature = read(tmp_path, content)[0]

    assert multi.geometry_type == "MultiPolygon"
    assert mixed_feature.geometry_type == "GeometryCollection"


def test_unsupported_geometry_is_reported_not_raised(tmp_path):
    model = "<Model><Location><longitude>77</longitude><latitude>12</latitude></Location></Model>"
    partly = f"<MultiGeometry>{kml_polygon(SQUARE)}{model}</MultiGeometry>"
    content = kml(f"<Document>{placemark(model, 'tower')}{placemark(partly, 'partly')}</Document>")

    tower, partial = read(tmp_path, content)[0]

    assert tower.geometry is None
    assert tower.geometry_type == "Model"
    assert "Model" in tower.unsupported_reason
    assert partial.geometry_type == "MultiPolygon"
    assert "Model" in partial.issue


def test_invalid_coordinates_are_reported_per_feature(tmp_path):
    bad = "<LineString><coordinates>77,12 oops</coordinates></LineString>"
    good = "<Point><coordinates>77,12</coordinates></Point>"
    content = kml(f"<Document>{placemark(bad, 'bad')}{placemark(good, 'good')}</Document>")

    bad_feature, good_feature = read(tmp_path, content)[0]

    assert bad_feature.geometry is None
    assert "invalid coordinate" in bad_feature.issue
    assert good_feature.geometry_type == "Point"


def test_tolerates_spaces_after_commas_and_older_namespaces(tmp_path):
    line = "<LineString><coordinates>77.0, 12.0  77.1, 12.1</coordinates></LineString>"
    content = kml(f"<Document>{placemark(line)}</Document>", "http://earth.google.com/kml/2.1")

    [feature], _ = read(tmp_path, content)

    assert list(feature.geometry.coords) == [(77.0, 12.0), (77.1, 12.1)]


def test_gx_track_is_read_as_line(tmp_path):
    track = (
        "<gx:Track><when>2024-01-01T00:00:00Z</when><gx:coord>77 12 900</gx:coord>"
        "<when>2024-01-01T00:01:00Z</when><gx:coord>77.01 12 900</gx:coord></gx:Track>"
    )
    [feature], _ = read(tmp_path, kml(f"<Document>{placemark(track)}</Document>"))

    assert feature.geometry_type == "LineString"


def test_placemark_without_geometry(tmp_path):
    [feature], _ = read(tmp_path, kml("<Document><Placemark><name>x</name></Placemark></Document>"))

    assert feature.geometry is None
    assert feature.geometry_type is None


def test_network_links_produce_a_warning(tmp_path):
    content = kml(
        "<Document><NetworkLink><Link><href>http://example.com/a.kml</href></Link>"
        "</NetworkLink></Document>"
    )

    features, reader = read(tmp_path, content)

    assert features == []
    assert "NetworkLink" in reader.warnings[0]


def test_kmz_reads_doc_kml(tmp_path):
    point = "<Point><coordinates>77,12</coordinates></Point>"
    content = zip_files(
        {
            "doc.kml": kml(f"<Document>{placemark(point, 'main')}</Document>"),
            "files/other.kml": kml(f"<Document>{placemark(point, 'other')}</Document>"),
        }
    )

    [feature], reader = read(tmp_path, content, KMZReader, ".kmz")

    assert feature.properties["name"] == "main"
    assert "2 KML documents" in reader.warnings[0]


def test_kmz_without_kml_is_rejected(tmp_path):
    with pytest.raises(InvalidGeoFileError, match=r"does not contain a \.kml"):
        read(tmp_path, zip_files({"image.png": b"png"}), KMZReader, ".kmz")


@pytest.mark.parametrize(
    ("content", "message"),
    [
        (b"<gpx></gpx>", "root element is <gpx>"),
        (b"<kml><Document>", "not well-formed"),
        (b"", "not well-formed"),
    ],
)
def test_rejects_non_kml(tmp_path, content, message):
    path = tmp_path / "bad.kml"
    path.write_bytes(content)
    with pytest.raises(InvalidGeoFileError, match=message), KMLReader(path) as reader:
        list(reader.features())


def test_rejects_entity_expansion_attack(tmp_path):
    billion_laughs = (
        b'<?xml version="1.0"?><!DOCTYPE kml [<!ENTITY a "aaaaaaaaaa">'
        b'<!ENTITY b "&a;&a;&a;&a;&a;&a;&a;&a;&a;&a;">]><kml><Document><name>&b;</name>'
        b"</Document></kml>"
    )
    with pytest.raises(InvalidGeoFileError, match="forbidden XML"):
        read(tmp_path, billion_laughs)


def test_rejects_external_entities(tmp_path):
    xxe = (
        b'<?xml version="1.0"?><!DOCTYPE kml [<!ENTITY x SYSTEM "file:///etc/passwd">]>'
        b"<kml><Document><name>&x;</name></Document></kml>"
    )
    with pytest.raises(InvalidGeoFileError, match="forbidden XML"):
        read(tmp_path, xxe)
