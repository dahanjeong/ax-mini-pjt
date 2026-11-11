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
from typing import Annotated, Any, Optional, TypedDict

from langgraph.graph import END, START, StateGraph

from ..constants import FAIL, NO_REVIEW
from ..retriever import Document, VectorStore, split_sentences
from ..tools import Providers, call_api, guarded
from .place import _norm, place_key

HIGH = 0.55          # cosine similarity for 높음
MID = 0.40           # cosine similarity for 보통 (and the minimum for evidence)
MAX_EVIDENCE = 2
MAX_REFERENCE_CANDIDATES = 5
MAX_REFERENCE_REVIEWS = 5
LEVEL_RANK = {"높음": 0, "보통": 1, "낮음": 2}

CATEGORY_LABELS = {
    "tourapi:12": "관광지", "tourapi:14": "문화시설", "tourapi:28": "레포츠 시설",
    "kakao:CT1": "문화시설", "kakao:AT4": "관광명소",
}
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

    The templated category sentence is left out on purpose: "X은(는) 관광지입니다"
    is close to every candidate's own category sentence and would drown the signal.
    """
    sentences = split_sentences(raw.get("description") or "")
    failed: list[str] = []
    reviews = guarded(failed, "naver", prov.reviews, raw) or []
    for r in reviews[:MAX_REFERENCE_REVIEWS]:
        sentences += split_sentences(f"{r.get('title', '')}. {r.get('snippet', '')}")
    return {
        "name": raw["name"],
        "address": raw.get("address", ""),
        "profile": sentences,
        "failed_sources": failed,
    }


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
            matches[key] = {"level": level, "score": round(best, 3), "evidence": evidence}
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
