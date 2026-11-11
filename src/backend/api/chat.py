"""POST /chat: one user turn of the supervisor.

The supervisor graph (in-memory sessions keyed by session_id) and the real integrated
services are built on the first request, so /health and the tests do not need API keys;
tests override `get_service` with fakes.
"""
from __future__ import annotations

import logging
import threading
import uuid
from typing import Any, Optional

from fastapi import APIRouter, Depends, HTTPException

from ..agent import build_graph, recommendation_turn
from ..supervisor.cards import build_cards
from ..tools import Providers
from .schemas import ChatRequest, ChatResponse

log = logging.getLogger(__name__)
router = APIRouter()


class ChatService:
    def __init__(self, graph: Any, providers: Providers):
        self.graph = graph
        self.providers = providers

    def turn(self, session_id: str, message: str) -> dict:
        view = recommendation_turn(self.graph, session_id, message, self.providers)
        if view.get("result_cards") is not None:
            view["result_cards"] = build_cards(view["result_cards"])
        return {**view, "session_id": session_id}


_service: Optional[ChatService] = None
_service_lock = threading.Lock()


def get_service() -> ChatService:
    global _service
    with _service_lock:
        if _service is None:
            try:
                from ..integrations.factory import build_deps, build_providers  # needs the API keys
                _service = ChatService(build_graph(build_deps()), build_providers())
            except Exception:
                log.exception("chat service could not start (check the .env keys)")
                raise HTTPException(status_code=500, detail="internal error")
        return _service


@router.post("/chat", response_model=ChatResponse)
def chat(req: ChatRequest, service: ChatService = Depends(get_service)) -> dict:
    session_id = req.session_id or uuid.uuid4().hex
    try:
        return service.turn(session_id, req.message)
    except Exception:
        # details stay in the server log; the client never sees internals or keys
        log.exception("chat turn failed (session %s)", session_id)
        raise HTTPException(status_code=500, detail="internal error")
