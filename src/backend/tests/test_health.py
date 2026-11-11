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
    text = (ROOT / "README.md").read_text(encoding="utf-8")
    assert "uvicorn" in text
    assert "npm run dev" in text
    assert "/health" in text


def test_frontend_has_no_secrets_and_has_dev_script():
    import json

    pkg = json.loads((ROOT / "src" / "frontend" / "package.json").read_text(encoding="utf-8"))
    assert "dev" in pkg["scripts"]
    for p in (ROOT / "src" / "frontend" / "src").rglob("*"):
        if p.is_file():
            body = p.read_text(encoding="utf-8")
            for key in ("KAKAO_KEY", "NAVER_CLIENT", "PUBLIC_DATA_DECODED_KEY", "LANGSMITH_API_KEY"):
                assert key not in body
