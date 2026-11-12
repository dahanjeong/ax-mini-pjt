"""Supervisor: understands the conversation and delegates to the sub-agents.

Graph (LangGraph, in-memory checkpointer keyed by thread_id):

    START -> extract -> classify -+-> reset -> check_age ...
                                  +-> detail -> END            (stored card)
                                  +-> out_of_scope -> END
                                  +-> check_age -> check_nap -> check_departure -> check_date
                                        -> check_reference -> plan -> delegate -> END

- extract   slots (age, nap, departure, date) + optional preference / reference place
- check_*   the first missing or invalid required input sets `reply` and ends the turn;
            check_reference resolves the reference place of a "similar place" request
            (asks back when it is not found or ambiguous)
- plan      intent + re-run scope by comparing with the inputs of the last search
- delegate  runs the delegation pipeline (pipeline.py) with the providers passed in
            `config["configurable"]["providers"]`; without providers it stops at
            status=ready (conversation only)

Results of the last run (candidates, per-place evaluations, cards) are kept in the
session state so a narrower scope reuses them.
"""
from __future__ import annotations

import re
from dataclasses import dataclass
from datetime import date, datetime, timedelta
from typing import Any, Callable, Optional, TypedDict

from langgraph.checkpoint.memory import MemorySaver
from langgraph.graph import END, START, StateGraph

from .supervisor.intent import (
    _DATE_TOKENS, _NAP_TOKENS, MAX_AGE, MIN_AGE, NOW, SCOPE_FULL, _NonNumeric,
    classify_message, parse_age, parse_date, parse_departure, parse_nap, parse_preference, parse_time,
    parse_reference, plan_scope, preference_keywords, search_snapshot,
    EXCLUDE_VERB, is_excluded_keyword, is_kind_word, normalize_exclusion, parse_exclusions, parse_inclusions,
    strip_exclusions,
)
from .agents import preference as preference_agent
from .core.constants import DRIVE_CONFIRMED, DRIVE_UNVERIFIED
from .supervisor.pipeline import _STORED_KEYS, KST, build_pipeline, run_pipeline
from .tools import Providers

DEFAULT_FORECAST_DAYS = 10
MAX_CANDIDATES = 5

# geocode(query) -> list of {"name", "address", "lat", "lng"}; raises on API failure
GeocodeFn = Callable[[str], list[dict]]
# date_range(today) -> (start, end) covered by the forecast
DateRangeFn = Callable[[date], tuple[date, date]]
# optional LLM extractor(message, awaiting) -> partial dict:
#   age_months, departure_query, date_text, time_text, travels_during_nap,
#   preference_text, preference_keywords (list), reference_place
ExtractorFn = Callable[[str, Optional[str]], dict]

_SLOT_KEYS = ("baby_age_months", "travels_during_nap", "outing_date", "departure_time", "departure_query",
              "departure_location", "preference_text", "preference_keywords", "reference_place",
              "exclude_keywords", "include_keywords")
_RESULT_KEYS = ("candidates", "evaluations", "result_cards", "max_drive_hours", "radius_km",
                "radius_expanded", "failed_sources", "elapsed_s", "searched", "matches",
                "match_query", "keywords_searched", "include_searched", "drive_times", "preference_status",
                "reference",
                "reference_candidates", "reference_chosen")
_CANCEL = re.compile(r"없음|없어요|취소|됐어|괜찮|상관\s*없")

OUT_OF_SCOPE_REPLY = ("저는 아기와 함께 갈 나들이 장소 추천을 도와드려요. "
                      "아기 월령, 출발지, 날짜와 출발 시각을 알려주시면 장소를 찾아볼게요.")
INTENT_REPLY = {
    "new_search": "입력이 모두 확인됐어요. 추천 장소를 찾아볼게요!",
    "change_departure": "출발지가 바뀌어서 장소를 다시 찾아볼게요.",
    "change_age": "월령·낮잠 조건이 바뀌어서 이동 반경과 적합도를 다시 확인할게요.",
    "change_date": "날짜를 {date}로 바꿔서 날씨·미세먼지와 이동시간을 다시 확인할게요.",
    "change_time": "출발 시각을 {time}으로 바꿔서 이동시간만 다시 확인할게요.",
    "change_exclusion": "말씀하신 제외 조건({excl})에 해당하는 곳은 빼고 다시 골라 드릴게요.",
    "change_inclusion": "말씀하신 {incl} 장소를 목록에 넣어 다시 골라 드릴게요.",
    "change_preference": "말씀하신 취향을 반영해 순위를 다시 정할게요.",
    "similar_place": "'{ref}'와 비슷한 곳을 기준으로 순위를 다시 정할게요.",
    "no_change": "조건이 그대로라 이전 추천을 다시 보여드릴게요.",
}


def default_date_range(today: date) -> tuple[date, date]:
    return today, today + timedelta(days=DEFAULT_FORECAST_DAYS)


@dataclass
class Deps:
    geocode: GeocodeFn
    date_range: DateRangeFn = default_date_range
    today: Callable[[], date] = date.today
    now: Callable[[], datetime] = lambda: datetime.now(KST)    # KST wall clock ("지금 출발")
    extractor: Optional[ExtractorFn] = None


class ChatState(TypedDict, total=False):
    message: str
    # required inputs
    baby_age_months: Optional[int]
    departure_query: Optional[str]
    departure_location: Optional[dict]
    departure_candidates: list
    outing_date: Optional[str]
    departure_time: Optional[str]            # "HH:MM" (KST) leaving time, for the drive estimate
    travels_during_nap: Optional[bool]
    nap_asked: bool
    # optional inputs
    preference_text: Optional[str]
    preference_keywords: Optional[list]
    exclude_keywords: Optional[list]         # kinds / names left out of the list ("물놀이"), until reset
    include_keywords: Optional[list]         # kinds asked to be added to the list ("물놀이도 추천해주세요")
    reference_place: Optional[str]           # name as the user said it
    reference: Optional[dict]                # resolved: {"query", "name", "profile": [sentences]}
    reference_candidates: list               # ambiguous lookup: [{"name", "address", "raw"}]
    reference_chosen: Optional[dict]         # raw place picked from reference_candidates
    # turn bookkeeping
    awaiting: Optional[str]  # age | nap | departure | departure_choice | date | time | reference | reference_choice
    prev_awaiting: Optional[str]
    has_new_input: bool
    missing_inputs: list
    available_date_range: Optional[dict]
    notice: Optional[str]
    reply: Optional[str]
    status: str  # ask | ready
    intent: Optional[str]
    scope: Optional[str]
    detail_index: Optional[int]
    delegated: bool
    progress: list
    # last delegation results (kept across turns)
    searched: Optional[dict]
    candidates: list
    evaluations: dict
    result_cards: list
    max_drive_hours: Optional[float]
    radius_km: Optional[float]
    radius_expanded: bool
    failed_sources: list
    elapsed_s: Optional[float]
    matches: dict
    match_query: Optional[list]
    keywords_searched: list
    drive_times: dict
    include_searched: list
    preference_status: Optional[str]


_PIPELINES: dict[int, tuple[Providers, Any]] = {}


def _pipeline_for(prov: Providers) -> Any:
    hit = _PIPELINES.get(id(prov))
    if hit and hit[0] is prov:
        return hit[1]
    if len(_PIPELINES) > 32:
        _PIPELINES.clear()
    pipe = build_pipeline(prov)
    _PIPELINES[id(prov)] = (prov, pipe)
    return pipe


# ---------------------------------------------------------------- nodes

def _fmt(d: date) -> str:
    return d.isoformat()


_FAC_LABELS = {"nursing_room": "수유실", "stroller_rental": "유모차 대여", "parking": "주차"}


def _drive_text(c: dict) -> str:
    d = c.get("drive") or {}
    if d.get("status") == DRIVE_CONFIRMED and d.get("minutes") is not None:
        when = (d.get("departure_time") or "").replace("T", " ")
        return f"차로 약 {round(d['minutes'])}분" + (f" ({when} 출발 기준)" if when else "")
    return DRIVE_UNVERIFIED


def _card_text(i: int, c: dict) -> str:
    io = "실내" if c.get("indoor_outdoor") == "indoor" else "야외"
    fac = " · ".join(f"{_FAC_LABELS.get(k, k)}: {f.get('status')}" for k, f in (c.get("facilities") or {}).items())
    w = c.get("weather") or {}
    weather = w.get("status") or f"강수확률 {w.get('precip_prob_max')}% · 최고 {w.get('temp_max')}℃ / 최저 {w.get('temp_min')}℃"
    d = c.get("dust") or {}
    dust = d.get("status") or f"PM10 {d.get('pm10_grade')} · PM2.5 {d.get('pm25_grade')}"
    lines = [
        f"{i + 1}위 {c['name']} ({io}, 직선거리 {round(float(c['distance_km']), 1)}km, {_drive_text(c)}, "
        f"월령 적합도 {c.get('age_suitability')})",
        f"편의시설: {fac}",
        f"날씨: {weather}",
        f"미세먼지: {dust}",
    ]
    if c.get("warnings"):
        lines.append("주의: " + ", ".join(c["warnings"]))
    lines.append("후기 요약: " + " / ".join(c.get("review_summary") or []))
    for src in c.get("review_sources") or []:
        if isinstance(src, dict) and src.get("link"):
            lines.append(f"후기 출처: {src.get('title') or ''} ({src['link']})")
    m = c.get("preference_match")
    if m:
        ev = " / ".join(e["text"] for e in m.get("evidence") or []) or "근거 문장 없음"
        lines.append(f"취향 일치: {m['level']} (근거: {ev})")
    return "\n".join(lines)


def _excluded_places(text: str, llm_terms: list, cards: list[dict]) -> tuple[list[str], list[str]]:
    """Names of recommended places the user asks to leave out: a card name (or a 4+ letter
    part of it: "어린이대공원" -> 서울어린이대공원) mentioned together with an exclusion word,
    or named by the LLM extractor's exclude_keywords. Also returns the words of `text` that
    named them, so they are not read as a preference."""
    flat = re.sub(r"\s+", "", text)
    terms = [re.sub(r"\s+", "", str(t)) for t in llm_terms]
    has_verb = bool(EXCLUDE_VERB.search(text))
    words = [re.sub(r"(?:에서|이랑|을|를|은|는|가|도|에|랑)$", "", w) for w in re.findall(r"[가-힣A-Za-z0-9]+", text)]
    out: list[str] = []
    said: list[str] = []
    for c in cards:
        name = str(c.get("name") or "")
        key = re.sub(r"\s+", "", name)
        if len(key) < 2 or name in out:
            continue
        # a kind word ("물놀이장") means the kind, even when a card name contains it
        parts = [w for w in words if len(w) >= 4 and w in key and not is_kind_word(w)] if has_verb else []
        if (has_verb and key in flat) or parts or any(
                len(t) >= 3 and (t in key or key in t) and not is_kind_word(t) for t in terms):
            out.append(name)
            said += [name] + parts
    return out, said


def _pick(text: str, cands: list[dict]) -> Optional[dict]:
    m = re.fullmatch(r"\s*(\d+)\s*(?:번|번째)?\s*", text)
    if m and 1 <= int(m.group(1)) <= len(cands):
        return cands[int(m.group(1)) - 1]
    for c in cands:
        if c.get("name") and c["name"] in text or (c.get("address") and c["address"] in text):
            return c
    return None


def _providers(config) -> Optional[Providers]:
    return ((config or {}).get("configurable") or {}).get("providers")


def build_graph(deps: Deps):
    def _extract(state: ChatState) -> ChatState:
        text = (state.get("message") or "").strip()
        awaiting = state.get("awaiting")
        out: ChatState = {
            "reply": None, "notice": None, "status": "ask", "awaiting": None, "prev_awaiting": awaiting,
            "intent": None, "scope": None, "detail_index": None, "delegated": False, "progress": [],
        }
        today = deps.today()
        llm: dict = {}
        if deps.extractor is not None:
            try:
                llm = deps.extractor(text, awaiting) or {}
            except Exception:
                llm = {}

        # ---- age (always re-read: a new age in a later message replaces the old one)
        age: Optional[float] = None
        non_numeric = False
        if awaiting == "age" or state.get("baby_age_months") is None or re.search(r"개월|살|세\b|신생아", text):
            try:
                age = parse_age(text, awaiting)
            except _NonNumeric:
                non_numeric = True
            if age is None and not non_numeric and llm.get("age_months") is not None:
                try:
                    age = float(llm["age_months"])
                except (TypeError, ValueError):
                    non_numeric = True
        if non_numeric:
            out["baby_age_months"] = None
            out["notice"] = "월령은 숫자로 입력해 주세요. 0~72개월(만 6세까지) 범위만 가능해요."
        elif age is not None:
            if age < MIN_AGE or age > MAX_AGE:
                out["baby_age_months"] = None
                out["notice"] = f"월령은 {MIN_AGE}~{MAX_AGE}개월(만 6세까지)만 지원해요. 입력하신 값({age:g})은 범위를 벗어났어요."
            else:
                new_age = int(round(age))
                out["baby_age_months"] = new_age
                if new_age >= 24:
                    out["travels_during_nap"] = None
                    out["nap_asked"] = False

        # ---- nap
        if awaiting == "nap":
            nap = parse_nap(text)
            out["travels_during_nap"] = nap if nap is not None else False  # asked once; unclear -> no nap
        elif state.get("travels_during_nap") is None and not state.get("nap_asked"):
            nap_m = _NAP_TOKENS.search(text)
            if nap_m:
                nap = parse_nap(nap_m.group(0))
                if nap is None and llm.get("travels_during_nap") is not None:
                    nap = bool(llm["travels_during_nap"])
                if nap is None:
                    nap = True
                out["travels_during_nap"] = nap
                out["nap_asked"] = True

        # ---- date
        date_val: Optional[date] = None
        date_unparsed = False
        has_date_words = bool(_DATE_TOKENS.search(text))
        if has_date_words or awaiting == "date":
            date_val = parse_date(text, today)
            if date_val is None and llm.get("date_text"):
                date_val = parse_date(str(llm["date_text"]), today)
            if date_val is None and awaiting == "date":
                date_unparsed = True
        if date_val is not None:
            out["outing_date"] = _fmt(date_val)
        elif date_unparsed:
            out["outing_date"] = None
            out["notice"] = "날짜를 이해하지 못했어요. 예: 내일, 11월 15일, 2026-11-15"

        # ---- departure time
        time_val = parse_time(text, awaiting)
        if time_val is None and llm.get("time_text"):
            time_val = parse_time(str(llm["time_text"]), awaiting or "time")
        if time_val == NOW:
            time_val = deps.now().strftime("%H:%M")
        if time_val is not None:
            out["departure_time"] = time_val
        elif awaiting == "time":
            out["departure_time"] = None
            out["notice"] = "출발 시각을 이해하지 못했어요. 예: 오전 9시, 10시 반, 14:00"

        # ---- reference place being re-asked
        if awaiting == "reference":
            if _CANCEL.search(text):
                out.update({"reference_place": None, "reference": None, "reference_candidates": []})
            elif text:
                out.update({"reference_place": text.strip(" .!?"), "reference": None})
            return out
        if awaiting == "reference_choice":
            chosen = _pick(text, state.get("reference_candidates") or [])
            if chosen:
                out.update({"reference_chosen": chosen["raw"], "reference_candidates": []})
                return out
            if _CANCEL.search(text):
                out.update({"reference_place": None, "reference": None, "reference_candidates": []})
                return out

        # ---- exclusions ("물놀이장소는 빼주세요"): rules + LLM, kept until reset; never a preference.
        # A recommended place named with an exclusion word ("서울어린이대공원은 빼주세요") is left out
        # by its own name, not generalized to its kind ("공원").
        named, named_words = _excluded_places(text, llm.get("exclude_keywords") or [], state.get("result_cards") or [])
        new_excl = list(named)
        place_text = "".join(re.sub(r"\s+", "", n) for n in named)
        for t in parse_exclusions(text) + [normalize_exclusion(str(k)) for k in llm.get("exclude_keywords") or []
                                           if re.sub(r"\s+", "", str(k)) not in place_text]:
            if t and t not in new_excl and t not in place_text:
                new_excl.append(t)
        new_incl: list[str] = []
        for t in parse_inclusions(text) + [normalize_exclusion(str(k)) for k in llm.get("include_keywords") or []]:
            if t and t not in new_incl and t not in new_excl:
                new_incl.append(t)
        # a kind asked for again is no longer left out, and one left out is no longer asked for
        old_excl = list(state.get("exclude_keywords") or [])
        old_incl = list(state.get("include_keywords") or [])
        exclusions = [t for t in old_excl if t not in new_incl] + [t for t in new_excl if t not in old_excl]
        inclusions = [t for t in old_incl if t not in new_excl] + [t for t in new_incl if t not in old_incl]
        if exclusions != old_excl:
            out["exclude_keywords"] = exclusions
        if inclusions != old_incl:
            out["include_keywords"] = inclusions

        # ---- preference / reference place (optional; LLM first, rule fallback)
        pref = llm.get("preference_text") if isinstance(llm.get("preference_text"), str) else None
        ref = llm.get("reference_place") if isinstance(llm.get("reference_place"), str) else None
        kws = llm.get("preference_keywords") if isinstance(llm.get("preference_keywords"), list) else None
        def without_exclusions(s: str) -> str:
            for name in named_words:             # excluded place names are not preferences ("…대공원")
                s = s.replace(name, " ")
            return strip_exclusions(s)

        if not llm and awaiting not in ("departure", "departure_choice"):
            ref = parse_reference(text)
            pref = None if ref else parse_preference(without_exclusions(text))
        if pref and (new_excl or new_incl):      # "물놀이장소는 제외" / "물놀이 장소도" edit the list,
            rest = without_exclusions(pref)      # they are not a mood to rank everything by
            listed = new_excl + new_incl
            words = preference_keywords(rest)
            pref = rest if parse_preference(rest) and not (
                words and all(normalize_exclusion(w) in listed for w in words)) else None
        if ref and ref.strip() != state.get("reference_place"):
            out.update({"reference_place": ref.strip(), "reference": None, "reference_chosen": None})
        if pref:
            out["preference_text"] = pref.strip()
            kws = [str(k) for k in kws][:3] if kws else preference_keywords(pref)
            out["preference_keywords"] = [k for k in kws if not is_excluded_keyword(k, exclusions)]

        # ---- departure
        candidates = state.get("departure_candidates") or []
        if awaiting == "departure_choice" and candidates:
            chosen = None
            m = re.fullmatch(r"\s*(\d+)\s*(?:번|번째)?\s*", text)
            if m and 1 <= int(m.group(1)) <= len(candidates):
                chosen = candidates[int(m.group(1)) - 1]
            else:
                for c in candidates:
                    if c["name"] and c["name"] in text or (c.get("address") and c["address"] in text):
                        chosen = c
                        break
            if chosen:
                out["departure_location"] = chosen
                out["departure_candidates"] = []
                out["departure_query"] = chosen["name"]
                return out
        query = parse_departure(text, awaiting) or (
            llm.get("departure_query") if isinstance(llm.get("departure_query"), str) else None
        )
        if query:
            out["departure_query"] = query
            out["departure_location"] = None
            out["departure_candidates"] = []
        return out

    def extract(state: ChatState) -> ChatState:
        out = _extract(state)
        out["has_new_input"] = any(k in out for k in _SLOT_KEYS) or bool(out.get("notice"))
        return out

    def classify(state: ChatState) -> ChatState:
        names = [c["name"] for c in state.get("result_cards") or []]
        kind, idx = classify_message(
            (state.get("message") or "").strip(), awaiting=state.get("prev_awaiting"),
            card_names=names, has_new_input=bool(state.get("has_new_input")),
        )
        return {"intent": kind, "detail_index": idx}

    def route_message(state: ChatState) -> str:
        return {"reset": "reset", "place_detail": "detail", "out_of_scope": "out_of_scope"}.get(
            state.get("intent"), "check_age")

    def reset(state: ChatState) -> ChatState:
        cleared: ChatState = {k: None for k in _SLOT_KEYS}
        cleared.update({k: None for k in _RESULT_KEYS})
        cleared.update({"departure_candidates": [], "nap_asked": False, "candidates": [],
                        "evaluations": {}, "result_cards": [], "failed_sources": [],
                        "radius_expanded": False, "notice": "처음부터 다시 할게요."})
        return cleared

    def detail(state: ChatState) -> ChatState:
        i = state["detail_index"]
        # keep waiting for a pending answer (e.g. a re-asked date) after answering
        return {"status": "ready", "reply": _card_text(i, state["result_cards"][i]),
                "awaiting": state.get("prev_awaiting"), "notice": None}

    def out_of_scope(state: ChatState) -> ChatState:
        return {"reply": OUT_OF_SCOPE_REPLY, "missing_inputs": _missing(state)}

    def check_age(state: ChatState) -> ChatState:
        if state.get("baby_age_months") is None:
            return {
                "awaiting": "age",
                "missing_inputs": _missing(state, with_age=True),
                "reply": (state.get("notice") + " " if state.get("notice") else "") + "아기는 몇 개월인가요? (0~72개월)",
            }
        return {}

    def check_nap(state: ChatState) -> ChatState:
        age = state["baby_age_months"]
        if age < 24 and state.get("travels_during_nap") is None:
            return {
                "awaiting": "nap",
                "nap_asked": True,
                "missing_inputs": ["travels_during_nap"],
                "reply": "24개월 미만이라 낮잠 시간이 중요해요. 이동이 아기 낮잠 시간과 겹치나요? (네/아니요)",
            }
        return {}

    def check_departure(state: ChatState) -> ChatState:
        if state.get("departure_location"):
            return {}
        query = state.get("departure_query")
        if not query:
            return {
                "awaiting": "departure",
                "missing_inputs": ["departure_location"],
                "reply": "어디에서 출발하시나요? (예: 강남역, 서울시 송파구 잠실동)",
            }
        try:
            found = deps.geocode(query) or []
        except Exception:
            return {
                "awaiting": "departure",
                "departure_query": None,
                "missing_inputs": ["departure_location"],
                "notice": "출발지 검색에 실패했어요.",
                "reply": "출발지 검색에 실패했어요. 출발 위치를 다시 알려주세요.",
            }
        if not found:
            return {
                "awaiting": "departure",
                "departure_query": None,
                "missing_inputs": ["departure_location"],
                "notice": f"'{query}' 위치를 찾지 못했어요.",
                "reply": f"'{query}' 위치를 찾지 못했어요. 더 구체적인 장소명이나 주소로 다시 알려주세요.",
            }
        if len(found) == 1:
            return {"departure_location": found[0], "departure_candidates": []}
        cands = found[:MAX_CANDIDATES]
        lines = "\n".join(f"{i}. {c['name']} ({c.get('address', '')})" for i, c in enumerate(cands, 1))
        return {
            "awaiting": "departure_choice",
            "departure_candidates": cands,
            "missing_inputs": ["departure_location"],
            "notice": f"'{query}' 검색 결과가 여러 곳이에요.",
            "reply": f"'{query}' 검색 결과가 여러 곳이에요. 번호나 이름으로 골라 주세요.\n{lines}",
        }

    def check_date(state: ChatState) -> ChatState:
        raw = state.get("outing_date")
        today = deps.today()
        start, end = deps.date_range(today)
        rng = {"start": _fmt(start), "end": _fmt(end)}
        if not raw:
            return {
                "awaiting": "date",
                "missing_inputs": ["outing_date"],
                "available_date_range": rng,
                "notice": state.get("notice"),
                "reply": (state.get("notice") + " " if state.get("notice") else "")
                + f"언제 나들이를 가시나요? ({rng['start']} ~ {rng['end']} 사이 날짜)",
            }
        d = date.fromisoformat(raw)
        if d < today:
            return {
                "awaiting": "date",
                "outing_date": None,
                "missing_inputs": ["outing_date"],
                "available_date_range": rng,
                "notice": "지난 날짜는 추천할 수 없어요.",
                "reply": f"지난 날짜는 추천할 수 없어요. {rng['start']} ~ {rng['end']} 사이의 날짜를 다시 알려주세요.",
            }
        if d > end or d < start:
            return {
                "awaiting": "date",
                "outing_date": None,
                "missing_inputs": ["outing_date"],
                "available_date_range": rng,
                "notice": "해당 날짜는 아직 예보가 제공되지 않아요.",
                "reply": f"{raw} 날짜는 제공되지 않아요. 선택 가능한 날짜는 {rng['start']} ~ {rng['end']} 입니다. 날짜를 다시 알려주세요.",
            }
        return {"available_date_range": rng}

    def check_time(state: ChatState) -> ChatState:
        raw = state.get("departure_time")
        if not raw:
            return {
                "awaiting": "time",
                "missing_inputs": ["departure_time"],
                "notice": state.get("notice"),
                "reply": (state.get("notice") + " " if state.get("notice") else "")
                + "대략 언제쯤 출발할 예정이신가요? (예: 오전 9시, 10시 반, 오후 2시)",
            }
        now = deps.now()
        # "today" comes from deps.today() like every other date check (tests pin it)
        if state.get("outing_date") == _fmt(deps.today()) and raw < now.strftime("%H:%M"):
            return {
                "awaiting": "time",
                "departure_time": None,
                "missing_inputs": ["departure_time"],
                "notice": f"오늘 {raw}은(는) 이미 지난 시각이에요.",
                "reply": f"오늘 {raw}은(는) 이미 지난 시각이에요. 지금 이후 출발 시각을 알려주세요. (예: 지금 바로, 오후 2시)",
            }
        return {}

    def check_reference(state: ChatState, config) -> ChatState:
        name = state.get("reference_place")
        if not name:
            return {"reference": None} if state.get("reference") else {}
        ref = state.get("reference") or {}
        if ref.get("query") == name and ref.get("profile") is not None:
            return {}
        prov = _providers(config)
        if prov is None:                       # conversation only: nothing to look up
            return {}
        chosen = state.get("reference_chosen")
        if chosen:
            prof = preference_agent.reference_profile(prov, chosen)
            return {"reference": {"query": name, "name": prof["name"], "profile": prof["profile"]},
                    "reference_chosen": None}
        res = preference_agent.resolve_reference(prov, name)
        if res["status"] == "ok":
            return {"reference": {"query": name, "name": res["name"], "profile": res["profile"]}}
        if res["status"] == "not_found":
            return {
                "awaiting": "reference",
                "reference_place": None,
                "reference": None,
                "missing_inputs": ["reference_place"],
                "notice": f"기준 장소 '{name}'을(를) 찾지 못했어요.",
                "reply": f"기준 장소 '{name}'을(를) 찾지 못했어요. 정확한 장소 이름을 알려주시거나, "
                         "기준 장소 없이 추천받으려면 '없음'이라고 해 주세요.",
            }
        if res["status"] == "ambiguous":
            cands = res["candidates"]
            lines = "\n".join(f"{i}. {c['name']} ({c.get('address', '')})" for i, c in enumerate(cands, 1))
            return {
                "awaiting": "reference_choice",
                "reference_candidates": cands,
                "missing_inputs": ["reference_place"],
                "notice": f"'{name}' 검색 결과가 여러 곳이에요.",
                "reply": f"기준 장소 '{name}' 검색 결과가 여러 곳이에요. 번호나 이름으로 골라 주세요.\n{lines}",
            }
        # failed / unavailable: go on without the reference place
        return {"reference": None, "reference_place": None,
                "notice": "기준 장소 정보를 불러오지 못해 기준 장소 없이 추천할게요."}

    def plan(state: ChatState) -> ChatState:
        current = search_snapshot(state)
        intent, scope = plan_scope(state.get("searched"), current)
        if scope != SCOPE_FULL and not state.get("candidates"):
            intent, scope = "new_search", SCOPE_FULL
        reply = INTENT_REPLY[intent].format(date=state.get("outing_date"), ref=state.get("reference_place"),
                                            time=state.get("departure_time"),
                                            excl=", ".join(state.get("exclude_keywords") or []),
                                            incl="·".join(state.get("include_keywords") or []))
        return {
            "status": "ready",
            "intent": intent,
            "scope": scope,
            "awaiting": None,
            "missing_inputs": [],
            "notice": state.get("notice"),
            "reply": reply,
        }

    def delegate(state: ChatState, config) -> ChatState:
        prov = _providers(config)
        if prov is None:
            return {}
        out = run_pipeline(
            _pipeline_for(prov), scope=state["scope"],
            departure=state["departure_location"], age_months=state["baby_age_months"],
            outing_date=state["outing_date"], departure_time=state.get("departure_time"),
            travels_during_nap=bool(state.get("travels_during_nap")),
            preference_text=state.get("preference_text"), reference=state.get("reference"),
            keywords=state.get("preference_keywords") or [],
            exclude=state.get("exclude_keywords") or [],
            include=state.get("include_keywords") or [],
            stored={k: state.get(k) for k in _STORED_KEYS},
        )
        notice = " ".join(n for n in (state.get("notice"), out["notice"]) if n) or None
        return {
            "delegated": True,
            "progress": out["messages"],
            "notice": notice,
            "searched": search_snapshot(state),
            **{k: out[k] for k in _STORED_KEYS},
            **{k: out[k] for k in ("result_cards", "failed_sources", "elapsed_s")},
        }

    def route(next_node: str):
        return lambda state: END if state.get("reply") else next_node

    g = StateGraph(ChatState)
    for name, fn in (
        ("extract", extract), ("classify", classify), ("reset", reset), ("detail", detail),
        ("out_of_scope", out_of_scope), ("check_age", check_age), ("check_nap", check_nap),
        ("check_departure", check_departure), ("check_date", check_date), ("check_time", check_time),
        ("check_reference", check_reference), ("plan", plan),
        ("delegate", delegate),
    ):
        g.add_node(name, fn)
    g.add_edge(START, "extract")
    g.add_edge("extract", "classify")
    g.add_conditional_edges("classify", route_message, ["reset", "detail", "out_of_scope", "check_age"])
    g.add_edge("reset", "check_age")
    g.add_edge("detail", END)
    g.add_edge("out_of_scope", END)
    g.add_conditional_edges("check_age", route("check_nap"), {END: END, "check_nap": "check_nap"})
    g.add_conditional_edges("check_nap", route("check_departure"), {END: END, "check_departure": "check_departure"})
    g.add_conditional_edges("check_departure", route("check_date"), {END: END, "check_date": "check_date"})
    g.add_conditional_edges("check_date", route("check_time"), {END: END, "check_time": "check_time"})
    g.add_conditional_edges("check_time", route("check_reference"), {END: END, "check_reference": "check_reference"})
    g.add_conditional_edges("check_reference", route("plan"), {END: END, "plan": "plan"})
    g.add_edge("plan", "delegate")
    g.add_edge("delegate", END)
    return g.compile(checkpointer=MemorySaver())


def _missing(state: ChatState, with_age: bool = False) -> list:
    m = []
    if with_age or state.get("baby_age_months") is None:
        m.append("baby_age_months")
    if not state.get("departure_location"):
        m.append("departure_location")
    if not state.get("outing_date"):
        m.append("outing_date")
    if not state.get("departure_time"):
        m.append("departure_time")
    return m


def _invoke(graph: Any, thread_id: str, message: str, prov: Optional[Providers]) -> dict:
    cfg: dict = {"configurable": {"thread_id": thread_id}}
    if prov is not None:
        cfg["configurable"]["providers"] = prov
    return graph.invoke({"message": message}, config=cfg)


_INTERNAL_INTENTS = {"continue"}          # message class before the input checks; not part of the API


def _view(result: dict) -> dict:
    intent = result.get("intent")
    return {
        "reply": result.get("reply"),
        "status": result.get("status", "ask"),
        "intent": "ask" if not intent or intent in _INTERNAL_INTENTS else intent,
        "notice": result.get("notice"),
        "missing_inputs": result.get("missing_inputs", []),
        "candidates": result.get("departure_candidates") or [],
        "available_date_range": result.get("available_date_range"),
        "baby_age_months": result.get("baby_age_months"),
        "travels_during_nap": result.get("travels_during_nap"),
        "departure_location": result.get("departure_location"),
        "outing_date": result.get("outing_date"),
        "departure_time": result.get("departure_time"),
        "exclude_keywords": list(result.get("exclude_keywords") or []),
        "include_keywords": list(result.get("include_keywords") or []),
        "preference_text": result.get("preference_text"),
        "reference_place": result.get("reference_place"),
        "reference_candidates": [{"name": c.get("name"), "address": c.get("address")}
                                 for c in result.get("reference_candidates") or []],
    }


def chat_turn(graph: Any, thread_id: str, message: str) -> dict:
    """Run one user turn (conversation only) and return the public view of the state."""
    return _view(_invoke(graph, thread_id, message, None))


def recommendation_turn(graph: Any, thread_id: str, message: str, prov: Providers) -> dict:
    """One chat turn with delegation: ask-back, or re-run the sub-agents in the planned scope."""
    result = _invoke(graph, thread_id, message, prov)
    view = _view(result)
    messages: list[str] = [view["reply"]] if view.get("reply") else []
    if result.get("delegated"):
        messages += list(result.get("progress") or [])
        for k in ("result_cards", "max_drive_hours", "radius_km", "radius_expanded",
                  "failed_sources", "elapsed_s", "preference_status"):
            view[k] = result.get(k)
    view["messages"] = messages
    return view
