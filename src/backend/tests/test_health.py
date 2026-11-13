from pathlib import Path

from fastapi.testclient import TestClient

from backend.main import app

client = TestClient(app)
ROOT = Path(__file__).resolve().parents[3]


def test_health_endpoint_answers():
    r = client.get("/health")
    assert r.status_code == 200
    assert r.json() == {"status": "ok"}


def test_readme_documents_local_run():
    assert "docs/run.md" in (ROOT / "README.md").read_text(encoding="utf-8")
    text = (ROOT / "docs" / "run.md").read_text(encoding="utf-8")
    assert "uvicorn" in text
    assert "npm run dev" in text
    assert "/health" in text


def test_frontend_has_no_secrets_and_has_dev_script():
    import json

    pkg = json.loads((ROOT / "src" / "frontend" / "package.json").read_text(encoding="utf-8"))
    assert "dev" in pkg["scripts"]
    for p in (ROOT / "src" / "frontend" / "src").rglob("*"):
        if p.is_file() and p.suffix not in (".webp", ".png", ".jpg", ".jpeg", ".gif", ".ico"):
            body = p.read_text(encoding="utf-8")
            for key in ("KAKAO_KEY", "NAVER_CLIENT", "PUBLIC_DATA_DECODED_KEY", "LANGSMITH_API_KEY"):
                assert key not in body


def test_cors_allows_the_frontend_on_any_local_port_only():
    from fastapi.testclient import TestClient

    from backend.main import app

    client = TestClient(app)

    def allowed(origin):
        r = client.options("/chat", headers={"Origin": origin, "Access-Control-Request-Method": "POST",
                                             "Access-Control-Request-Headers": "content-type"})
        return r.headers.get("access-control-allow-origin") == origin

    # Vite moves to 5174 when 5173 is taken: that must not look like a dead server
    for origin in ("http://localhost:5173", "http://localhost:5174", "http://127.0.0.1:5175"):
        assert allowed(origin), origin
    for origin in ("http://evil.example", "http://localhost.evil.example", "https://localhost:5173.evil.example"):
        assert not allowed(origin), origin


# ---------------------------------------------------------------- trial password (APP_PASSWORD)

def _basic(user, password):
    import base64
    return {"Authorization": "Basic " + base64.b64encode(f"{user}:{password}".encode()).decode()}


def test_no_password_set_keeps_everything_open(monkeypatch):
    monkeypatch.delenv("APP_PASSWORD", raising=False)
    assert client.post("/chat", json={"message": ""}).status_code == 422      # reached the API


def test_password_protects_the_app_but_not_the_health_check(monkeypatch):
    monkeypatch.setenv("APP_PASSWORD", "봄소풍2026")
    monkeypatch.setenv("APP_USERNAME", "family")
    assert client.get("/health").status_code == 200                          # Render health check
    r = client.post("/chat", json={"message": ""})
    assert r.status_code == 401 and r.headers["www-authenticate"].startswith("Basic ")
    assert client.post("/chat", json={"message": ""}, headers=_basic("family", "틀림")).status_code == 401
    assert client.post("/chat", json={"message": ""}, headers=_basic("other", "봄소풍2026")).status_code == 401
    assert client.post("/chat", json={"message": ""}, headers={"Authorization": "Basic !!!"}).status_code == 401
    assert client.post("/chat", json={"message": ""}, headers=_basic("family", "봄소풍2026")).status_code == 422


def test_built_frontend_is_served_from_the_same_origin(tmp_path, monkeypatch):
    import importlib

    import backend.main as main

    (tmp_path / "index.html").write_text("<!doctype html><title>아기랑 나들이</title>", encoding="utf-8")
    monkeypatch.delenv("APP_PASSWORD", raising=False)
    monkeypatch.setenv("FRONTEND_DIST", str(tmp_path))
    try:
        c = TestClient(importlib.reload(main).app)
        assert "아기랑 나들이" in c.get("/").text
        assert c.get("/health").json() == {"status": "ok"}                   # the API wins over static files
        assert c.post("/chat", json={"message": ""}).status_code == 422
    finally:
        monkeypatch.delenv("FRONTEND_DIST")
        importlib.reload(main)
