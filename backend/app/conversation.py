"""Ask-back conversation flow, managed by LangGraph (in-memory checkpointer only).

Each user turn runs: extract -> check_age -> check_nap -> check_departure ->
check_date -> ready. The first check that still needs something sets `reply`
and ends the turn. State lives in the MemorySaver keyed by thread_id.
"""
from __future__ import annotations

import re
from dataclasses import dataclass, field
from datetime import date, datetime, timedelta
from typing import Any, Callable, Optional, TypedDict

from langgraph.checkpoint.memory import MemorySaver
from langgraph.graph import END, START, StateGraph

MIN_AGE, MAX_AGE = 0, 72
DEFAULT_FORECAST_DAYS = 10
MAX_CANDIDATES = 5

# geocode(query) -> list of {"name", "address", "lat", "lng"}; raises on API failure
GeocodeFn = Callable[[str], list[dict]]
# date_range(today) -> (start, end) covered by the forecast
DateRangeFn = Callable[[date], tuple[date, date]]
# optional LLM extractor(message, awaiting) -> partial dict (age_months, departure_query, date_text, travels_during_nap)
ExtractorFn = Callable[[str, Optional[str]], dict]


def default_date_range(today: date) -> tuple[date, date]:
    return today, today + timedelta(days=DEFAULT_FORECAST_DAYS)


@dataclass
class Deps:
    geocode: GeocodeFn
    date_range: DateRangeFn = default_date_range
    today: Callable[[], date] = date.today
    extractor: Optional[ExtractorFn] = None


class ChatState(TypedDict, total=False):
    message: str
    baby_age_months: Optional[int]
    departure_query: Optional[str]
    departure_location: Optional[dict]
    departure_candidates: list
    outing_date: Optional[str]
    travels_during_nap: Optional[bool]
    nap_asked: bool
    awaiting: Optional[str]  # age | nap | departure | departure_choice | date
    missing_inputs: list
    available_date_range: Optional[dict]
    notice: Optional[str]
    reply: Optional[str]
    status: str  # ask | ready


# ---------------------------------------------------------------- parsing

_NUM = r"-?\d+(?:\.\d+)?"
_WEEKDAYS = {"월": 0, "화": 1, "수": 2, "목": 3, "금": 4, "토": 5, "일": 6}


class _NonNumeric(Exception):
    pass


def parse_age(text: str, awaiting: Optional[str]) -> Optional[float]:
    """Return age in months, None when absent. Raises _NonNumeric for a given but non-numeric age."""
    m = re.search(rf"({_NUM})\s*(?:개월|달)", text)
    if m:
        return float(m.group(1))
    m = re.search(rf"({_NUM})\s*(?:살|세)(?![가-힣]*\s*(?:이상))", text)
    if m:
        return float(m.group(1)) * 12
    if "신생아" in text:
        return 0.0
    if awaiting == "age":
        m = re.fullmatch(rf"\s*({_NUM})\s*", text)
        if m:
            return float(m.group(1))
        raise _NonNumeric
    if re.search(r"(?:개월|월령)", text) and not re.search(r"\d", text):
        raise _NonNumeric
    return None


def _weekday_date(today: date, wd: int, week_offset: Optional[int]) -> date:
    if week_offset is None:
        delta = (wd - today.weekday()) % 7
        return today + timedelta(days=delta)
    monday = today - timedelta(days=today.weekday()) + timedelta(weeks=week_offset)
    return monday + timedelta(days=wd)


def parse_date(text: str, today: date) -> Optional[date]:
    m = re.search(r"(\d{4})\s*[-./년]\s*(\d{1,2})\s*[-./월]\s*(\d{1,2})", text)
    if m:
        try:
            return date(int(m.group(1)), int(m.group(2)), int(m.group(3)))
        except ValueError:
            return None
    m = re.search(r"(\d{1,2})\s*월\s*(\d{1,2})\s*일?", text)
    if m:
        try:
            return date(today.year, int(m.group(1)), int(m.group(2)))
        except ValueError:
            return None
    m = re.search(r"(\d+)\s*일\s*(?:뒤|후)", text)
    if m:
        return today + timedelta(days=int(m.group(1)))
    for word, delta in (("글피", 3), ("모레", 2), ("내일", 1), ("오늘", 0), ("어제", -1), ("그제", -2), ("그저께", -2)):
        if word in text:
            return today + timedelta(days=delta)
    m = re.search(r"(다음\s*주|담주|이번\s*주|금주)?\s*([월화수목금토일])요일", text)
    if m:
        prefix = m.group(1) or ""
        off = 1 if ("다음" in prefix or "담주" in prefix) else (0 if prefix else None)
        return _weekday_date(today, _WEEKDAYS[m.group(2)], off)
    m = re.search(r"(다음\s*주|이번\s*주)?\s*주말", text)
    if m:
        off = 1 if m.group(1) and "다음" in m.group(1) else (0 if m.group(1) else None)
        return _weekday_date(today, 5, off)
    return None


_DATE_TOKENS = re.compile(
    r"\d{4}\s*[-./년]\s*\d{1,2}\s*[-./월]\s*\d{1,2}\s*일?|\d{1,2}\s*월\s*\d{1,2}\s*일?|\d+\s*일\s*(?:뒤|후)|"
    r"글피|모레|내일|오늘|어제|그제|그저께|(?:다음\s*주|담주|이번\s*주|금주)?\s*[월화수목금토일]요일|"
    r"(?:다음\s*주|이번\s*주)?\s*주말|다음\s*주|이번\s*주"
)
_AGE_TOKENS = re.compile(rf"{_NUM}\s*(?:개월|달|살|세)(?:인|된)?|(?:신생아|아기|아이|애기|월령)(?:랑|와|과|하고|는|가|도)?")
_NAP_TOKENS = re.compile(r"낮잠[^,.]*")
_TAIL = re.compile(r"(?:에서|서)?\s*(?:출발(?:할게요|해요|합니다|할래요|할 예정이에요|할 거예요)?|갈게요|가요|갈래요|예요|이에요|입니다|이요|요|에요)?[.!?\s]*$")


def parse_nap(text: str) -> Optional[bool]:
    t = text.strip()
    if re.search(r"(아니|안\s*(?:자|해)|없|괜찮|상관\s*없|피해|피할|아닌|no\b)", t, re.I):
        return False
    if re.search(r"(네|넵|예|응|어|맞|그래|있|겹|낮잠\s*시간에|yes\b)", t, re.I):
        return True
    return None


def parse_departure(text: str, awaiting: Optional[str]) -> Optional[str]:
    cleaned = _NAP_TOKENS.sub(" ", _AGE_TOKENS.sub(" ", _DATE_TOKENS.sub(" ", text)))
    m = re.search(r"출발지\s*(?:는|은|:)?\s*([^\s,.]+(?: [^\s,.]+)?)", cleaned)
    if m:
        cand = re.sub(r"(?:이에요|예요|입니다|이요|에서)$", "", m.group(1).strip())
        if cand:
            return cand
    m = re.search(r"([^\s,.]+(?: [^\s,.]+)?)\s*에서", cleaned)
    if m:
        return m.group(1).strip()
    if awaiting in ("departure", "departure_choice"):
        cand = _TAIL.sub("", cleaned).strip(" ,.!?")
        cand = re.sub(r"^(?:저는|제가|우리는|출발지는|에서)\s*", "", cand).strip()
        return cand or None
    return None


# ---------------------------------------------------------------- nodes

def _fmt(d: date) -> str:
    return d.isoformat()


def build_graph(deps: Deps):
    def extract(state: ChatState) -> ChatState:
        text = (state.get("message") or "").strip()
        awaiting = state.get("awaiting")
        out: ChatState = {"reply": None, "notice": None, "status": "ask", "awaiting": None}
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

    def ready(state: ChatState) -> ChatState:
        return {
            "status": "ready",
            "awaiting": None,
            "missing_inputs": [],
            "notice": None,
            "reply": "입력이 모두 확인됐어요. 추천 장소를 찾아볼게요!",
        }

    def route(next_node: str):
        return lambda state: END if state.get("reply") else next_node

    g = StateGraph(ChatState)
    for name, fn in (
        ("extract", extract), ("check_age", check_age), ("check_nap", check_nap),
        ("check_departure", check_departure), ("check_date", check_date), ("ready", ready),
    ):
        g.add_node(name, fn)
    g.add_edge(START, "extract")
    g.add_edge("extract", "check_age")
    g.add_conditional_edges("check_age", route("check_nap"), {END: END, "check_nap": "check_nap"})
    g.add_conditional_edges("check_nap", route("check_departure"), {END: END, "check_departure": "check_departure"})
    g.add_conditional_edges("check_departure", route("check_date"), {END: END, "check_date": "check_date"})
    g.add_conditional_edges("check_date", route("ready"), {END: END, "ready": "ready"})
    g.add_edge("ready", END)
    return g.compile(checkpointer=MemorySaver())


def _missing(state: ChatState, with_age: bool = False) -> list:
    m = []
    if with_age or state.get("baby_age_months") is None:
        m.append("baby_age_months")
    if not state.get("departure_location"):
        m.append("departure_location")
    if not state.get("outing_date"):
        m.append("outing_date")
    return m


def chat_turn(graph: Any, thread_id: str, message: str) -> dict:
    """Run one user turn and return the public view of the conversation state."""
    result = graph.invoke({"message": message}, config={"configurable": {"thread_id": thread_id}})
    return {
        "reply": result.get("reply"),
        "status": result.get("status", "ask"),
        "notice": result.get("notice"),
        "missing_inputs": result.get("missing_inputs", []),
        "candidates": result.get("departure_candidates") or [],
        "available_date_range": result.get("available_date_range"),
        "baby_age_months": result.get("baby_age_months"),
        "travels_during_nap": result.get("travels_during_nap"),
        "departure_location": result.get("departure_location"),
        "outing_date": result.get("outing_date"),
    }
