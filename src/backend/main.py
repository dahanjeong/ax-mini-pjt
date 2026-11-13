from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

from .api.chat import router as chat_router

app = FastAPI(title="Baby Outing Chat")

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
