"""Delegation pipeline run by the supervisor: place search -> per-candidate environment
and review agents (fanned out with Send) -> preference matching -> rank.

    START ─┬─ full ────────▶ search ─┬─▶ evaluate (×new candidates, Send) ─▶ match
           │                 ▲       └─▶ match (nothing new to evaluate)
           ├─ environment ─▶ refresh_env (×stored candidates, Send) ─────────▶ match
           └─ rerank ──────────────────────────────────────────────────────▶ match
    match ─▶ rank (family-outing order, at most 2 of a kind) ─┬─▶ widen ─▶ search      (full scope, fewer than TOP_N, not widened yet)
                   ├─▶ augment ─▶ evaluate / match
                   │              (preference given, fewer than MIN_HIGH_MATCHES "높음",
                   │               keywords not searched yet)
                   └─▶ finish ─▶ END

Stored `candidates` / `evaluations` / `matches` from an earlier turn are passed back in,
so a narrower scope re-runs only the agents whose inputs changed.
"""
from __future__ import annotations

import operator
import time
from concurrent.futures import ThreadPoolExecutor
from dataclasses import dataclass
from typing import Annotated, Any, Callable, Optional, TypedDict

from langgraph.graph import END, START, StateGraph
from langgraph.types import Send

from ..agents import environment, place, preference, review
from ..agents import candidates
from ..agents.candidates import place_key
from ..core.constants import FACILITY_KEYS, SUIT_RANK
from .intent import SCOPE_ENVIRONMENT, SCOPE_FULL
from ..tools import Providers

TOP_N = 5
MAX_PER_KIND = 2
MIN_HIGH_MATCHES = 3

MSG_SEARCH = "주변 장소를 찾고 있어요..."
MSG_WIDEN = "후보가 부족해 검색 반경을 1.5배로 넓혀 다시 찾고 있어요..."
MSG_REFRESH = "바뀐 날짜의 날씨·미세먼지를 다시 확인하고 있어요..."
MSG_MATCH = "말씀하신 취향과 장소 설명·후기를 비교하고 있어요..."
MSG_AUGMENT = "취향에 잘 맞는 곳이 부족해 취향 키워드로 더 찾고 있어요..."
MSG_DONE = "날씨·편의시설·후기를 확인해 순위를 정했어요."
NOTICE_NO_MATCH = "취향 매칭을 하지 못해 기본 순위로 보여드려요."

_ENV_KEYS = ("weather", "dust", "is_bad_day", "bad_day_warnings")
_REVIEW_KEYS = ("review_evidence_count", "review_insufficient", "age_suitability",
                "review_summary", "facility_mentions", "mentions_failed", "indoor_outdoor")


def _count(fac: dict) -> int:
    return sum(1 for k in FACILITY_KEYS if fac.get(k, {}).get("status") == "있음")


def merge_place(p: dict, ev: dict) -> dict:
    """Candidate + its environment/review results -> one ranked-place record."""
    out = {k: v for k, v in p.items() if k not in ("public_facilities", "public_failed_sources")}
    for k in ("review_evidence_count", "review_insufficient", "age_suitability",
              "review_summary", "indoor_outdoor"):
        out[k] = ev[k]
    fac = place.resolve_facilities(
        p.get("public_facilities"), ev["facility_mentions"], mentions_failed=ev["mentions_failed"]
    )
    out["facilities"] = fac
    out["facility_count"] = _count(fac)
    for k in ("weather", "dust", "is_bad_day"):
        out[k] = ev[k]
    out["warnings"] = ev["bad_day_warnings"] if ev["indoor_outdoor"] == "outdoor" else []
    out["failed_sources"] = sorted(set(
        list(p.get("public_failed_sources") or []) + ev.get("env_failed", []) + ev.get("review_failed", [])
    ))
    return out


def rank_places(places: list[dict]) -> list[dict]:
    """Family-outing order: safety -> preference -> outing grade -> age suitability ->
    facilities -> distance (distance only breaks the last ties: everything is already
    within the baby's drive radius)."""
    def key(p):
        outdoor_bad = p["indoor_outdoor"] == "outdoor" and p["is_bad_day"]
        match = p.get("preference_match")
        pref = preference.LEVEL_RANK[match["level"]] if match else 0
        return (outdoor_bad, pref, candidates.outing_grade(p), SUIT_RANK[p["age_suitability"]],
                -p["facility_count"], p["distance_km"])

    return sorted(places, key=key)


def pick_varied(ranked: list[dict], n: int = TOP_N, per_kind: int = MAX_PER_KIND) -> list[dict]:
    """Top `n` in rank order with at most `per_kind` of one kind (zoo, kids cafe, museum, ...);
    when there are not enough other kinds, the skipped ones fill the remaining slots after them."""
    chosen, skipped, count = [], [], {}
    for i, p in enumerate(ranked):
        k = candidates.kind_of(p)
        if count.get(k, 0) < per_kind:
            chosen.append(i)
            count[k] = count.get(k, 0) + 1
        else:
            skipped.append(i)
        if len(chosen) == n:
            break
    return [ranked[i] for i in chosen] + [ranked[i] for i in skipped[:n - len(chosen)]]


def _merge_evaluations(old: Optional[dict], new: Optional[dict]) -> dict:
    out = dict(old or {})
    for k, v in (new or {}).items():
        out[k] = {**out.get(k, {}), **v}
    return out


class PipelineState(TypedDict, total=False):
    # input
    scope: str
    departure: dict
    age_months: int
    travels_during_nap: bool
    outing_date: str
    preference_text: Optional[str]
    reference: Optional[dict]                    # resolved reference place {"name", "profile"}
    keywords: list[str]                          # preference keywords for the extra search
    # stored from an earlier turn (non-full scopes)
    candidates: list[dict]
    evaluations: Annotated[dict, _merge_evaluations]   # place_key -> environment/review results
    matches: dict                                # place_key -> preference match
    match_query: Optional[list]                  # [preference_text, reference name] the matches are for
    keywords_searched: list[str]
    max_drive_hours: Optional[float]
    radius_km: Optional[float]
    radius_expanded: bool
    # working
    radius_scale: float
    merged: list[dict]
    # output
    results: list[dict]
    preference_status: str                       # off | ok | unavailable | failed
    notice: Optional[str]
    failed_sources: Annotated[list[str], operator.add]
    messages: Annotated[list[str], operator.add]


@dataclass
class SubAgents:
    """Compiled sub-graphs, bound to one set of providers."""
    place: Any
    environment: Any
    review: Any
    preference: Any

    @classmethod
    def build(cls, prov: Providers) -> "SubAgents":
        return cls(place.build_graph(prov), environment.build_graph(prov), review.build_graph(prov),
                   preference.build_graph(prov))


def _wants_preference(state: PipelineState) -> bool:
    return bool(state.get("preference_text") or (state.get("reference") or {}).get("profile"))


def _query_id(state: PipelineState) -> list:
    return [state.get("preference_text"), (state.get("reference") or {}).get("name")]


def build_pipeline(prov: Providers):
    sub = SubAgents.build(prov)

    def entry(state: PipelineState):
        scope = state.get("scope", SCOPE_FULL)
        if scope == SCOPE_FULL:
            return "search"
        if scope == SCOPE_ENVIRONMENT and state.get("candidates"):
            return [Send("refresh_env", {"place": p, "outing_date": state["outing_date"]})
                    for p in state["candidates"]]
        return "match"

    def search(state: PipelineState) -> dict:
        scale = state.get("radius_scale", 1.0)
        found = place.run(sub.place, departure=state["departure"], age_months=state["age_months"],
                          travels_during_nap=bool(state.get("travels_during_nap")), radius_scale=scale)
        return {
            "candidates": found["candidates"],
            "max_drive_hours": found["max_drive_hours"],
            "radius_km": found["radius_km"],
            "failed_sources": found["failed_sources"],
        }

    def fan_out_new(state: PipelineState):
        done = state.get("evaluations") or {}
        new = [p for p in state.get("candidates") or [] if place_key(p) not in done]
        if not new:
            return "match"
        return [Send("evaluate", {"place": p, "age_months": state["age_months"],
                                  "outing_date": state["outing_date"]}) for p in new]

    def evaluate(item: dict) -> dict:
        p = item["place"]
        with ThreadPoolExecutor(max_workers=2) as ex:
            f_env = ex.submit(environment.run, sub.environment, place=p, date=item["outing_date"])
            f_rev = ex.submit(review.run, sub.review, place=p, age_months=item["age_months"])
            env, rev = f_env.result(), f_rev.result()
        ev = {k: env[k] for k in _ENV_KEYS} | {k: rev[k] for k in _REVIEW_KEYS}
        ev["env_failed"] = env["failed_sources"]
        ev["review_failed"] = rev["failed_sources"]
        return {"evaluations": {place_key(p): ev}}

    def refresh_env(item: dict) -> dict:
        p = item["place"]
        env = environment.run(sub.environment, place=p, date=item["outing_date"])
        ev = {k: env[k] for k in _ENV_KEYS}
        ev["env_failed"] = env["failed_sources"]
        return {"evaluations": {place_key(p): ev}}

    def match(state: PipelineState) -> dict:
        evals = state.get("evaluations") or {}
        merged = [merge_place(p, evals[place_key(p)])
                  for p in state.get("candidates") or [] if place_key(p) in evals]
        merged = [p for p in merged if p["age_suitability"] != "부적합"]
        if not _wants_preference(state):
            return {"merged": merged, "matches": {}, "match_query": None, "preference_status": "off"}
        stored = state.get("matches") or {}
        if (state.get("match_query") == _query_id(state) and state.get("preference_status") == "ok"
                and all(place_key(p) in stored for p in merged)):
            return {"merged": merged}                     # nothing new to match
        out = preference.run(sub.preference, places=merged, preference_text=state.get("preference_text"),
                             reference=state.get("reference"))
        return {
            "merged": merged,
            "matches": out["matches"],
            "match_query": _query_id(state),
            "preference_status": out["status"] if out["status"] != "skipped" else "off",
            "messages": [MSG_MATCH] if out["status"] == "ok" else [],
            "failed_sources": out["failed_sources"],
        }

    def rank(state: PipelineState) -> dict:
        matches = state.get("matches") or {}
        records = [{**p, "preference_match": matches.get(place_key(p))} for p in state.get("merged") or []]
        return {"results": pick_varied(rank_places(records))}

    def after_rank(state: PipelineState) -> str:
        results = state.get("results") or []
        if (state.get("scope", SCOPE_FULL) == SCOPE_FULL and len(results) < TOP_N
                and not state.get("radius_expanded")):
            return "widen"
        high = sum(1 for p in results if (p.get("preference_match") or {}).get("level") == "높음")
        keywords = state.get("keywords") or []
        if (state.get("preference_status") == "ok" and high < MIN_HIGH_MATCHES and keywords
                and keywords != (state.get("keywords_searched") or []) and prov.keyword_search is not None):
            return "augment"
        return "finish"

    def widen(state: PipelineState) -> dict:
        return {"radius_scale": place.WIDEN_FACTOR, "radius_expanded": True, "messages": [MSG_WIDEN]}

    def augment(state: PipelineState) -> dict:
        found = place.run(sub.place, departure=state["departure"], age_months=state["age_months"],
                          travels_during_nap=bool(state.get("travels_during_nap")),
                          radius_scale=state.get("radius_scale", 1.0),
                          keywords=state["keywords"], exclude=state.get("candidates") or [])
        return {
            "candidates": list(state.get("candidates") or []) + found["candidates"],
            "keywords_searched": list(state["keywords"]),
            "failed_sources": found["failed_sources"],
            "messages": [MSG_AUGMENT],
        }

    def finish(state: PipelineState) -> dict:
        n = len(state.get("results") or [])
        notices = []
        if n < TOP_N:
            notices.append(f"조건에 맞는 장소가 {n}곳뿐이에요. 찾은 장소만 보여드릴게요.")
        if _wants_preference(state) and state.get("preference_status") in ("unavailable", "failed"):
            notices.append(NOTICE_NO_MATCH)
        return {"notice": " ".join(notices) or None, "messages": [MSG_DONE]}

    g = StateGraph(PipelineState)
    for name, fn in (("search", search), ("evaluate", evaluate), ("refresh_env", refresh_env),
                     ("match", match), ("rank", rank), ("widen", widen), ("augment", augment),
                     ("finish", finish)):
        g.add_node(name, fn)
    g.add_conditional_edges(START, entry, ["search", "refresh_env", "match"])
    g.add_conditional_edges("search", fan_out_new, ["evaluate", "match"])
    g.add_conditional_edges("augment", fan_out_new, ["evaluate", "match"])
    g.add_edge("evaluate", "match")
    g.add_edge("refresh_env", "match")
    g.add_edge("match", "rank")
    g.add_conditional_edges("rank", after_rank, ["widen", "augment", "finish"])
    g.add_edge("widen", "search")
    g.add_edge("finish", END)
    return g.compile()


_STORED_KEYS = ("candidates", "evaluations", "matches", "match_query", "keywords_searched",
                "preference_status", "max_drive_hours", "radius_km", "radius_expanded")


def run_pipeline(pipeline: Any, *, scope: str, departure: dict, age_months: int, outing_date: str,
                 travels_during_nap: bool = False, preference_text: Optional[str] = None,
                 reference: Optional[dict] = None, keywords: Optional[list[str]] = None,
                 stored: Optional[dict] = None) -> dict:
    """Run the pipeline. `stored` = what the last run returned under `_STORED_KEYS`
    (ignored for the full scope)."""
    stored = (stored or {}) if scope != SCOPE_FULL else {}
    t0 = time.monotonic()
    first = MSG_REFRESH if scope == SCOPE_ENVIRONMENT else (MSG_SEARCH if scope == SCOPE_FULL else None)
    s = pipeline.invoke({
        "scope": scope,
        "departure": departure,
        "age_months": age_months,
        "travels_during_nap": bool(travels_during_nap),
        "outing_date": outing_date,
        "preference_text": preference_text,
        "reference": reference,
        "keywords": list(keywords or []),
        "candidates": stored.get("candidates") or [],
        "evaluations": stored.get("evaluations") or {},
        "matches": stored.get("matches") or {},
        "match_query": stored.get("match_query"),
        "keywords_searched": stored.get("keywords_searched") or [],
        "preference_status": stored.get("preference_status") or "off",
        "max_drive_hours": stored.get("max_drive_hours"),
        "radius_km": stored.get("radius_km"),
        "radius_expanded": bool(stored.get("radius_expanded")),
        "radius_scale": place.WIDEN_FACTOR if stored.get("radius_expanded") else 1.0,
        "messages": [first] if first else [],
    })
    return {
        "max_drive_hours": s.get("max_drive_hours"),
        "radius_km": s.get("radius_km"),
        "radius_expanded": bool(s.get("radius_expanded")),
        "result_cards": s.get("results") or [],
        "notice": s.get("notice"),
        "preference_status": s.get("preference_status") or "off",
        "failed_sources": sorted(set(s.get("failed_sources") or [])),
        "messages": list(s.get("messages") or []),
        "elapsed_s": time.monotonic() - t0,
        # kept by the supervisor for the next turn
        "candidates": s.get("candidates") or [],
        "evaluations": s.get("evaluations") or {},
        "matches": s.get("matches") or {},
        "match_query": s.get("match_query"),
        "keywords_searched": s.get("keywords_searched") or [],
    }


def recommend(
    prov: Providers,
    *,
    age_months: int,
    departure: dict,
    outing_date: str,
    travels_during_nap: bool = False,
    preference_text: Optional[str] = None,
    keywords: Optional[list[str]] = None,
    progress: Optional[Callable[[str], None]] = None,
) -> dict:
    """One-shot full recommendation (no conversation)."""
    out = run_pipeline(build_pipeline(prov), scope=SCOPE_FULL, departure=departure,
                       age_months=age_months, outing_date=outing_date,
                       travels_during_nap=travels_during_nap, preference_text=preference_text,
                       keywords=keywords)
    if progress:
        for m in out["messages"]:
            progress(m)
    for k in ("messages", "candidates", "evaluations", "matches", "match_query", "keywords_searched"):
        out.pop(k)
    return out
