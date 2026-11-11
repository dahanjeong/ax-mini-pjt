"""Shared prompt pieces."""
from __future__ import annotations

import json


def place_data(place: dict) -> str:
    """The place facts given to the LLM (inside <place> ... </place>)."""
    return json.dumps({
        "name": place.get("name"), "types": place.get("types"),
        "address": place.get("address"), "description": place.get("description"),
    }, ensure_ascii=False)
