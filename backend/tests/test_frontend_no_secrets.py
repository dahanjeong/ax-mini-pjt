"""AC: no API key / .env secret appears in the frontend source or its build output."""
import re
import subprocess
import shutil
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[2]
FRONTEND = ROOT / "frontend"
KEY_NAMES = [
    "AWS_ACCESS_KEY_ID", "AWS_SECRET_ACCESS_KEY", "AWS_SESSION_TOKEN", "AWS_BEARER_TOKEN_BEDROCK",
    "LANGSMITH_API_KEY", "LANGSMITH_TRACING", "PUBLIC_DATA_DECODED_KEY",
    "NAVER_CLIENT_ID", "NAVER_CLIENT_KEY", "NAVER_CLIENT_SECRET", "KAKAO_KEY",
]
EXTERNAL_HOSTS = [
    "apis.data.go.kr", "dapi.kakao.com", "openapi.naver.com", "bedrock", "amazonaws.com",
    "smith.langchain.com", "api.smith.langchain.com", "kapi.kakao.com",
]


def _env_values():
    vals = []
    for p in (ROOT / ".env", ROOT / "backend" / ".env"):
        if p.exists():
            for line in p.read_text(encoding="utf-8", errors="ignore").splitlines():
                if "=" in line and not line.strip().startswith("#"):
                    v = line.split("=", 1)[1].strip().strip("'\"")
                    if len(v) >= 6:
                        vals.append(v)
    return vals


def _files(*dirs):
    out = []
    for d in dirs:
        base = FRONTEND / d
        if base.is_file():
            out.append(base)
        elif base.is_dir():
            out += [p for p in base.rglob("*") if p.is_file()]
    return out


def _scan(files):
    values = _env_values()
    for f in files:
        text = f.read_text(encoding="utf-8", errors="ignore")
        for name in KEY_NAMES:
            assert name not in text, f"{name} found in {f}"
        for v in values:
            assert v not in text, f"a .env secret value found in {f}"
        for host in EXTERNAL_HOSTS:
            assert host not in text.lower(), f"external API host {host} in {f}"
        assert not re.search(r"import\.meta\.env\.(?!MODE|DEV|PROD|BASE_URL|SSR)", text), f
        assert "process.env" not in text or f.suffix == ".js" and "dist" in f.parts, f


def test_frontend_source_has_no_secrets_or_external_api_calls():
    files = _files("src", "index.html", "vite.config.js", "package.json")
    assert files
    _scan([f for f in files if f.name != "package.json"] + [FRONTEND / "package.json"])
    # frontend must not ship its own .env files
    assert not list(FRONTEND.glob(".env*"))


def test_frontend_calls_only_the_local_backend():
    for f in _files("src"):
        for url in re.findall(r"https?://[^\s\"'`/]+", f.read_text(encoding="utf-8")):
            assert re.match(r"https?://(localhost|127\.0\.0\.1)(:\d+)?$", url), url


def test_frontend_build_output_has_no_secrets():
    npx = shutil.which("npx")
    if npx is None and not (FRONTEND / "dist").exists():
        pytest.skip("no node toolchain and no dist")
    if npx is not None:
        r = subprocess.run([npx, "vite", "build"], cwd=FRONTEND, capture_output=True, text=True, timeout=180)
        assert r.returncode == 0, r.stdout + r.stderr
    dist = _files("dist")
    assert dist
    _scan(dist)
