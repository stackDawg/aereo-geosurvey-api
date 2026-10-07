import pytest

from app.main import create_app
from tests.conftest import create_key
from tests.test_api import SURVEY_KML, upload


def test_key_is_returned_once_and_identifies_the_client(anonymous_client):
    response = anonymous_client.post("/api/auth/keys/", json={"name": "Survey team"})

    assert response.status_code == 201
    body = response.json()
    assert body["api_key"].startswith("gm_")
    assert body["key_prefix"] == body["api_key"][:10]

    me = anonymous_client.get("/api/auth/me/", headers={"X-API-Key": body["api_key"]}).json()
    assert me == {k: body[k] for k in ("id", "name", "key_prefix", "created_at")}
    assert "api_key" not in me


@pytest.mark.parametrize(
    ("headers", "detail"),
    [({}, "Missing API key"), ({"X-API-Key": "gm_wrong"}, "Invalid API key")],
)
@pytest.mark.parametrize(
    ("method", "path"),
    [
        ("get", "/api/files/"),
        ("post", "/api/files/"),
        ("get", "/api/files/abc/"),
        ("get", "/api/files/abc/measurements/"),
        ("get", "/api/files/abc/features/"),
        ("delete", "/api/files/abc/"),
        ("get", "/api/auth/me/"),
    ],
)
def test_file_endpoints_require_a_valid_key(anonymous_client, method, path, headers, detail):
    response = anonymous_client.request(method, path, headers=headers)

    assert response.status_code == 401
    assert detail in response.json()["detail"]


def test_clients_only_see_their_own_files(anonymous_client):
    alice = {"X-API-Key": create_key(anonymous_client, "alice")}
    bob = {"X-API-Key": create_key(anonymous_client, "bob")}
    anonymous_client.headers.update(alice)
    file_id = upload(anonymous_client, "survey.kml", SURVEY_KML).json()["id"]

    assert anonymous_client.get("/api/files/").json()["total"] == 1
    for path in ("", "measurements/", "features/"):
        response = anonymous_client.get(f"/api/files/{file_id}/{path}", headers=bob)
        assert response.status_code == 404  # not 403: don't reveal that the file exists
    assert anonymous_client.delete(f"/api/files/{file_id}/", headers=bob).status_code == 404
    assert anonymous_client.get("/api/files/", headers=bob).json()["total"] == 0


def test_self_service_keys_can_be_disabled(settings):
    from fastapi.testclient import TestClient

    settings.allow_key_signup = False
    with TestClient(create_app(settings)) as client:
        response = client.post("/api/auth/keys/", json={"name": "x"})

    assert response.status_code == 403


def test_key_name_is_validated(anonymous_client):
    assert anonymous_client.post("/api/auth/keys/", json={"name": ""}).status_code == 422


def test_cli_creates_working_key(settings, monkeypatch, capsys, anonymous_client):
    from app import cli

    monkeypatch.setattr(cli, "get_settings", lambda: settings)
    cli.main(["create-key", "Ops"])
    key = capsys.readouterr().out.strip().rsplit(" ", 1)[-1]

    me = anonymous_client.get("/api/auth/me/", headers={"X-API-Key": key})
    assert me.json()["name"] == "Ops"
