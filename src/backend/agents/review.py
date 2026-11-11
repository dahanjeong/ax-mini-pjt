"""Reviews & suitability: NAVER review snippets, LLM age-suitability judgement and
3-line summary, indoor/outdoor classification.

Review text is untrusted: it only goes into the LLM judge as data, and the judge
output is accepted solely in the fixed shape (see cards.parse_llm_judgement).
"""
from __future__ import annotations

from ..constants import FAIL, NO_REVIEW, SUIT_RANK
from ..tools import Providers, guarded

MAX_REVIEWS = 10
MIN_REVIEWS = 3
SUMMARY_LINES = 3
INDOOR_RULE = {"tourapi:14": "indoor", "kakao:CT1": "indoor"}  # others are ambiguous -> LLM


def assess_reviews(prov: Providers, p: dict, age_months: int) -> dict:
    rf: list[str] = []
    jf: list[str] = []
    io_f: list[str] = []

    reviews = guarded(rf, "naver", prov.reviews, p)
    reviews_failed = reviews is None
    reviews = (reviews or [])[:MAX_REVIEWS]

    judge = guarded(jf, "llm", prov.llm_judge, p, age_months, reviews) or {}
    judge_failed = bool(jf)
    suit = judge.get("age_suitability")
    summary = list(judge.get("summary") or [])[:SUMMARY_LINES]
    if reviews_failed or (judge_failed and reviews):
        review_summary = [FAIL]
    else:
        review_summary = summary if (reviews and summary) else [NO_REVIEW]

    # indoor / outdoor: category rule first, LLM only when ambiguous
    io = next((INDOOR_RULE[t] for t in p["types"] if t in INDOOR_RULE), None)
    if io is None:
        io = guarded(io_f, "llm", prov.llm_indoor_outdoor, p, reviews)
        io = io if io in ("indoor", "outdoor") else "outdoor"

    return {
        "review_evidence_count": len(reviews),
        "review_insufficient": len(reviews) < MIN_REVIEWS,
        "age_suitability": suit if suit in SUIT_RANK else "보통",
        "review_summary": review_summary,
        "facility_mentions": judge.get("facility_mentions") or {},
        "mentions_failed": reviews_failed or judge_failed,
        "indoor_outdoor": io,
        "failed_sources": rf + jf + io_f,
    }
