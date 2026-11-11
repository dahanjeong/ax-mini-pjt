"""Result cards: the fixed field set returned to the client for each recommended place."""
from __future__ import annotations

from typing import Any

from ..core.constants import FACILITY_KEYS, FAIL, NO_DUST, NO_REVIEW, UNKNOWN
from ..prompts.judge import MAX_LINE_CHARS, sanitize_summary

CARD_FIELDS = (
    "name", "distance_km", "indoor_outdoor", "age_suitability", "facilities",
    "weather", "dust", "is_bad_day", "warnings", "review_summary", "failed_sources",
    "preference_match", "includes",
)
MATCH_LEVELS = ("높음", "보통", "낮음")
FACILITY_LABELS = {"nursing_room": "수유실", "stroller_rental": "유모차 대여", "parking": "주차"}
FACILITY_VALUES = ("있음", "없음", UNKNOWN, FAIL)


def _facility(fac: dict, key: str) -> dict:
    f = fac.get(key) or {}
    status = f.get("status")
    return {
        "label": FACILITY_LABELS[key],
        "status": status if status in FACILITY_VALUES else UNKNOWN,
        "source": f.get("source"),
    }


def _preference_match(m: Any) -> Any:
    """{level, evidence: [{doc_id, text}]} or None when no preference was given."""
    if not isinstance(m, dict) or m.get("level") not in MATCH_LEVELS:
        return None
    evidence = []
    for e in m.get("evidence") or []:
        if isinstance(e, dict) and isinstance(e.get("text"), str) and isinstance(e.get("doc_id"), str):
            evidence.append({"doc_id": e["doc_id"], "text": e["text"][:MAX_LINE_CHARS]})
    return {"level": m["level"], "evidence": evidence[:2]}


def build_card(place: dict) -> dict:
    fac = place.get("facilities") or {}
    summary = sanitize_summary(place.get("review_summary"))
    if place.get("review_summary") == [FAIL]:
        summary = [FAIL]
    elif place.get("review_evidence_count", 0) == 0:
        summary = [NO_REVIEW]
    return {
        "name": str(place["name"]),
        "distance_km": round(float(place["distance_km"]), 1),
        "indoor_outdoor": place.get("indoor_outdoor"),
        "age_suitability": place.get("age_suitability", "보통"),
        "facilities": {k: _facility(fac, k) for k in FACILITY_KEYS},
        "weather": place.get("weather") or {"status": FAIL},
        "dust": place.get("dust") or {"status": NO_DUST},
        "is_bad_day": bool(place.get("is_bad_day")),
        "warnings": list(place.get("warnings") or []),
        "review_summary": summary,
        "failed_sources": list(place.get("failed_sources") or []),
        "preference_match": _preference_match(place.get("preference_match")),
        "includes": [str(n) for n in place.get("includes") or []],
    }


def build_cards(places: list[dict]) -> list[dict]:
    return [build_card(p) for p in places]
