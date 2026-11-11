"""Delegation pipeline run by the supervisor: place search -> per-candidate environment
and review agents (fanned out with Send) -> merge & rank.

    START ─┬─ full ────────▶ search ─┬─▶ evaluate (×new candidates, Send) ─▶ rank
           │                 ▲       └─▶ rank (nothing new to evaluate)
           ├─ environment ─▶ refresh_env (×stored candidates, Send) ─────────▶ rank
           └─ rerank ──────────────────────────────────────────────────────▶ rank
    rank ─┬─▶ widen ─▶ search      (full scope, fewer than TOP_N, not widened yet)
          └─▶ finish ─▶ END

Stored `candidates` / `evaluations` from an earlier turn are passed back in, so a
narrower scope re-runs only the agents whose inputs changed.
"""
from __future__ import annotations

import operator
import time
from concurrent.futures import ThreadPoolExecutor
from dataclasses import dataclass
from typing import Annotated, Any, Callable, Optional, TypedDict

from langgraph.graph import END, START, StateGraph
from langgraph.types import Send

from .agents import environment, place, review
from .constants import FACILITY_KEYS, SUIT_RANK
from .intent import SCOPE_ENVIRONMENT, SCOPE_FULL, SCOPE_RERANK
from .tools import Providers

TOP_N = 5

MSG_SEARCH = "주변 장소를 찾고 있어요..."
MSG_WIDEN = "후보가 부족해 검색 반경을 1.5배로 넓혀 다시 찾고 있어요..."
MSG_REFRESH = "바뀐 날짜의 날씨·미세먼지를 다시 확인하고 있어요..."
MSG_DONE = "날씨·편의시설·후기를 확인해 순위를 정했어요."

_ENV_KEYS = ("weather", "dust", "is_bad_day", "bad_day_warnings")
_REVIEW_KEYS = ("review_evidence_count", "review_insufficient", "age_suitability",
                "review_summary", "facility_mentions", "mentions_failed", "indoor_outdoor")


def place_key(p: dict) -> str:
    return "|".join(f"{k}:{v}" for k, v in sorted(p["ids"].items()))


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
    def key(p):
        outdoor_bad = p["indoor_outdoor"] == "outdoor" and p["is_bad_day"]
        return (outdoor_bad, SUIT_RANK[p["age_suitability"]], -p["facility_count"], p["distance_km"])

    return sorted(places, key=key)


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
    candidates: list[dict]                       # stored from an earlier turn (non-full scopes)
    evaluations: Annotated[dict, _merge_evaluations]   # place_key -> environment/review results
    max_drive_hours: Optional[float]
    radius_km: Optional[float]
    radius_expanded: bool
    # working
    radius_scale: float
    # output
    results: list[dict]
    notice: Optional[str]
    failed_sources: Annotated[list[str], operator.add]
    messages: Annotated[list[str], operator.add]


@dataclass
class SubAgents:
    """Compiled sub-graphs, bound to one set of providers."""
    place: Any
    environment: Any
    review: Any

    @classmethod
    def build(cls, prov: Providers) -> "SubAgents":
        return cls(place.build_graph(prov), environment.build_graph(prov), review.build_graph(prov))


def build_pipeline(prov: Providers):
    sub = SubAgents.build(prov)

    def entry(state: PipelineState):
        scope = state.get("scope", SCOPE_FULL)
        if scope == SCOPE_FULL:
            return "search"
        if scope == SCOPE_ENVIRONMENT and state.get("candidates"):
            return [Send("refresh_env", {"place": p, "outing_date": state["outing_date"]})
                    for p in state["candidates"]]
        return "rank"

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
            return "rank"
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

    def rank(state: PipelineState) -> dict:
        evals = state.get("evaluations") or {}
        merged = [merge_place(p, evals[place_key(p)])
                  for p in state.get("candidates") or [] if place_key(p) in evals]
        kept = [p for p in merged if p["age_suitability"] != "부적합"]
        return {"results": rank_places(kept)[:TOP_N]}

    def after_rank(state: PipelineState) -> str:
        short = len(state.get("results") or []) < TOP_N
        if state.get("scope", SCOPE_FULL) == SCOPE_FULL and short and not state.get("radius_expanded"):
            return "widen"
        return "finish"

    def widen(state: PipelineState) -> dict:
        return {"radius_scale": place.WIDEN_FACTOR, "radius_expanded": True, "messages": [MSG_WIDEN]}

    def finish(state: PipelineState) -> dict:
        n = len(state.get("results") or [])
        notice = f"조건에 맞는 장소가 {n}곳뿐이에요. 찾은 장소만 보여드릴게요." if n < TOP_N else None
        return {"notice": notice, "messages": [MSG_DONE]}

    g = StateGraph(PipelineState)
    for name, fn in (("search", search), ("evaluate", evaluate), ("refresh_env", refresh_env),
                     ("rank", rank), ("widen", widen), ("finish", finish)):
        g.add_node(name, fn)
    g.add_conditional_edges(START, entry, ["search", "refresh_env", "rank"])
    g.add_conditional_edges("search", fan_out_new, ["evaluate", "rank"])
    g.add_edge("evaluate", "rank")
    g.add_edge("refresh_env", "rank")
    g.add_conditional_edges("rank", after_rank, ["widen", "finish"])
    g.add_edge("widen", "search")
    g.add_edge("finish", END)
    return g.compile()


def run_pipeline(pipeline: Any, *, scope: str, departure: dict, age_months: int, outing_date: str,
                 travels_during_nap: bool = False, stored: Optional[dict] = None) -> dict:
    """Run the pipeline. `stored` = candidates/evaluations/radius info from the last run
    (ignored for the full scope)."""
    stored = stored if scope != SCOPE_FULL else None
    t0 = time.monotonic()
    first = MSG_REFRESH if scope == SCOPE_ENVIRONMENT else (MSG_SEARCH if scope == SCOPE_FULL else None)
    s = pipeline.invoke({
        "scope": scope,
        "departure": departure,
        "age_months": age_months,
        "travels_during_nap": bool(travels_during_nap),
        "outing_date": outing_date,
        "candidates": (stored or {}).get("candidates") or [],
        "evaluations": (stored or {}).get("evaluations") or {},
        "max_drive_hours": (stored or {}).get("max_drive_hours"),
        "radius_km": (stored or {}).get("radius_km"),
        "radius_expanded": bool((stored or {}).get("radius_expanded")),
        "radius_scale": place.WIDEN_FACTOR if (stored or {}).get("radius_expanded") else 1.0,
        "messages": [first] if first else [],
    })
    return {
        "max_drive_hours": s.get("max_drive_hours"),
        "radius_km": s.get("radius_km"),
        "radius_expanded": bool(s.get("radius_expanded")),
        "result_cards": s.get("results") or [],
        "notice": s.get("notice"),
        "failed_sources": sorted(set(s.get("failed_sources") or [])),
        "messages": list(s.get("messages") or []),
        "elapsed_s": time.monotonic() - t0,
        # kept by the supervisor for the next turn
        "candidates": s.get("candidates") or [],
        "evaluations": s.get("evaluations") or {},
    }


def recommend(
    prov: Providers,
    *,
    age_months: int,
    departure: dict,
    outing_date: str,
    travels_during_nap: bool = False,
    progress: Optional[Callable[[str], None]] = None,
) -> dict:
    """One-shot full recommendation (no conversation)."""
    out = run_pipeline(build_pipeline(prov), scope=SCOPE_FULL, departure=departure,
                       age_months=age_months, outing_date=outing_date,
                       travels_during_nap=travels_during_nap)
    if progress:
        for m in out["messages"]:
            progress(m)
    for k in ("messages", "candidates", "evaluations"):
        out.pop(k)
    return out
