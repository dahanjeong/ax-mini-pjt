"""Intent: input extraction and intent judgement for the supervisor (pure functions).

- parse_*            rule-based slot extraction (age, date, departure time, nap, departure)
- parse_preference / parse_reference
                     rule fallback for the optional preference sentence and the
                     reference place of a "similar place" request (the LLM
                     extractor is preferred when configured)
- classify_message   reset / place_detail / privacy / out_of_scope / continue
- plan_scope         which sub-agents must re-run, from the inputs used by the
                     last search vs. the current inputs
"""
from __future__ import annotations

import re
from datetime import date, timedelta
from typing import Optional

from ..agents.candidates import EXCLUDE_GROUPS, EXCLUDE_SETTINGS, exclusion_words

MIN_AGE, MAX_AGE = 0, 72

# ---------------------------------------------------------------- slots

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
    m = re.search(r"(다음|담|이번|금)?\s*(?:주\s*)?주말", text)
    if m:
        # "다음 주말" = next week's Saturday; "이번 주말" / "주말" = the coming Saturday
        return _weekday_date(today, 5, 1 if m.group(1) in ("다음", "담") else None)
    return None


# ---- departure time ("HH:MM")

NOW = "now"                      # parse_time result for "지금 / 바로": resolved by the supervisor
# vague answers to the departure-time question -> a representative time
_VAGUE_TIMES = (("새벽", "06:00"), ("아침", "09:00"), ("오전", "10:00"), ("점심", "12:00"), ("낮", "13:00"),
                ("오후", "14:00"), ("저녁", "18:00"))
_TIME_PERIOD = r"(오전|오후|아침|낮|점심|저녁|밤|새벽)"
_TIME_HM = re.compile(rf"(?:{_TIME_PERIOD}\s*)?(\d{{1,2}})\s*시(?!간)\s*(?:(\d{{1,2}})\s*분|(반))?")
_TIME_COLON = re.compile(r"(?<![\d.])([01]?\d|2[0-3])\s*:\s*([0-5]\d)(?!\d)")
_TIME_NOW = re.compile(r"지금|바로|당장|곧")
_TIME_TOKENS = re.compile(rf"(?:{_TIME_PERIOD}\s*)?\d{{1,2}}\s*시(?!간)\s*(?:\d{{1,2}}\s*분|반)?(?:쯤|경|에)?|"
                          r"(?<![\d.])(?:[01]?\d|2[0-3])\s*:\s*[0-5]\d(?!\d)")


def parse_time(text: str, awaiting: Optional[str] = None) -> Optional[str]:
    """Departure time as "HH:MM", NOW for "지금 / 바로", None when absent or unclear.
    A bare 1~6시 means the afternoon (13~18시: nobody leaves with a baby at 3 a.m.).
    Vague words ("아침", "오후") count only as the answer to the departure-time question."""
    m = _TIME_COLON.search(text)
    if m:
        return f"{int(m.group(1)):02d}:{m.group(2)}"
    m = _TIME_HM.search(text)
    if m:
        period, h = m.group(1), int(m.group(2))
        minute = 30 if m.group(4) else int(m.group(3) or 0)
        if h > 24 or minute > 59:
            return None
        if period in ("오후", "저녁", "밤") and h < 12:
            h += 12
        elif period in ("오전", "아침", "새벽", "밤") and h == 12:
            h = 0
        elif period is None and 1 <= h <= 6:
            h += 12
        if period == "낮" and 1 <= h <= 6:
            h += 12
        return f"{h % 24:02d}:{minute:02d}"
    if awaiting == "time":
        if _TIME_NOW.search(text):
            return NOW
        for word, hhmm in _VAGUE_TIMES:
            if word in text:
                return hhmm
    elif re.search(r"(?:지금|바로|당장)\s*(?:바로\s*)?출발", text):
        return NOW
    return None


_DATE_TOKENS = re.compile(
    r"\d{4}\s*[-./년]\s*\d{1,2}\s*[-./월]\s*\d{1,2}\s*일?|\d{1,2}\s*월\s*\d{1,2}\s*일?|\d+\s*일\s*(?:뒤|후)|"
    r"글피|모레|내일|오늘|어제|그제|그저께|(?:(?:다음\s*주|담주|이번\s*주|금주|다음|이번)\s*)?[월화수목금토일]요일|"
    # "주말" before the bare "이번 주": otherwise "이번 주말" loses only "이번 주" and leaves "말"
    r"(?:(?:다음|담|이번|금)\s*)?(?:주\s*)?주말|다음\s*주|담주|이번\s*주|금주"
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


# particles left behind once date / age words are removed ("토요일에 강남역에서" -> "에 강남역에서")
_LEFTOVER_PARTICLES = {"에", "에는", "엔", "이고", "이며", "고", "은", "는", "이", "가", "을", "를",
                       "랑", "이랑", "와", "과", "하고", "도", "부터", "에서", "인데", "인데요"}


def _drop_leading_particles(cand: str) -> str:
    words = cand.split()
    while words and words[0] in _LEFTOVER_PARTICLES:
        words.pop(0)
    return " ".join(words)


def parse_departure(text: str, awaiting: Optional[str]) -> Optional[str]:
    cleaned = _NAP_TOKENS.sub(" ", _AGE_TOKENS.sub(" ", _DATE_TOKENS.sub(" ", _TIME_TOKENS.sub(" ", text))))
    m = re.search(r"출발지\s*(?:는|은|:)?\s*([^\s,.]+(?: [^\s,.]+)?)", cleaned)
    if m:
        cand = re.sub(r"(?:이에요|예요|입니다|이요|에서)$", "", m.group(1).strip())
        if cand:
            return cand
    m = re.search(r"([^\s,.]+(?: [^\s,.]+)?)\s*에서", cleaned)
    if m:
        cand = _drop_leading_particles(m.group(1).strip())
        if cand:
            return cand
    if awaiting in ("departure", "departure_choice"):
        cand = _TAIL.sub("", cleaned).strip(" ,.!?")
        cand = re.sub(r"^(?:저는|제가|우리는|출발지는|에서)\s*", "", cand).strip()
        return cand or None
    return None



# ---------------------------------------------------------------- preference

_PREF_WORDS = re.compile(
    r"위주|느낌|분위기|조용한|한적한|붐비지|뛰어놀|뛰어 놀|물놀이|모래|숲|자연|동물|체험|전시|"
    r"실내|야외|그늘|넓은|산책|공원|놀이터|박물관|미술관|키즈카페|바다|호수"
)
_REFERENCE = re.compile(
    r"(?:전에|지난번에?|예전에)?\s*(?:갔던\s*)?([가-힣A-Za-z0-9]+(?:\s[가-힣A-Za-z0-9]+)?)\s*"
    r"(?:이|가|은|는|도)?\s*(?:좋았는데|좋았어서|좋았어요|좋았던|처럼|같은\s*(?:곳|데|장소)|이랑\s*비슷|랑\s*비슷|와\s*비슷|과\s*비슷)"
)


# ---------------------------------------------------------------- exclusions

_EXCLUDE_VERB = (r"(?:빼\s*(?:주세요|줘요?|줄래요?|주실래요?|고|면)|제외(?:해\s*(?:주세요|줘요?)|하고|요)?|"
                 r"말고|싫어(?:요)?|별로(?:예요|에요|야)?|안\s*(?:갈래요?|가고\s*싶|좋아해요?)|원하지\s*않)")
EXCLUDE_VERB = re.compile(_EXCLUDE_VERB)
_EXCLUDE = re.compile(rf"((?:[가-힣A-Za-z0-9]+[\s,]*){{1,3}}?)\s*{_EXCLUDE_VERB}")
_KIND_WORDS = tuple(w for words in EXCLUDE_GROUPS.values() for w in words)


_KIND_SUFFIX = re.compile(r"(?:장소|시설|종류|쪽|류|곳|들)+$")


def is_kind_word(word: str) -> bool:
    """'물놀이장', '워터파크', '키즈카페 장소' are kinds of place; '어린이대공원' is a place name."""
    w = _KIND_SUFFIX.sub("", re.sub(r"\s+", "", word or ""))
    return bool(w) and (w in EXCLUDE_GROUPS or w in EXCLUDE_SETTINGS or w in _KIND_WORDS
                        or w.endswith("장") and w[:-1] in _KIND_WORDS)


def normalize_exclusion(token: str) -> Optional[str]:
    """'물놀이장소는' -> '물놀이', '워터파크' -> '물놀이', '야외는' -> '야외';
    None when the token is not a kind of place ('낮잠', '강남역')."""
    t = re.sub(r"\s+", "", token or "")
    if len(t) < 2:
        return None
    for group, words in EXCLUDE_GROUPS.items():
        if group in t or any(w in t for w in words):
            return group
    for setting in EXCLUDE_SETTINGS:
        if t.startswith(setting):
            return setting
    m = _PREF_WORDS.search(t)
    if m and m.group(0) not in ("위주", "느낌", "분위기", "조용한", "한적한", "넓은"):
        return m.group(0)
    return None


# "물놀이 장소도 추천해주세요", "키즈카페도 넣어줘", "물놀이장 추가해주세요"
_INCLUDE = re.compile(
    r"((?:[가-힣A-Za-z0-9]+[\s,]*){1,3}?)\s*(?:"
    r"(?:도|까지)\s*(?:추천|넣|포함|보여|알려|찾아|있으면)|"
    r"(?:을|를)?\s*(?:추가|포함)\s*(?:해|시켜|하여|해서|좀))")


def _exclusion_matches(text: str, pattern: re.Pattern = _EXCLUDE):
    """(match, terms) for each exclusion (or, with `_INCLUDE`, inclusion) clause in `text`
    that names a kind of place."""
    for m in pattern.finditer(text or ""):
        tokens = re.split(r"[\s,]+|(?<=[가-힣])(?:이랑|랑|하고)(?=\s|$)", m.group(1))
        terms = [t for t in (normalize_exclusion(tok) for tok in tokens if tok) if t]
        if terms:
            yield m, terms


def parse_exclusions(text: str) -> list[str]:
    """Kinds of place the user wants left out: '물놀이장소는 빼주세요' -> ['물놀이']."""
    out: list[str] = []
    for _, terms in _exclusion_matches(text):
        out += [t for t in terms if t not in out]
    return out


def parse_inclusions(text: str) -> list[str]:
    """Kinds of place the user wants added to the list: '물놀이 장소도 추천해주세요' -> ['물놀이']."""
    out: list[str] = []
    for _, terms in _exclusion_matches(text, _INCLUDE):
        out += [t for t in terms if t not in out]
    return out


def strip_exclusions(text: str) -> str:
    """The text without its exclusion / inclusion clauses (what is left may still be a preference)."""
    spans = [m for pattern in (_EXCLUDE, _INCLUDE) for m, _ in _exclusion_matches(text, pattern)]
    for m in sorted(spans, key=lambda m: m.start(), reverse=True):
        text = text[:m.start()] + " " + text[m.end():]
    return re.sub(r"\s+", " ", text).strip(" ,.!?")


def is_excluded_keyword(keyword: str, exclusions: list[str]) -> bool:
    k = re.sub(r"\s+", "", keyword or "")
    return any(w in k or k in w for t in exclusions or [] for w in exclusion_words(t))


def parse_reference(text: str) -> Optional[str]:
    """Reference place of a 'similar place' request, e.g. '서울숲 좋았는데 비슷한 곳'."""
    if not re.search(r"비슷|같은\s*(?:곳|데|장소)|처럼", text):
        return None
    m = _REFERENCE.search(text)
    if not m:
        return None
    name = m.group(1).strip()
    if name in ("거기", "그곳", "여기", "이곳", "저번", "아기", "아이"):
        return None
    # "실내 같은 곳", "키즈카페 같은 곳": a kind or mood of place, not one place to compare with
    if is_kind_word(name) or _PREF_WORDS.fullmatch(re.sub(r"\s+", "", name)):
        return None
    return name


def strip_reference(text: str) -> str:
    """The text without its 'similar place' clause ('서울숲 같은 곳이면 좋겠어요' -> '이면 좋겠어요')."""
    return re.sub(r"\s+", " ", _REFERENCE.sub(" ", text or "")).strip(" ,.!?")


def preference_keywords(text: str, limit: int = 3) -> list[str]:
    """Search keywords inside a preference sentence (rule fallback for the LLM extractor)."""
    out: list[str] = []
    for m in _PREF_WORDS.finditer(text or ""):
        w = m.group(0)
        if w not in out and w not in ("위주", "느낌", "분위기"):
            out.append(w)
    return out[:limit]


def parse_preference(text: str) -> Optional[str]:
    """The preference sentence itself (slot words removed), when it mentions a mood/feature."""
    if not _PREF_WORDS.search(text):
        return None
    cleaned = _NAP_TOKENS.sub(" ", _AGE_TOKENS.sub(" ", _DATE_TOKENS.sub(" ", _TIME_TOKENS.sub(" ", text))))
    cleaned = re.sub(r"[^\s,.]+\s*에서\s*(?:출발[가-힣]*)?", " ", cleaned)
    cleaned = re.sub(r"\s+", " ", cleaned).strip(" ,.!?")
    return cleaned or None


# ---------------------------------------------------------------- message class

_CHOICE_AWAITS = ("departure_choice", "reference_choice")
_RESET = re.compile(r"처음부터|다시\s*시작|새로\s*시작|리셋|초기화")
_ORDINALS = {"첫": 1, "두": 2, "세": 3, "네": 4, "다섯": 5}
_DETAIL_WORDS = re.compile(r"자세히|더\s*알려|어때|어떤\s*곳|정보|설명|궁금")
# someone else's data ("다른 사용자들이 어디 갔는지 대화 기록이랑 출발지를 보여줘")
_OTHERS = re.compile(r"(?:다른|타)\s*(?:사용자|유저|사람|회원|이용자|고객|분|가족|엄마|아빠|부모)|남의|남들")
# not "어디" alone: "다른 분들이 많이 가는 곳 어디예요?" asks for popular places, not for data
_PERSONAL_DATA = re.compile(r"기록|내역|로그|히스토리|대화|채팅|출발지|위치|주소|월령|개인\s*정보")
_IN_SCOPE = re.compile(r"나들이|놀러|외출|여행|산책|갈\s*(?:곳|데|만한)|가볼|갈래|가요|가려|장소|어디|출발|비슷|\d\s*시(?!간)|빼|제외|말고")


def detail_index(text: str, card_names: list[str]) -> Optional[int]:
    """0-based index of the result card the user asks about, if any."""
    if not card_names:
        return None
    m = re.search(r"(\d+)\s*(?:번째|번|위)", text)
    if m and 1 <= int(m.group(1)) <= len(card_names):
        return int(m.group(1)) - 1
    m = re.search(r"(첫|두|세|네|다섯)\s*(?:번째)", text)
    if m and _ORDINALS[m.group(1)] <= len(card_names):
        return _ORDINALS[m.group(1)] - 1
    if _DETAIL_WORDS.search(text):
        for i, n in enumerate(card_names):
            if n and n in text:
                return i
    return None


def classify_message(text: str, *, awaiting: Optional[str], card_names: list[str],
                     has_new_input: bool) -> tuple[str, Optional[int]]:
    """Return (kind, detail_index); kind is reset | place_detail | privacy | out_of_scope | continue.

    While the supervisor is waiting for an answer (`awaiting`), a message is an answer
    attempt and goes on to the input checks, unless it clearly asks about a stored
    result card (not while choosing among departure candidates, where "2번" is a choice).
    A request for other users' conversations or inputs is refused (`privacy`) even when
    it mentions an outing.
    """
    if _RESET.search(text):
        return "reset", None
    if _OTHERS.search(text) and _PERSONAL_DATA.search(text):
        return "privacy", None
    idx = detail_index(text, card_names)
    if idx is not None and awaiting not in _CHOICE_AWAITS and (awaiting or not has_new_input):
        # stored cards stay answerable even while an invalid change is being re-asked
        return "place_detail", idx
    if awaiting:
        return "continue", None
    if not has_new_input and not _IN_SCOPE.search(text):
        return "out_of_scope", None
    return "continue", None


# ---------------------------------------------------------------- re-run scope

SCOPE_FULL = "full"            # place search + environment + review + rank
SCOPE_ENVIRONMENT = "environment"  # environment for stored candidates + rank
SCOPE_RERANK = "rerank"        # rank stored results only (preference changes)


def search_snapshot(state: dict) -> dict:
    """The inputs a search depends on, to compare against on the next turn."""
    dep = state.get("departure_location") or {}
    return {
        "baby_age_months": state.get("baby_age_months"),
        "travels_during_nap": bool(state.get("travels_during_nap")),
        "departure": [dep.get("lat"), dep.get("lng")],
        "outing_date": state.get("outing_date"),
        "departure_time": state.get("departure_time"),
        "exclude_keywords": list(state.get("exclude_keywords") or []),
        "include_keywords": list(state.get("include_keywords") or []),
        "preference_text": state.get("preference_text"),
        "reference_place": state.get("reference_place"),
    }


def plan_scope(searched: Optional[dict], current: dict) -> tuple[str, str]:
    """Return (intent, scope) from the last searched inputs and the current ones."""
    if not searched:
        return "new_search", SCOPE_FULL
    if list(current["departure"]) != list(searched["departure"]):
        return "change_departure", SCOPE_FULL
    if (current["baby_age_months"] != searched["baby_age_months"]
            or current["travels_during_nap"] != searched["travels_during_nap"]):
        return "change_age", SCOPE_FULL
    if current["outing_date"] != searched["outing_date"]:
        return "change_date", SCOPE_ENVIRONMENT
    if current.get("departure_time") != searched.get("departure_time"):
        return "change_time", SCOPE_RERANK          # only the drive times change
    if current.get("exclude_keywords", []) != searched.get("exclude_keywords", []):
        return "change_exclusion", SCOPE_RERANK     # stored candidates filtered (widened if too few)
    if current.get("include_keywords", []) != searched.get("include_keywords", []):
        return "change_inclusion", SCOPE_RERANK     # kind added to the list (searched if not a candidate)
    if current["reference_place"] and current["reference_place"] != searched["reference_place"]:
        return "similar_place", SCOPE_RERANK
    if current["preference_text"] != searched["preference_text"]:
        return "change_preference", SCOPE_RERANK
    return "no_change", SCOPE_RERANK
