import base64
import os
import secrets
from pathlib import Path

from fastapi import FastAPI, Request
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import Response
from fastapi.staticfiles import StaticFiles

from .api.chat import router as chat_router
from .core.config import load_env

load_env()

app = FastAPI(title="Baby Outing Chat")

# Built frontend (src/frontend/dist, made by `npm run build` / the Dockerfile): served from
# the same origin as the API in deployment. Absent in local development (Vite serves it).
FRONTEND_DIST = Path(os.getenv("FRONTEND_DIST") or Path(__file__).resolve().parents[1] / "frontend" / "dist")

# Trial deployment: one shared password (HTTP Basic auth) when APP_PASSWORD is set.
# Off when it is not set, so local development stays open. /health stays open for the
# platform's health check. The browser asks once and resends it for /chat by itself.
AUTH_REALM = "baby-outing"
OPEN_PATHS = {"/health"}


def _authorized(header: str, user: str, password: str) -> bool:
    if not header.startswith("Basic "):
        return False
    try:
        got_user, _, got_password = base64.b64decode(header[6:]).decode("utf-8").partition(":")
    except (ValueError, UnicodeDecodeError):
        return False
    return secrets.compare_digest(got_user.encode(), user.encode()) & secrets.compare_digest(
        got_password.encode(), password.encode())


@app.middleware("http")
async def basic_auth(request: Request, call_next):
    password = os.getenv("APP_PASSWORD")
    if (not password or request.method == "OPTIONS" or request.url.path in OPEN_PATHS
            or _authorized(request.headers.get("authorization", ""), os.getenv("APP_USERNAME", "family"), password)):
        return await call_next(request)
    return Response(status_code=401, headers={"WWW-Authenticate": f'Basic realm="{AUTH_REALM}", charset="UTF-8"'})


# Local demo: allow the React dev server to call the API, on any local port (Vite moves to
# 5174, 5175, ... when 5173 is taken, and a 5173-only rule then fails like a dead server).
app.add_middleware(
    CORSMiddleware,
    allow_origin_regex=r"http://(localhost|127\.0\.0\.1)(:\d+)?",
    allow_methods=["*"],
    allow_headers=["*"],
)

app.include_router(chat_router)


@app.get("/health")
def health() -> dict:
    return {"status": "ok"}


# registered last: /chat and /health above take precedence over the static files
if FRONTEND_DIST.is_dir():
    app.mount("/", StaticFiles(directory=FRONTEND_DIST, html=True), name="frontend")
