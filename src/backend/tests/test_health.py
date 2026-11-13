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
