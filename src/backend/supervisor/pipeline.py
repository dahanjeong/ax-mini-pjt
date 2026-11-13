"""Delegation pipeline run by the supervisor: place search -> per-candidate environment
and review agents (fanned out with Send) -> preference matching -> rank.

    START ─┬─ full ────────▶ search ─┬─▶ evaluate (×new candidates, Send) ─▶ match
           │                 ▲       └─▶ match (nothing new to evaluate)
           ├─ environment ─▶ refresh_env (×stored candidates, Send) ─────────▶ match
           └─ rerank ──────────────────────────────────────────────────────▶ match
    match ─▶ rank (family-outing order, at most 2 of a kind, drive-time check)
                   ├─▶ widen ─▶ search      (full scope, fewer than TOP_N, not widened yet)
                   ├─▶ augment ─▶ evaluate / match
                   │              (preference given, fewer than MIN_HIGH_MATCHES "높음",
                   │               keywords not searched yet)
                   └─▶ finish ─▶ END

Drive-time check: the radius (max drive hours x 40 km/h / 1.3) only gathers candidates.
`rank` asks Kakao Mobility for the expected car travel time of the picks when leaving at
the user's departure time on the outing date (09:00 when not given; future-traffic directions;
the next minute when that has already passed today; at most MAX_DRIVE_CHECKS calls per rank): over the age limit -> dropped and the next one picked,
within it -> "확인됨" with minutes, unchecked (API failure / budget used up / no provider)
-> "이동시간 확인 필요". An unchecked place is only shown when it lies inside the age
radius (not the widened one).

Stored `candidates` / `evaluations` / `matches` / `drive_times` from an earlier turn are
passed back in, so a narrower scope re-runs only the agents whose inputs changed
(drive times are kept per departure time, so a date or leaving-time change re-checks them).
"""
from __future__ import annotations

import operator
import time
from concurrent.futures import ThreadPoolExecutor
from dataclasses import dataclass
from datetime import date, datetime, time as dtime, timedelta, timezone
from typing import Annotated, Any, Callable, Optional, TypedDict

from langgraph.graph import END, START, StateGraph
from langgraph.types import Send

from ..agents import environment, place, preference, review
from ..agents import candidates
from ..agents.candidates import excluded_by, matches_kind, place_key, search_words
from ..core.constants import DRIVE_CONFIRMED, DRIVE_UNVERIFIED, FACILITY_KEYS, SUIT_RANK
from .intent import SCOPE_ENVIRONMENT, SCOPE_FULL
from ..tools import Providers, guarded

TOP_N = 5
MAX_PER_KIND = 2
MIN_HIGH_MATCHES = 3
MAX_DRIVE_CHECKS = 10            # Kakao Mobility calls per rank
OUTING_START_HOUR = 9            # leaving time when none is given (weather uses 09-18)
KST = timezone(timedelta(hours=9))

MSG_SEARCH = "주변 장소를 찾고 있어요..."
MSG_WIDEN = "후보가 부족해 검색 반경을 1.5배로 넓혀 다시 찾고 있어요..."
MSG_REFRESH = "바뀐 날짜의 날씨·미세먼지를 다시 확인하고 있어요..."
MSG_MATCH = "말씀하신 취향과 장소 설명·후기를 비교하고 있어요..."
MSG_AUGMENT = "취향에 잘 맞는 곳이 부족해 취향 키워드로 더 찾고 있어요..."
MSG_INCLUDE = "말씀하신 {terms} 장소가 후보에 없어 더 찾고 있어요..."
MSG_DRIVE = "추천 후보의 실제 차량 이동시간을 확인하고 있어요..."
# the closing line names only what this run checked (a date change does not re-read reviews)
MSG_DONE = "날씨·편의시설·후기를 확인해 순위를 정했어요."
MSG_DONE_ENVIRONMENT = "바뀐 날짜의 날씨·미세먼지로 순위를 다시 정리했어요."
MSG_DONE_RERANK = "바뀐 조건을 반영해 순위를 다시 정했어요."
NOTICE_NO_MATCH = "취향 매칭을 하지 못해 기본 순위로 보여드려요."
NOTICE_WEATHER_HELD = ("날씨가 좋지 않은 날이라 취향에 잘 맞는 야외 장소({names} 등)보다 실내 장소를 먼저 "
                       "보여드려요. 날짜를 바꾸면 다시 확인할게요.")

_ENV_KEYS = ("weather", "dust", "is_bad_day", "bad_day_warnings")
_REVIEW_KEYS = ("review_evidence_count", "review_insufficient", "age_suitability",
                "review_summary", "review_sources", "facility_mentions", "mentions_failed", "indoor_outdoor")


def _count(fac: dict) -> int:
    return sum(1 for k in FACILITY_KEYS if fac.get(k, {}).get("status") == "있음")


def merge_place(p: dict, ev: dict) -> dict:
    """Candidate + its environment/review results -> one ranked-place record."""
    out = {k: v for k, v in p.items() if k not in ("public_facilities", "public_failed_sources")}
    for k in ("review_evidence_count", "review_insufficient", "age_suitability",
              "review_summary", "indoor_outdoor"):
        out[k] = ev[k]
    out["review_sources"] = ev.get("review_sources") or []
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


def departure_time_for(outing_date: str, now: Optional[datetime] = None,
                       departure_time: Optional[str] = None) -> datetime:
    """Departure time the drive is estimated for: the user's leaving time ("HH:MM", KST) on the
    outing date, OUTING_START_HOUR when not given; the next minute when it has already passed."""
    now = now or datetime.now(KST)
    hh, mm = (int(x) for x in departure_time.split(":")) if departure_time else (OUTING_START_HOUR, 0)
    start = datetime.combine(date.fromisoformat(outing_date), dtime(hh, mm), KST)
    return max(start, (now.astimezone(KST) + timedelta(minutes=1)).replace(second=0, microsecond=0))


def drive_status(minutes: Optional[float], limit_min: float, departure_time: str) -> Optional[dict]:
    """Card `drive` of a place: unchecked -> 이동시간 확인 필요, within the limit -> 확인됨;
    None when it is over the limit (the place is not recommended)."""
    if minutes is None:
        return {"status": DRIVE_UNVERIFIED, "minutes": None, "departure_time": departure_time}
    if minutes > limit_min:
        return None
    return {"status": DRIVE_CONFIRMED, "minutes": minutes, "departure_time": departure_time}


def pick_including(ranked: list[dict], include: list[str], n: int = TOP_N,
                   per_kind: int = MAX_PER_KIND) -> list[dict]:
    """`pick_varied`, then for each kind the user asked to add ("물놀이 장소도 추천해주세요")
    that is not in the picks: its best-ranked places (up to `per_kind`) replace the lowest picks
    that are not themselves an asked-for kind. The result stays in rank order."""
    picks = pick_varied(ranked, n, per_kind)
    for term in include or []:
        if any(matches_kind(p, term) for p in picks):
            continue
        keys = {place_key(p) for p in picks}
        extra = [p for p in ranked if matches_kind(p, term) and place_key(p) not in keys][:per_kind]
        if not extra:
            continue
        keep = [p for p in picks if any(matches_kind(p, t) for t in include)]
        rest = [p for p in picks if p not in keep]
        picks = keep + rest[:max(0, n - len(keep) - len(extra))] + extra
        order = {place_key(p): i for i, p in enumerate(ranked)}
        picks.sort(key=lambda p: order[place_key(p)])
    return picks


def pick_with_drive_check(ranked: list[dict], *, departure: dict, max_drive_hours: float,
                          departure_time: datetime, drive_times: dict, drive_minutes: Optional[Callable],
                          include: Optional[list[str]] = None,
                          max_checks: int = MAX_DRIVE_CHECKS) -> tuple[list[dict], dict, list[str], int]:
    """`pick_varied`, checking the picks' expected car travel time when leaving at
    `departure_time` (future traffic): a pick over the limit is dropped and the next one
    picked, until all picks are checked or `max_checks` calls are used.
    `drive_times`: "<place_key>@<departure time>" -> minutes (None = the call failed), reused
    across ranks and turns with the same departure time.
    Returns (picks with "drive", updated drive_times, failed sources, calls made)."""
    limit_min = max_drive_hours * 60
    when = departure_time.strftime("%Y-%m-%dT%H:%M")

    def dk(p: dict) -> str:
        return f"{place_key(p)}@{when}"
    age_radius = place.radius_km_for(max_drive_hours)
    times = dict(drive_times or {})
    failed: list[str] = []
    calls = 0

    def allowed(p: dict, can_check: bool) -> bool:
        k = dk(p)
        if k in times and times[k] is not None:
            return times[k] <= limit_min
        # failed or not checked: shown unverified only inside the age radius; a not-yet-checked
        # place further out stays eligible while it can still be checked
        return p["distance_km"] <= age_radius or (can_check and k not in times)

    def check(p: dict) -> tuple[Optional[float], list[str]]:
        f: list[str] = []
        minutes = guarded(f, "kakao_navi", drive_minutes, departure["lat"], departure["lng"], p["lat"], p["lng"],
                          departure_time)
        return minutes, f

    while True:
        can_check = drive_minutes is not None and calls < max_checks
        picks = pick_including([p for p in ranked if allowed(p, can_check)], include or [])
        todo = [p for p in picks if dk(p) not in times][:max_checks - calls]
        if not can_check or not todo:
            break
        with ThreadPoolExecutor(max_workers=len(todo)) as ex:
            res = list(ex.map(check, todo))
        for p, (minutes, f) in zip(todo, res):
            times[dk(p)] = minutes
            failed += f
        calls += len(todo)
    out = [{**p, "drive": drive_status(times.get(dk(p)), limit_min, when)} for p in picks]
    return out, times, sorted(set(failed)), calls


def _merge_evaluations(old: Optional[dict], new: Optional[dict]) -> dict:
    out = dict(old or {})
    for k, v in (new or {}).items():
        out[k] = {**out.get(k, {}), **v}
    return out


class PipelineState(TypedDict, total=False):
    # input
    scope: str
    now: Optional[datetime]                      # the supervisor's clock (Deps.now); None = wall clock
    departure: dict
    age_months: int
    travels_during_nap: bool
    outing_date: str
    departure_time: Optional[str]                # "HH:MM" leaving time (None -> OUTING_START_HOUR)
    preference_text: Optional[str]
    reference: Optional[dict]                    # resolved reference place {"name", "profile"}
    keywords: list[str]                          # preference keywords for the extra search
    exclude: list[str]                           # kinds / place names to leave out of the list
    include: list[str]                           # kinds to add to the list ("물놀이도 추천해주세요")
    include_searched: list[str]                  # search words already used for `include`
    excluded_count: int                          # places dropped by `exclude` in the last match
    # stored from an earlier turn (non-full scopes)
    candidates: list[dict]
    evaluations: Annotated[dict, _merge_evaluations]   # place_key -> environment/review results
    matches: dict                                # place_key -> preference match
    match_query: Optional[list]                  # [preference_text, reference name] the matches are for
    keywords_searched: list[str]
    drive_times: dict                            # "<place_key>@<departure>" -> car minutes (None = check failed)
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


def _search_keywords(state: PipelineState) -> list[str]:
    """Preference keywords for the extra search, minus anything the user excluded."""
    from .intent import is_excluded_keyword
    return [k for k in state.get("keywords") or [] if not is_excluded_keyword(k, state.get("exclude") or [])]


def _missing_inclusions(state: PipelineState) -> list[str]:
    """Kinds the user asked to add that are still not in the results."""
    results = state.get("results") or []
    return [t for t in state.get("include") or [] if not any(matches_kind(p, t) for p in results)]


def _held_back_by_weather(state: PipelineState) -> list[str]:
    """Outdoor places that match the preference 높음 but were ranked below the results
    because of a bad-weather day (the safety rule), best first."""
    shown = {place_key(p) for p in state.get("results") or []}
    matches = state.get("matches") or {}
    return [p["name"] for p in rank_places([{**p, "preference_match": matches.get(place_key(p))}
                                            for p in state.get("merged") or []])
            if place_key(p) not in shown and p["indoor_outdoor"] == "outdoor" and p["is_bad_day"]
            and (matches.get(place_key(p)) or {}).get("level") == "높음"]


def _augment_keywords(state: PipelineState) -> tuple[list[str], list[str]]:
    """(search words for asked-for kinds not found yet, preference keywords) still to search."""
    searched = set(state.get("include_searched") or [])
    inc = [w for t in _missing_inclusions(state) for w in search_words(t) if w not in searched]
    results = state.get("results") or []
    high = sum(1 for p in results if (p.get("preference_match") or {}).get("level") == "높음")
    keywords = _search_keywords(state)
    pref = keywords if (state.get("preference_status") == "ok" and high < MIN_HIGH_MATCHES and keywords
                        and keywords != (state.get("keywords_searched") or [])) else []
    return inc, pref


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
        before = len(merged)
        merged = [p for p in merged if not excluded_by(p, state.get("exclude") or [])]
        excluded = {"excluded_count": before - len(merged)}
        if not _wants_preference(state):
            return {"merged": merged, "matches": {}, "match_query": None, "preference_status": "off", **excluded}
        stored = state.get("matches") or {}
        if (state.get("match_query") == _query_id(state) and state.get("preference_status") == "ok"
                and all(place_key(p) in stored for p in merged)):
            return {"merged": merged, **excluded}         # nothing new to match
        out = preference.run(sub.preference, places=merged, preference_text=state.get("preference_text"),
                             reference=state.get("reference"))
        return {
            "merged": merged,
            "matches": out["matches"],
            "match_query": _query_id(state),
            "preference_status": out["status"] if out["status"] != "skipped" else "off",
            "messages": [MSG_MATCH] if out["status"] == "ok" else [],
            "failed_sources": out["failed_sources"],
            **excluded,
        }

    def rank(state: PipelineState) -> dict:
        matches = state.get("matches") or {}
        records = [{**p, "preference_match": matches.get(place_key(p))} for p in state.get("merged") or []]
        hours = state.get("max_drive_hours") or place.max_drive_hours(
            state["age_months"], bool(state.get("travels_during_nap")))
        picks, times, failed, calls = pick_with_drive_check(
            rank_places(records), departure=state["departure"], max_drive_hours=hours,
            departure_time=departure_time_for(state["outing_date"], state.get("now"),
                                              departure_time=state.get("departure_time")),
            drive_times=state.get("drive_times") or {}, drive_minutes=prov.drive_minutes,
            include=state.get("include") or [])
        return {"results": picks, "drive_times": times, "failed_sources": failed,
                "messages": [MSG_DRIVE] if calls else []}

    def after_rank(state: PipelineState) -> str:
        results = state.get("results") or []
        if len(results) < TOP_N and not state.get("radius_expanded") and (
                state.get("scope", SCOPE_FULL) == SCOPE_FULL or state.get("excluded_count")):
            return "widen"                               # too few, also after leaving places out
        inc_words, pref_words = _augment_keywords(state)
        if (inc_words or pref_words) and prov.keyword_search is not None:
            return "augment"
        return "finish"

    def widen(state: PipelineState) -> dict:
        return {"radius_scale": place.WIDEN_FACTOR, "radius_expanded": True, "messages": [MSG_WIDEN]}

    def augment(state: PipelineState) -> dict:
        inc_words, pref_words = _augment_keywords(state)
        found = place.run(sub.place, departure=state["departure"], age_months=state["age_months"],
                          travels_during_nap=bool(state.get("travels_during_nap")),
                          radius_scale=state.get("radius_scale", 1.0),
                          keywords=inc_words + pref_words, exclude=state.get("candidates") or [])
        out = {
            "candidates": list(state.get("candidates") or []) + found["candidates"],
            "failed_sources": found["failed_sources"],
            "messages": [],
        }
        if inc_words:
            out["include_searched"] = list(state.get("include_searched") or []) + inc_words
            out["messages"].append(MSG_INCLUDE.format(terms="·".join(_missing_inclusions(state))))
        if pref_words:
            out["keywords_searched"] = _search_keywords(state)
            out["messages"].append(MSG_AUGMENT)
        return out

    def finish(state: PipelineState) -> dict:
        n = len(state.get("results") or [])
        notices = []
        if n < TOP_N:
            notices.append(f"조건에 맞는 장소가 {n}곳뿐이에요. 찾은 장소만 보여드릴게요.")
        if _wants_preference(state) and state.get("preference_status") in ("unavailable", "failed"):
            notices.append(NOTICE_NO_MATCH)
        for t in _missing_inclusions(state):
            notices.append(f"반경 안에서 {t} 장소를 찾지 못했어요.")
        if state.get("excluded_count"):
            notices.append(f"제외 조건({', '.join(state.get('exclude') or [])})에 해당하는 곳은 빼고 골랐어요.")
        held = _held_back_by_weather(state)
        if held:
            notices.append(NOTICE_WEATHER_HELD.format(names=", ".join(held[:2])))
        scope = state.get("scope", SCOPE_FULL)
        done = {SCOPE_FULL: MSG_DONE, SCOPE_ENVIRONMENT: MSG_DONE_ENVIRONMENT}.get(scope, MSG_DONE_RERANK)
        return {"notice": " ".join(notices) or None, "messages": [done]}

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


_STORED_KEYS = ("candidates", "evaluations", "matches", "match_query", "keywords_searched", "include_searched",
                "drive_times", "preference_status", "max_drive_hours", "radius_km", "radius_expanded")


def run_pipeline(pipeline: Any, *, scope: str, departure: dict, age_months: int, outing_date: str,
                 departure_time: Optional[str] = None, travels_during_nap: bool = False, preference_text: Optional[str] = None,
                 reference: Optional[dict] = None, keywords: Optional[list[str]] = None,
                 exclude: Optional[list[str]] = None, include: Optional[list[str]] = None,
                 stored: Optional[dict] = None, now: Optional[datetime] = None) -> dict:
    """Run the pipeline. `stored` = what the last run returned under `_STORED_KEYS`
    (ignored for the full scope). `now` = the caller's clock for "already passed" departure
    times (the supervisor passes Deps.now, so tests and the conversation share one clock)."""
    stored = (stored or {}) if scope != SCOPE_FULL else {}
    t0 = time.monotonic()
    first = MSG_REFRESH if scope == SCOPE_ENVIRONMENT else (MSG_SEARCH if scope == SCOPE_FULL else None)
    s = pipeline.invoke({
        "scope": scope,
        "now": now,
        "departure": departure,
        "age_months": age_months,
        "travels_during_nap": bool(travels_during_nap),
        "outing_date": outing_date,
        "departure_time": departure_time,
        "preference_text": preference_text,
        "reference": reference,
        "keywords": list(keywords or []),
        "exclude": list(exclude or []),
        "include": [t for t in include or [] if t not in (exclude or [])],
        "include_searched": stored.get("include_searched") or [],
        "candidates": stored.get("candidates") or [],
        "evaluations": stored.get("evaluations") or {},
        "matches": stored.get("matches") or {},
        "match_query": stored.get("match_query"),
        "keywords_searched": stored.get("keywords_searched") or [],
        "drive_times": stored.get("drive_times") or {},
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
        "include_searched": s.get("include_searched") or [],
        "drive_times": s.get("drive_times") or {},
    }


def recommend(
    prov: Providers,
    *,
    age_months: int,
    departure: dict,
    outing_date: str,
    departure_time: Optional[str] = None,
    travels_during_nap: bool = False,
    preference_text: Optional[str] = None,
    keywords: Optional[list[str]] = None,
    progress: Optional[Callable[[str], None]] = None,
) -> dict:
    """One-shot full recommendation (no conversation)."""
    out = run_pipeline(build_pipeline(prov), scope=SCOPE_FULL, departure=departure,
                       age_months=age_months, outing_date=outing_date, departure_time=departure_time,
                       travels_during_nap=travels_during_nap, preference_text=preference_text,
                       keywords=keywords)
    if progress:
        for m in out["messages"]:
            progress(m)
    for k in ("messages", "candidates", "evaluations", "matches", "match_query", "keywords_searched",
              "include_searched", "drive_times"):
        out.pop(k)
    return out
