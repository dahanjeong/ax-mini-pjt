"""Reviews & suitability sub-graph: NAVER review snippets -> LLM age-suitability
judgement and 3-line summary -> indoor/outdoor classification.

    START -> fetch_reviews -> judge -+-> classify_llm -> END   (category ambiguous)
                                     +-> END                   (category rule decided)

Review text is untrusted: it only goes into the LLM judge as data, and the judge
output is accepted solely in the fixed shape (see cards.parse_llm_judgement).
The LLM is called as a tool inside fixed steps; it never decides the flow.
"""
from __future__ import annotations

import operator
from typing import Annotated, Any, TypedDict

from langgraph.graph import END, START, StateGraph

from ..constants import FAIL, NO_REVIEW, SUIT_RANK
from ..tools import Providers, guarded

MAX_REVIEWS = 10
MIN_REVIEWS = 3
SUMMARY_LINES = 3
INDOOR_RULE = {"tourapi:14": "indoor", "kakao:CT1": "indoor"}  # others are ambiguous -> LLM


def indoor_by_rule(place: dict):
    return next((INDOOR_RULE[t] for t in place.get("types", []) if t in INDOOR_RULE), None)


class ReviewState(TypedDict, total=False):
    # input
    place: dict
    age_months: int
    # internal
    reviews: list[dict]
    reviews_failed: bool
    # output
    review_evidence_count: int
    review_insufficient: bool
    age_suitability: str
    review_summary: list[str]
    facility_mentions: dict
    mentions_failed: bool           # reviews or judge failed -> facility fallback unavailable
    indoor_outdoor: str
    failed_sources: Annotated[list[str], operator.add]


def build_graph(prov: Providers):
    def fetch_reviews(state: ReviewState) -> dict:
        failed: list[str] = []
        reviews = guarded(failed, "naver", prov.reviews, state["place"])
        kept = (reviews or [])[:MAX_REVIEWS]
        return {
            "reviews": kept,
            "reviews_failed": reviews is None,
            "review_evidence_count": len(kept),
            "review_insufficient": len(kept) < MIN_REVIEWS,
            "failed_sources": failed,
        }

    def judge(state: ReviewState) -> dict:
        failed: list[str] = []
        reviews = state.get("reviews") or []
        result = guarded(failed, "llm", prov.llm_judge, state["place"], state["age_months"], reviews) or {}
        judge_failed = bool(failed)
        suit = result.get("age_suitability")
        summary = list(result.get("summary") or [])[:SUMMARY_LINES]
        if state.get("reviews_failed") or (judge_failed and reviews):
            review_summary = [FAIL]
        else:
            review_summary = summary if (reviews and summary) else [NO_REVIEW]
        return {
            "age_suitability": suit if suit in SUIT_RANK else "보통",
            "review_summary": review_summary,
            "facility_mentions": result.get("facility_mentions") or {},
            "mentions_failed": bool(state.get("reviews_failed")) or judge_failed,
            "indoor_outdoor": indoor_by_rule(state["place"]),
            "failed_sources": failed,
        }

    def route_indoor(state: ReviewState) -> str:
        return END if state.get("indoor_outdoor") else "classify_llm"

    def classify_llm(state: ReviewState) -> dict:
        failed: list[str] = []
        io = guarded(failed, "llm", prov.llm_indoor_outdoor, state["place"], state.get("reviews") or [])
        return {"indoor_outdoor": io if io in ("indoor", "outdoor") else "outdoor", "failed_sources": failed}

    g = StateGraph(ReviewState)
    g.add_node("fetch_reviews", fetch_reviews)
    g.add_node("judge", judge)
    g.add_node("classify_llm", classify_llm)
    g.add_edge(START, "fetch_reviews")
    g.add_edge("fetch_reviews", "judge")
    g.add_conditional_edges("judge", route_indoor, ["classify_llm", END])
    g.add_edge("classify_llm", END)
    return g.compile()


_OUTPUT_KEYS = ("review_evidence_count", "review_insufficient", "age_suitability", "review_summary",
                "facility_mentions", "mentions_failed", "indoor_outdoor")


def run(graph: Any, *, place: dict, age_months: int) -> dict:
    s = graph.invoke({"place": place, "age_months": age_months})
    out = {k: s[k] for k in _OUTPUT_KEYS}
    out["failed_sources"] = list(s.get("failed_sources") or [])
    return out
