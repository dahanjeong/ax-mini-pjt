"""Environment sub-graph: weather and fine-dust forecast for one place, then
bad-day judgement.

    START -+-> weather -+-> judge -> END
           +-> dust ----+
"""
from __future__ import annotations

import operator
from typing import Annotated, Any, Optional, TypedDict

from langgraph.graph import END, START, StateGraph

from ..core.constants import FAIL, NO_DUST
from ..tools import Providers, guarded

BAD_GRADES = {"나쁨", "매우나쁨", "매우 나쁨", "높음"}   # 높음: weekly PM2.5 forecast
RAIN_PROB = 60
HEAT_C = 33
COLD_C = -5


def evaluate_bad_day(w: dict, d: dict) -> tuple[bool, list[str]]:
    warnings: list[str] = []
    if isinstance(w.get("precip_prob_max"), (int, float)) and w["precip_prob_max"] >= RAIN_PROB:
        warnings.append("강수")
    if d.get("pm10_grade") in BAD_GRADES or d.get("pm25_grade") in BAD_GRADES:
        warnings.append("미세먼지")
    if isinstance(w.get("temp_max"), (int, float)) and w["temp_max"] >= HEAT_C:
        warnings.append("폭염")
    if isinstance(w.get("temp_min"), (int, float)) and w["temp_min"] <= COLD_C:
        warnings.append("한파")
    return bool(warnings), warnings


class EnvironmentState(TypedDict, total=False):
    # input
    place: dict                     # needs "lat", "lng"
    date: str                       # YYYY-MM-DD
    # internal (None = call failed)
    weather_raw: Optional[dict]
    dust_raw: Optional[dict]
    # output
    weather: dict
    dust: dict
    is_bad_day: bool
    bad_day_warnings: list[str]
    failed_sources: Annotated[list[str], operator.add]


def build_graph(prov: Providers):
    def weather(state: EnvironmentState) -> dict:
        failed: list[str] = []
        p = state["place"]
        raw = guarded(failed, "kma", prov.weather, p["lat"], p["lng"], state["date"])
        return {"weather_raw": raw, "failed_sources": failed}

    def dust(state: EnvironmentState) -> dict:
        failed: list[str] = []
        p = state["place"]
        raw = guarded(failed, "airkorea", prov.dust, p["lat"], p["lng"], state["date"])
        return {"dust_raw": raw, "failed_sources": failed}

    def judge(state: EnvironmentState) -> dict:
        w, d = state.get("weather_raw"), state.get("dust_raw")
        if d is None:
            dust_out = {"status": FAIL}
        elif not d:
            dust_out = {"status": NO_DUST}
        else:
            dust_out = dict(d)
        bad, warns = evaluate_bad_day(w or {}, d or {})
        return {
            "weather": {"status": FAIL} if w is None else dict(w),
            "dust": dust_out,
            "is_bad_day": bad,
            "bad_day_warnings": warns,
        }

    g = StateGraph(EnvironmentState)
    g.add_node("weather", weather)
    g.add_node("dust", dust)
    g.add_node("judge", judge)
    g.add_edge(START, "weather")
    g.add_edge(START, "dust")
    g.add_edge(["weather", "dust"], "judge")
    g.add_edge("judge", END)
    return g.compile()


def run(graph: Any, *, place: dict, date: str) -> dict:
    s = graph.invoke({"place": place, "date": date})
    return {
        "weather": s["weather"],
        "dust": s["dust"],
        "is_bad_day": s["is_bad_day"],
        "bad_day_warnings": s["bad_day_warnings"],
        "failed_sources": list(s.get("failed_sources") or []),
    }
