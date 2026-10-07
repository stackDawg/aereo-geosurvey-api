from pathlib import Path

import pytest
from pyproj import Geod
from shapely.geometry import LineString, Point, Polygon, box

from app.models import FileStatus, GeoFile
from tests.factories import (
    kml,
    kml_polygon,
    placemark,
    shapefile_members,
    shapefile_zip,
    write_shapefile,
    zip_files,
)

GEOD = Geod(ellps="WGS84")
PLOT = [(77.59, 12.97), (77.6, 12.97), (77.6, 12.98), (77.59, 12.98), (77.59, 12.97)]
ROAD = "<LineString><coordinates>77.59,12.97 77.6,12.97</coordinates></LineString>"
SURVEY_KML = kml(
    "<Document><name>Survey</name>"
    + placemark(kml_polygon(PLOT), "Plot A", pm_id="plot-a")
    + placemark(ROAD, "Road")
    + placemark("<Point><coordinates>77.595,12.975</coordinates></Point>", "Well")
    + placemark("<Model><Location><longitude>77</longitude></Location></Model>", "Tower")
    + "</Document>"
)


def upload(client, filename: str, content: bytes, **form):
    return client.post("/api/files/", files={"file": (filename, content)}, data=form)


def test_upload_kml_and_get_results(client):
    response = upload(client, "survey.kml", SURVEY_KML)

    assert response.status_code == 202
    body = response.json()
    assert body["status"] == FileStatus.PENDING
    assert body["filename"] == "survey.kml"
    assert body["file_type"] == "KML"
    assert response.headers["Location"] == f"/api/files/{body['id']}/"

    info = client.get(f"/api/files/{body['id']}/").json()
    assert info["status"] == "COMPLETED"
    assert info["feature_count"] == 4
    assert info["crs"] == "EPSG:4326"
    assert info["layers"] == [{"name": "Survey", "crs": "EPSG:4326", "feature_count": 4}]

    measurements = client.get(f"/api/files/{body['id']}/measurements/").json()
    plot, road, well, tower = measurements["items"]
    assert plot["feature_id"] == "plot-a"
    assert plot["status"] == "MEASURED"
    # Compared with geodesic (ellipsoidal) ground truth; UTM stays within 0.3 %.
    geodesic_area = abs(GEOD.geometry_area_perimeter(Polygon(PLOT))[0])
    geodesic_length = GEOD.geometry_length(LineString(PLOT[:2]))
    assert plot["area_m2"] == pytest.approx(geodesic_area, rel=0.003)
    assert plot["measurement_crs"] == "EPSG:32643"
    assert road["length_m"] == pytest.approx(geodesic_length, rel=0.003)
    assert well["status"] == "NOT_APPLICABLE"
    assert tower["status"] == "UNSUPPORTED"
    assert tower["geometry_type"] == "Model"

    summary = measurements["summary"]
    assert summary["feature_count"] == 4
    assert summary["measured_count"] == 2
    assert summary["total_area_m2"] == plot["area_m2"]
    assert summary["total_length_m"] == road["length_m"]
    assert summary["by_status"] == {"MEASURED": 2, "NOT_APPLICABLE": 1, "UNSUPPORTED": 1}
    assert summary["by_geometry_type"] == {"Polygon": 1, "LineString": 1, "Point": 1, "Model": 1}


def test_features_endpoint_returns_geometry_and_properties(client):
    file_id = upload(client, "survey.kml", SURVEY_KML).json()["id"]

    page = client.get(f"/api/files/{file_id}/features/", params={"limit": 2, "offset": 1}).json()

    assert page["total"] == 4
    assert [f["feature_index"] for f in page["items"]] == [1, 2]
    road = page["items"][0]
    assert road["geometry"] == {
        "type": "LineString",
        "coordinates": [[77.59, 12.97], [77.6, 12.97]],
    }
    assert road["properties"] == {"name": "Road"}
    assert road["crs"] == "EPSG:4326"
    assert road["measurement"]["status"] == "MEASURED"


def test_upload_projected_shapefile(client, tmp_path):
    content = shapefile_zip(
        tmp_path,
        geometries=[box(776_000, 1_434_000, 776_100, 1_434_200)],
        crs="EPSG:32643",
        fields={"name": ["Block 1"]},
    )
    file_id = upload(client, "parcels.zip", content).json()["id"]

    info = client.get(f"/api/files/{file_id}/").json()
    [item] = client.get(f"/api/files/{file_id}/measurements/").json()["items"]

    assert info["status"] == "COMPLETED"
    assert info["crs"] == "EPSG:32643"
    assert item["area_m2"] == pytest.approx(20_000, abs=0.01)
    assert item["perimeter_m"] == pytest.approx(600, abs=0.01)


def test_shapefile_without_prj_needs_source_crs(client, tmp_path):
    content = shapefile_zip(
        tmp_path, geometries=[box(776_000, 1_434_000, 776_100, 1_434_100)], crs=None
    )

    without = upload(client, "noprj.zip", content).json()["id"]
    info = client.get(f"/api/files/{without}/").json()
    [item] = client.get(f"/api/files/{without}/measurements/").json()["items"]
    assert info["status"] == "COMPLETED"
    assert info["crs"] is None
    assert any("source_crs" in w for w in info["warnings"])
    assert item["status"] == "FAILED"

    with_crs = upload(client, "noprj.zip", content, source_crs="epsg:32643").json()
    assert with_crs["source_crs"] == "EPSG:32643"
    info = client.get(f"/api/files/{with_crs['id']}/").json()
    [item] = client.get(f"/api/files/{with_crs['id']}/measurements/").json()["items"]
    assert info["crs"] == "EPSG:32643"
    assert item["area_m2"] == pytest.approx(10_000, abs=0.01)


def test_layers_with_different_crs(client, tmp_path):
    wells = write_shapefile(tmp_path / "a", "wells", [Point(77.59, 12.97)])
    roads = write_shapefile(
        tmp_path / "b",
        "roads",
        [LineString([(776_000, 1_434_000), (776_100, 1_434_000)])],
        "EPSG:32643",
    )
    content = zip_files({**shapefile_members(wells), **shapefile_members(roads)})

    file_id = upload(client, "network.zip", content).json()["id"]
    info = client.get(f"/api/files/{file_id}/").json()

    assert info["crs"] is None
    assert {layer["name"]: layer["crs"] for layer in info["layers"]} == {
        "roads": "EPSG:32643",
        "wells": "EPSG:4326",
    }


def test_upload_kmz(client):
    content = zip_files({"doc.kml": SURVEY_KML})

    file_id = upload(client, "survey.kmz", content).json()["id"]

    assert client.get(f"/api/files/{file_id}/").json()["feature_count"] == 4


@pytest.mark.parametrize(
    ("filename", "content", "form", "status", "message"),
    [
        ("data.geojson", b"{}", {}, 415, "Unsupported file"),
        ("survey.kml", b"", {}, 422, "empty"),
        ("survey.kml", b"<gpx/>", {}, 422, "Not a KML document"),
        ("parcels.zip", b"not a zip", {}, 422, "Not a valid zip"),
        ("parcels.zip", zip_files({"a.txt": b"x"}), {}, 422, "does not contain a shapefile"),
        ("survey.kml", SURVEY_KML, {"source_crs": "EPSG:999999"}, 422, "Unrecognised CRS"),
        ("big.kml", b"<kml>" + b" " * 1024 * 1024 + b"</kml>", {}, 413, "upload limit"),
    ],
    ids=["extension", "empty", "not-kml", "not-zip", "no-shapefile", "bad-crs", "too-large"],
)
def test_invalid_uploads_are_rejected(client, settings, filename, content, form, status, message):
    response = upload(client, filename, content, **form)

    assert response.status_code == status
    assert message in response.json()["detail"]
    assert client.get("/api/files/").json()["total"] == 0
    assert not any(Path(settings.storage_dir).iterdir())


def test_unreadable_file_is_marked_failed(client):
    # The root element is valid, so the upload is accepted; the error surfaces while processing.
    file_id = upload(client, "broken.kml", b"<kml><Document><Placemark>").json()["id"]

    info = client.get(f"/api/files/{file_id}/").json()
    assert info["status"] == "FAILED"
    assert "not well-formed" in info["error"]

    response = client.get(f"/api/files/{file_id}/measurements/")
    assert response.status_code == 409
    assert "failed" in response.json()["detail"]


def test_results_are_not_available_before_processing(client):
    owner_id = client.get("/api/auth/me/").json()["id"]
    session_factory = client.app.state.session_factory
    with session_factory() as session:
        session.add(
            GeoFile(
                id="pending1",
                owner_id=owner_id,
                filename="x.kml",
                file_type="KML",
                size_bytes=1,
                storage_path="x",
                status=FileStatus.PROCESSING,
            )
        )
        session.commit()

    for path in ("measurements", "features"):
        response = client.get(f"/api/files/pending1/{path}/")
        assert response.status_code == 409
        assert "PROCESSING" in response.json()["detail"]
    assert client.delete("/api/files/pending1/").status_code == 409


@pytest.mark.parametrize("path", ["", "measurements/", "features/"])
def test_unknown_file_returns_404(client, path):
    response = client.get(f"/api/files/does-not-exist/{path}")

    assert response.status_code == 404
    assert response.json() == {"detail": "File 'does-not-exist' not found."}


def test_list_and_delete_files(client, settings):
    first = upload(client, "a.kml", SURVEY_KML).json()["id"]
    second = upload(client, "b.kml", SURVEY_KML).json()["id"]

    listing = client.get("/api/files/", params={"limit": 1}).json()
    assert listing["total"] == 2
    assert [f["id"] for f in listing["items"]] == [second]

    assert client.delete(f"/api/files/{first}/").status_code == 204
    assert client.get(f"/api/files/{first}/").status_code == 404
    assert not (Path(settings.storage_dir) / first).exists()
    assert client.get("/api/files/").json()["total"] == 1


def test_health(client):
    assert client.get("/health").json() == {"status": "ok"}


def test_features_can_be_reprojected_for_web_maps(client, tmp_path):
    content = shapefile_zip(
        tmp_path,
        geometries=[LineString([(776_000, 1_434_000), (776_100, 1_434_000)])],
        crs="EPSG:32643",
    )
    file_id = upload(client, "pipes.zip", content).json()["id"]

    [source] = client.get(f"/api/files/{file_id}/features/").json()["items"]
    [web] = client.get(f"/api/files/{file_id}/features/", params={"crs": "EPSG:4326"}).json()[
        "items"
    ]

    assert source["crs"] == "EPSG:32643"
    assert source["geometry"]["coordinates"][0] == [776_000, 1_434_000]
    assert web["crs"] == "EPSG:4326"
    lon, lat = web["geometry"]["coordinates"][0]
    assert 77 < lon < 78 and 12 < lat < 13


def test_features_without_crs_are_not_reprojected(client, tmp_path):
    content = shapefile_zip(tmp_path, geometries=[box(0, 0, 10, 10)], crs=None)
    file_id = upload(client, "noprj.zip", content).json()["id"]

    [feature] = client.get(f"/api/files/{file_id}/features/", params={"crs": "EPSG:4326"}).json()[
        "items"
    ]

    assert feature["crs"] is None
    assert feature["geometry"]["type"] == "Polygon"


def test_invalid_output_crs_is_rejected(client):
    file_id = upload(client, "survey.kml", SURVEY_KML).json()["id"]

    response = client.get(f"/api/files/{file_id}/features/", params={"crs": "nonsense"})

    assert response.status_code == 422
    assert "Unrecognised CRS" in response.json()["detail"]
