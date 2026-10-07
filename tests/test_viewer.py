from fastapi.testclient import TestClient

from app.main import create_app


def test_built_viewer_is_served_at_root(settings, tmp_path):
    dist = tmp_path / "dist"
    (dist / "assets").mkdir(parents=True)
    (dist / "index.html").write_text("<!doctype html><title>viewer</title>")
    (dist / "assets" / "app.js").write_text("console.log('viewer')")
    settings.frontend_dir = dist

    with TestClient(create_app(settings), follow_redirects=False) as client:
        assert "viewer" in client.get("/").text
        assert client.get("/assets/app.js").status_code == 200
        # The viewer must not swallow API paths.
        assert client.get("/api/files").status_code == 307
        assert client.get("/nope").status_code == 404


def test_no_viewer_when_not_built(client):
    assert client.get("/").status_code == 404
