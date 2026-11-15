"""Optional /operator/ static mount (apps/operator build): same-origin, SPA fallback, API unaffected."""

from __future__ import annotations

from starlette.testclient import TestClient

from fazetime_api.main import create_app

from .conftest import make_settings


def test_operator_static_mount_with_spa_fallback(db_path, clock, tmp_path):
    dist = tmp_path / "dist"
    (dist / "assets").mkdir(parents=True)
    (dist / "index.html").write_text("<!doctype html><title>operator</title>")
    (dist / "assets" / "app.js").write_text("console.log('op')")
    with TestClient(create_app(make_settings(db_path, operator_dist=str(dist)), clock)) as client:
        index = client.get("/operator/")
        assert index.status_code == 200 and "<title>operator</title>" in index.text
        assert index.headers["x-frame-options"] == "DENY"
        assert client.get("/operator/assets/app.js").text == "console.log('op')"
        route = client.get("/operator/markets/mkt_123")  # client-side route -> index.html
        assert route.status_code == 200 and "<title>operator</title>" in route.text
        missing = client.get("/operator/assets/missing.js")
        assert missing.status_code == 404 and missing.json()["error"]["code"] == "NOT_FOUND"
        assert client.get("/v1/me").json()["error"]["code"] == "UNAUTHENTICATED"  # API unaffected
        assert client.get("/openapi.json").json()["info"]["title"].startswith("FaZeTime")
        assert client.get("/healthz").json()["ok"] is True


def test_operator_mount_absent_without_dist(db_path, clock, tmp_path):
    with TestClient(create_app(make_settings(db_path, operator_dist=str(tmp_path / "nope")), clock)) as client:
        assert client.get("/operator/").status_code == 404
