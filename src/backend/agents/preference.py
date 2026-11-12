"""Preference matching (RAG): how well each candidate fits the user's preference
sentence and/or a reference place ("서울숲 같은 곳").

    START -> build_query -> build_profiles -> index -> score -> END

- build_query     query sentences = the preference sentence + the reference place profile
- build_profiles  per candidate: category, TourAPI description, indoor/outdoor,
                  facilities, review summary -> sentence documents (retriever.Document)
- index           one embedding call for all documents and queries -> VectorStore
- score           per candidate, the best-matching sentences -> level 높음/보통/낮음
                  and up to 2 evidence sentences (doc_id + text)

`resolve_reference` (used by the supervisor before delegating) finds the reference
place by name and builds its profile; the supervisor asks back when it is not
found or ambiguous.

Review text is untrusted: it is only embedded and quoted as evidence, never
followed as instructions.
"""
from __future__ import annotations

import operator
import re
from typing import Annotated, Any, Optional, TypedDict

from langgraph.graph import END, START, StateGraph

from ..core.constants import FAIL, NO_REVIEW
from ..core.geo import haversine_km
from ..retriever import Document, VectorStore, split_sentences
from ..tools import Providers, call_api, guarded
from .candidates import _norm, kind_of, place_key

# Titan v2 cosine similarity, measured on Korean place sentences (2026-11-12): related pairs
# ("동물 체험" ~ "동물 먹이주기 체험", "숲 속 산책로" ~ "숲길·잔디밭") score 0.37~0.46,
# unrelated ones mostly below 0.25.
HIGH = 0.40          # cosine similarity for 높음
MID = 0.30           # cosine similarity for 보통 (and the minimum for evidence)
# An indoor / outdoor wish is decided by the indoor/outdoor judgement, not by similarity:
# "비 와도 괜찮은 곳" ~ "실내 장소입니다" is only 0.10.
_WANTS_INDOOR = re.compile(r"실내|비\s*(?:가|이)?\s*(?:와도|오면|오는|올\s*때)|우천|궂은\s*날|추운\s*날|더운\s*날")
_WANTS_OUTDOOR = re.compile(r"야외|바깥|밖에서|햇볕|햇살")
MAX_EVIDENCE = 2
MAX_REFERENCE_CANDIDATES = 5
MAX_REFERENCE_REVIEWS = 5
LEVEL_RANK = {"높음": 0, "보통": 1, "낮음": 2}

CATEGORY_LABELS = {
    "tourapi:12": "관광지", "tourapi:14": "문화시설", "tourapi:28": "레포츠 시설",
    "kakao:CT1": "문화시설", "kakao:AT4": "관광명소", "kakao:PARK": "공원", "kakao:KIDS": "키즈카페",
}
BROAD_CATEGORIES = {"관광지", "관광명소", "문화시설", "레포츠 시설"}
# candidates.kind_of -> the kind named in "X은(는) <kind>입니다": many parks are only a TourAPI
# 관광지, so the kind from the name / cat3 is what lets "서울숲 같은 곳" find 만석거공원
KIND_LABELS = {"zoo": "동물원", "kids": "키즈카페", "themepark": "테마파크", "museum": "박물관",
               "experience": "체험 장소", "nature": "숲·수목원 같은 자연 공원", "park": "공원",
               "library": "도서관", "heritage": "고궁"}


def _kind_labels(p: dict, types: list) -> list[str]:
    """Specific kinds of a place, from its source categories and from candidates.kind_of."""
    labels = {CATEGORY_LABELS[t] for t in types if t in CATEGORY_LABELS} - BROAD_CATEGORIES
    kind = KIND_LABELS.get(kind_of({**p, "types": types}))
    if kind and not any(kind in lb or lb in kind for lb in labels):
        labels.add(kind)
    return sorted(labels)
FACILITY_TEXT = {"nursing_room": "수유실", "stroller_rental": "유모차 대여", "parking": "주차"}


# ---------------------------------------------------------------- profiles

def _category(types: list[str]) -> Optional[str]:
    labels = sorted({CATEGORY_LABELS[t] for t in types or [] if t in CATEGORY_LABELS})
    return ", ".join(labels) or None


def profile_docs(p: dict) -> list[Document]:
    """Sentence documents describing one candidate (merged place record)."""
    key = place_key(p)
    texts: list[tuple[str, str]] = []
    cat = _category(p.get("types") or [])
    if cat:
        texts.append(("category", f"{p['name']}은(는) {cat}입니다"))
    kinds = [k for k in _kind_labels(p, p.get("types") or []) if k not in (cat or "")]
    if kinds:
        texts.append(("category", f"{p['name']}은(는) {', '.join(kinds)}입니다"))
    for s in split_sentences(p.get("description") or ""):
        texts.append(("description", s))
    io = p.get("indoor_outdoor")
    if io in ("indoor", "outdoor"):
        texts.append(("setting", "실내 장소입니다" if io == "indoor" else "야외 장소입니다"))
    for k, label in FACILITY_TEXT.items():
        if ((p.get("facilities") or {}).get(k) or {}).get("status") == "있음":
            texts.append(("facility", f"{label}이(가) 있습니다"))
    for line in p.get("review_summary") or []:
        if line not in (FAIL, NO_REVIEW):
            texts.append(("review", line))
    return [Document(f"{key}#{i}", key, t, kind) for i, (kind, t) in enumerate(texts)]


def reference_profile(prov: Providers, raw: dict) -> dict:
    """Profile sentences of a chosen reference place (description + review snippets).

    A broad category sentence is left out on purpose: "X은(는) 관광지입니다" is close to
    every candidate's own category sentence and would drown the signal. A specific kind
    ("서울숲은(는) 공원입니다") comes first: it is what "서울숲 같은 곳" mostly means.
    """
    sentences = split_sentences(raw.get("description") or "")
    # a Kakao document's description is its category path ("여행 > 공원 > 도시근린공원")
    category = raw.get("category") or (raw.get("description", "") if raw.get("source") == "kakao" else "")
    kinds = _kind_labels({"name": raw.get("name", ""), "category": category},
                         [t for t in raw.get("kinds") or [raw.get("type")] if t])
    if kinds:
        sentences.insert(0, f"{raw['name']}은(는) {', '.join(kinds)}입니다")
    failed: list[str] = []
    reviews = guarded(failed, "naver", prov.reviews, raw) or []
    for r in reviews[:MAX_REFERENCE_REVIEWS]:
        sentences += split_sentences(f"{r.get('title', '')}. {r.get('snippet', '')}")
    return {
        "name": raw["name"],
        "address": raw.get("address", ""),
        "profile": sentences,
        "kinds": kinds,
        "failed_sources": failed,
    }


def wanted_setting(preference_text: Optional[str]) -> Optional[str]:
    """'indoor' for "실내 위주로" / "비 와도 괜찮은 곳", 'outdoor' for "야외에서", else None
    (both or neither said)."""
    t = preference_text or ""
    indoor, outdoor = bool(_WANTS_INDOOR.search(t)), bool(_WANTS_OUTDOOR.search(t))
    return "indoor" if indoor and not outdoor else "outdoor" if outdoor and not indoor else None


def apply_setting(match: dict, place: dict, setting_doc: Optional[Document], wanted: Optional[str]) -> dict:
    """A place in the wanted setting is 높음 with its setting sentence as the first evidence;
    one in the other setting is at most 보통."""
    io = place.get("indoor_outdoor")
    if not wanted or io not in ("indoor", "outdoor"):
        return match
    if io == wanted:
        return _high_with(match, setting_doc)
    if match["level"] == "높음":
        return {**match, "level": "보통"}
    return match


def _kind_group(label: str) -> str:
    return "공원" if "공원" in label else label     # 공원 ~ 숲·수목원 같은 자연 공원


def apply_kind(match: dict, place: dict, kind_docs: list[Document], ref_kinds: list[str]) -> dict:
    """A place of the reference place's kind ("서울숲 같은 곳" -> parks) is 높음 with its kind
    sentence as the first evidence. Titan scores "서울숲은(는) 공원입니다" against
    "만석거공원은(는) 공원입니다" only ~0.30: the names dominate the vectors."""
    wanted = {_kind_group(k) for k in ref_kinds or []}
    if not wanted:
        return match
    doc = next((d for d in kind_docs if any(_kind_group(lb) in wanted for lb in _labels_in(d.text))), None)
    return _high_with(match, doc) if doc else match


def _labels_in(text: str) -> list[str]:
    """Kind labels of a "X은(는) <kinds>입니다" sentence (the name is skipped: "만석거공원")."""
    kinds = text.split("은(는) ", 1)[-1]
    known = set(CATEGORY_LABELS.values()) | set(KIND_LABELS.values())
    return [lb for lb in known if lb in kinds]


def _high_with(match: dict, doc: Optional[Document]) -> dict:
    """`match` raised to 높음, `doc` (the sentence that decided it) first in the evidence."""
    ev = [e for e in match["evidence"] if not doc or e["doc_id"] != doc.doc_id]
    if doc:
        ev = [{"doc_id": doc.doc_id, "text": doc.text, "score": match["score"]}] + ev
    return {**match, "level": "높음", "evidence": ev[:MAX_EVIDENCE]}


SAME_PLACE_KM = 1.5              # same name this close = one place listed by two sources


def _distinct_places(items: list[dict]) -> list[dict]:
    """Drop repeats of one place (TourAPI and Kakao both list "서울숲" at the same spot);
    the first one (TourAPI, with a description) is kept."""
    out: list[dict] = []
    for r in items:
        same = next((o for o in out if _norm(r["name"]) == _norm(o["name"]) and _near(r, o)), None)
        if same is None:
            out.append({**r, "kinds": [r["type"]] if r.get("type") else []})
        elif r.get("type") and r["type"] not in same["kinds"]:
            same["kinds"].append(r["type"])      # Kakao knows 서울숲 is a 공원, TourAPI only a 관광지
    return out


def _near(a: dict, b: dict) -> bool:
    try:
        return haversine_km(float(a["lat"]), float(a["lng"]), float(b["lat"]), float(b["lng"])) <= SAME_PLACE_KM
    except (KeyError, TypeError, ValueError):
        return False


def resolve_reference(prov: Providers, name: str) -> dict:
    """Find the reference place nationwide.

    status: ok | not_found | ambiguous | failed | unavailable
    """
    if prov.keyword_search is None:
        return {"status": "unavailable"}
    try:
        items = [r for r in (call_api(prov.keyword_search, name, None, None, None) or []) if r.get("name")]
    except Exception:
        return {"status": "failed", "failed_sources": ["keyword_search"]}
    items = _distinct_places(items)
    exact = [r for r in items if _norm(r["name"]) == _norm(name)]
    if len(exact) == 1:
        chosen = exact[0]
    elif len(items) == 1:
        chosen = items[0]
    elif not items:
        return {"status": "not_found"}
    else:
        pool = exact or items
        return {
            "status": "ambiguous",
            "candidates": [{"name": r["name"], "address": r.get("address", ""), "raw": r}
                           for r in pool[:MAX_REFERENCE_CANDIDATES]],
        }
    return {"status": "ok", **reference_profile(prov, chosen)}


# ---------------------------------------------------------------- sub-graph

class PreferenceState(TypedDict, total=False):
    # input
    places: list[dict]
    preference_text: Optional[str]
    reference: Optional[dict]          # {"name", "profile": [sentences]}
    # internal
    queries: list[str]
    docs: list[Document]
    store: Any
    query_vectors: list[list[float]]
    # output
    status: str                        # ok | skipped | unavailable | failed
    matches: dict                      # place_key -> {"level", "score", "evidence": [{doc_id, text}]}
    failed_sources: Annotated[list[str], operator.add]


def build_graph(prov: Providers):
    def build_query(state: PreferenceState) -> dict:
        queries = []
        if state.get("preference_text"):
            queries.append(state["preference_text"])
        ref = state.get("reference") or {}
        queries += list(ref.get("profile") or [])[:6]
        return {"queries": queries}

    def route_query(state: PreferenceState) -> str:
        if not state.get("queries") or not state.get("places"):
            return "skip"
        if prov.embed is None:
            return "unavailable"
        return "build_profiles"

    def skip(state: PreferenceState) -> dict:
        return {"status": "skipped", "matches": {}}

    def unavailable(state: PreferenceState) -> dict:
        return {"status": "unavailable", "matches": {}}

    def build_profiles(state: PreferenceState) -> dict:
        docs = [d for p in state["places"] for d in profile_docs(p)]
        return {"docs": docs}

    def index(state: PreferenceState) -> dict:
        docs, queries = state.get("docs") or [], state["queries"]
        failed: list[str] = []
        vectors = guarded(failed, "embedding", prov.embed, [d.text for d in docs] + queries)
        if vectors is None or len(vectors) != len(docs) + len(queries):
            return {"status": "failed", "matches": {}, "failed_sources": failed or ["embedding"]}
        return {
            "store": VectorStore.build(docs, vectors[:len(docs)]),
            "query_vectors": vectors[len(docs):],
        }

    def route_index(state: PreferenceState) -> str:
        return END if state.get("status") == "failed" else "score"

    def score(state: PreferenceState) -> dict:
        store: VectorStore = state["store"]
        wanted = wanted_setting(state.get("preference_text"))
        setting_docs = {d.owner: d for d in state.get("docs") or [] if d.kind == "setting"}
        kind_docs: dict[str, list[Document]] = {}
        for d in state.get("docs") or []:
            if d.kind == "category":
                kind_docs.setdefault(d.owner, []).append(d)
        ref_kinds = (state.get("reference") or {}).get("kinds") or []
        matches = {}
        for p in state["places"]:
            key = place_key(p)
            hits: dict[str, tuple[Document, float]] = {}
            for qv in state["query_vectors"]:
                for doc, s in store.search(qv, owner=key, k=MAX_EVIDENCE):
                    if doc.doc_id not in hits or s > hits[doc.doc_id][1]:
                        hits[doc.doc_id] = (doc, s)
            ranked = sorted(hits.values(), key=lambda t: t[1], reverse=True)
            best = ranked[0][1] if ranked else 0.0
            level = "높음" if best >= HIGH else ("보통" if best >= MID else "낮음")
            evidence = [{"doc_id": d.doc_id, "text": d.text, "score": round(s, 3)}
                        for d, s in ranked[:MAX_EVIDENCE] if s >= MID]
            match = apply_kind({"level": level, "score": round(best, 3), "evidence": evidence},
                               p, kind_docs.get(key, []), ref_kinds)
            matches[key] = apply_setting(match, p, setting_docs.get(key), wanted)
        return {"status": "ok", "matches": matches}

    g = StateGraph(PreferenceState)
    for name, fn in (("build_query", build_query), ("skip", skip), ("unavailable", unavailable),
                     ("build_profiles", build_profiles), ("index", index), ("score", score)):
        g.add_node(name, fn)
    g.add_edge(START, "build_query")
    g.add_conditional_edges("build_query", route_query, ["skip", "unavailable", "build_profiles"])
    g.add_edge("skip", END)
    g.add_edge("unavailable", END)
    g.add_edge("build_profiles", "index")
    g.add_conditional_edges("index", route_index, ["score", END])
    g.add_edge("score", END)
    return g.compile()


def run(graph: Any, *, places: list[dict], preference_text: Optional[str],
        reference: Optional[dict]) -> dict:
    s = graph.invoke({"places": places, "preference_text": preference_text, "reference": reference})
    return {
        "status": s.get("status", "skipped"),
        "matches": s.get("matches") or {},
        "failed_sources": list(s.get("failed_sources") or []),
    }
