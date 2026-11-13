"""RAGAS evaluation of the two RAG steps of the service.

- review summary   (NAVER review search -> Claude 3-line summary):
                   faithfulness, answer_relevancy, context_recall
- preference match (place-profile sentences -> Titan vector search -> 취향 일치도):
                   context_precision

Two steps, two environments (ragas 0.4 needs Python <= 3.13 and langchain-community < 0.4,
so it lives in its own venv and never touches the service dependencies):

    python evaluation/run_ragas.py collect [--ids 1,2,3,4,8]
        service env: runs the in-out cases through the real service and records, for every
        result card, the reviews the summary was written from -> results/ragas_samples.json
    python evaluation/run_ragas.py collect-preference
        service env: runs the preference scenarios (PREFERENCE_CASES) and records, for every
        result card, the sentences the vector search returned -> results/ragas_preference_samples.json
    .venv-eval/Scripts/python evaluation/run_ragas.py score [--only review|preference]
        eval venv (evaluation/requirements-ragas.txt): scores the samples with RAGAS on Bedrock
        -> results/ragas_scores.json + ragas_report.md (--only keeps the other part's scores)

Review summary: one sample per result card that has a review summary:
- user_input          "{월령} 아기와 '{장소}'에 가려고 해요. 후기를 아기 동반 관점으로 요약해 주세요."
- retrieved_contexts  the NAVER review snippets passed to the judge (title + snippet)
- response            the 3-line review summary shown on the card
- reference           public data on the place (TourAPI facility statuses + the first sentences
                      of its overview): an official source independent of the reviews. Cards
                      without public data (Kakao-only places) have no reference and are left
                      out of context_recall only.

Metrics: faithfulness, answer_relevancy (ResponseRelevancy), context_recall (LLMContextRecall:
how much of the official facts the retrieved reviews cover).

Preference match: one sample per result card that has a preference match:
- user_input          the wish ("실내 위주로…" / "'서울숲' 같은 곳") and the place to judge
- retrieved_contexts  the place's profile sentences the vector search returned, best first
                      (top 2 per query sentence, merged as the service ranks them)
- response            "'{장소}'의 취향 일치도는 {높음|보통|낮음}입니다." as shown on the card
Metric: context_precision (LLMContextPrecisionWithoutReference: was each retrieved sentence
useful for that judgement, and are the useful ones ranked first?).
"""
from __future__ import annotations

import argparse
import json
import math
import os
import re
import sys
import time
from datetime import date
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
EVAL_DIR = ROOT / "evaluation"
SAMPLES = EVAL_DIR / "results" / "ragas_samples.json"
PREF_SAMPLES = EVAL_DIR / "results" / "ragas_preference_samples.json"
SCORES = EVAL_DIR / "results" / "ragas_scores.json"
REPORT = EVAL_DIR / "ragas_report.md"
DEFAULT_IDS = "1,2,3,4,8"        # recommendation cases with different departures / ages

QUESTION = ("{age} 아기와 '{name}'에 가려고 해요. 다녀온 사람들의 후기를 아기 동반 관점"
            "(이용 연령, 유모차·수유실·주차, 머무는 시간, 주의할 점)으로 3줄 요약해 주세요.")
FACILITY_TEXT = {"nursing_room": "수유실", "stroller_rental": "유모차 대여", "parking": "주차"}
OVERVIEW_SENTENCES = 3

# Preference scenarios: the in-out cases with a preference (#3 실내, #4 서울숲 같은 곳, #17 비 와도)
# plus two decided by similarity alone (#3 / #17 are mostly decided by the indoor/outdoor rule).
# Same turn format as test_queries.csv (" >> " between turns).
PREFERENCE_CASES = [
    {"id": 3, "input": None},
    {"id": 4, "input": None},
    {"id": 17, "input": None},
    {"id": "P1", "input": "30개월 아기랑 내일 강남역에서 출발해요. 동물 먹이주기 체험을 할 수 있는 곳이면 좋겠어요 >> 오전 10시"},
    {"id": "P2", "input": "24개월 아기랑 내일 판교역에서 출발해요. 숲길 산책할 수 있는 곳이 좋아요 >> 오전 10시"},
]
PREF_QUESTION = ("아기와 나들이 갈 곳을 찾고 있어요. 원하는 곳: {wish}. "
                 "'{name}'이(가) 여기에 맞는지 판단할 근거가 되는 장소 정보를 찾아 주세요.")
PREF_RESPONSE = "'{name}'의 취향 일치도는 {level}입니다."

RAGAS_LLM_REGION = os.getenv("RAGAS_LLM_REGION", "us-west-2")
RAGAS_LLM_MODEL = os.getenv("RAGAS_LLM_MODEL", "us.anthropic.claude-sonnet-4-6")
RAGAS_EMBED_REGION = os.getenv("RAGAS_EMBED_REGION", "us-east-1")
RAGAS_EMBED_MODEL = os.getenv("RAGAS_EMBED_MODEL", "amazon.titan-embed-text-v2:0")
REVIEW_METRICS = ("context_recall", "faithfulness", "answer_relevancy")


# ---------------------------------------------------------------- collect (service env)

def reference_text(name: str, public: dict | None) -> str | None:
    """Official facts on the place: facility statuses that are known (있음/없음) and the
    first sentences of the TourAPI overview. None when public data has neither."""
    if not isinstance(public, dict):
        return None
    lines = [f"{name}의 {label} 여부: {public[k]}." for k, label in FACILITY_TEXT.items()
             if public.get(k) in ("있음", "없음")]
    overview = re.sub(r"\s+", " ", str(public.get("overview") or "")).strip()
    if overview:
        sentences = [s.strip() for s in re.split(r"(?<=[.!?])\s+", overview) if s.strip()]
        lines.append(" ".join(sentences[:OVERVIEW_SENTENCES]))
    return "\n".join(lines) or None


def collect_case(case: dict, base, geocode, extractor) -> list[dict]:
    import dataclasses

    from backend.agent import Deps, build_graph, recommendation_turn
    from backend.core.constants import FAIL, NO_REVIEW
    from backend.prompts.judge import age_label
    from backend.supervisor.cards import build_cards

    public: dict[str, dict] = {}
    judged: dict[str, dict] = {}

    def facilities(place: dict):
        out = base.facilities(place)
        public[str(place.get("name"))] = out
        return out

    def llm_judge(place: dict, age_months: int, reviews: list):
        out = base.llm_judge(place, age_months, reviews)
        judged[str(place.get("name"))] = {"age_months": age_months, "reviews": list(reviews or [])}
        return out

    prov = dataclasses.replace(base, facilities=facilities, llm_judge=llm_judge)
    graph = build_graph(Deps(geocode=geocode, extractor=extractor))
    session = f"ragas-{case['id']}-{int(time.time())}"
    view: dict = {}
    for turn in case["turns"]:
        view = recommendation_turn(graph, session, turn, prov)
    samples = []
    for rank, card in enumerate(build_cards(view.get("result_cards") or []), 1):
        j = judged.get(card["name"])
        summary = card.get("review_summary") or []
        if not j or not j["reviews"] or summary in ([NO_REVIEW], [FAIL]):
            continue
        samples.append({
            "case_id": case["id"],
            "rank": rank,
            "place": card["name"],
            "user_input": QUESTION.format(age=age_label(j["age_months"]), name=card["name"]),
            "retrieved_contexts": [f"{r.get('title', '')}\n{r.get('snippet', '')}".strip() for r in j["reviews"]],
            "response": "\n".join(summary),
            "reference": reference_text(card["name"], public.get(card["name"])),
            "sources": [s["link"] for s in card.get("review_sources") or []],
        })
    return samples


def collect(ids: list[int]) -> None:
    sys.path.insert(0, str(ROOT / "src"))
    sys.path.insert(0, str(EVAL_DIR))
    from concurrent.futures import ThreadPoolExecutor

    from backend.integrations.bedrock import BedrockLLM
    from backend.integrations.factory import build_providers
    from backend.integrations.kakao import KakaoClient
    from run_eval import EVAL_DIR as _E, load_cases  # noqa: F401  (same case file and parser)

    cases = [c for c in load_cases(EVAL_DIR / "test_queries.csv") if c["id"] in ids]
    llm = BedrockLLM()
    providers, geocode = build_providers(llm=llm), KakaoClient().geocode

    def one(case: dict) -> list[dict]:
        t = time.monotonic()
        try:
            out = collect_case(case, providers, geocode, llm.extract)
        except Exception as e:                       # one broken case does not stop the run
            print(f"#{case['id']} failed: {e!r}", flush=True)
            return []
        print(f"#{case['id']}: {len(out)} samples ({time.monotonic() - t:.0f}s)", flush=True)
        return out

    with ThreadPoolExecutor(max_workers=2) as ex:
        samples = [s for chunk in ex.map(one, cases) for s in chunk]
    SAMPLES.parent.mkdir(parents=True, exist_ok=True)
    SAMPLES.write_text(json.dumps({"collected": date.today().isoformat(), "case_ids": ids, "samples": samples},
                                  ensure_ascii=False, indent=2), encoding="utf-8")
    print(f"{len(samples)} samples -> {SAMPLES.relative_to(ROOT)}")


def collect_preference_case(case: dict, base, geocode, extractor) -> list[dict]:
    """Records every preference-matching run of the case (the wish, and per place the sentences
    the vector search returned); the last run is the one the cards show."""
    from unittest import mock

    from backend.agent import Deps, build_graph, recommendation_turn
    from backend.agents import preference
    from backend.agents.candidates import place_key
    from backend.retriever import VectorStore
    from backend.supervisor.cards import build_cards

    runs: list[dict] = []
    original_run, original_search = preference.run, VectorStore.search

    def search(self, query_vec, *, owner=None, k=2):
        hits = original_search(self, query_vec, owner=owner, k=k)
        if runs:
            runs[-1]["hits"].setdefault(owner, []).extend(hits)
        return hits

    def run(graph, *, places, preference_text, reference):
        wish = f"'{reference['name']}' 같은 곳" if reference and reference.get("name") else preference_text
        runs.append({"wish": wish, "names": {place_key(p): p.get("name") for p in places}, "hits": {}})
        return original_run(graph, places=places, preference_text=preference_text, reference=reference)

    graph = build_graph(Deps(geocode=geocode, extractor=extractor))
    session = f"ragas-pref-{case['id']}-{int(time.time())}"
    view: dict = {}
    with mock.patch.object(preference, "run", run), mock.patch.object(VectorStore, "search", search):
        for turn in case["turns"]:
            view = recommendation_turn(graph, session, turn, base)
    if not runs:
        return []
    last = runs[-1]
    key_by_name = {name: key for key, name in last["names"].items()}
    samples = []
    for rank, card in enumerate(build_cards(view.get("result_cards") or []), 1):
        match, key = card.get("preference_match"), key_by_name.get(card["name"])
        if not match or key not in last["hits"]:
            continue
        best: dict[str, tuple] = {}
        for doc, sim in last["hits"][key]:          # union over the query sentences, best score kept
            if doc.doc_id not in best or sim > best[doc.doc_id][1]:
                best[doc.doc_id] = (doc, sim)
        ranked = sorted(best.values(), key=lambda t: t[1], reverse=True)
        samples.append({
            "case_id": case["id"], "rank": rank, "place": card["name"], "level": match["level"],
            "user_input": PREF_QUESTION.format(wish=last["wish"], name=card["name"]),
            "retrieved_contexts": [d.text for d, _ in ranked],
            "context_kinds": [d.kind for d, _ in ranked],
            "context_scores": [round(sim, 3) for _, sim in ranked],
            "response": PREF_RESPONSE.format(name=card["name"], level=match["level"]),
        })
    return samples


def collect_preference() -> None:
    sys.path.insert(0, str(ROOT / "src"))
    sys.path.insert(0, str(EVAL_DIR))
    from backend.integrations.bedrock import BedrockLLM
    from backend.integrations.factory import build_providers
    from backend.integrations.kakao import KakaoClient
    from run_eval import TURN_SEP, load_cases

    by_id = {c["id"]: c for c in load_cases(EVAL_DIR / "test_queries.csv")}
    llm = BedrockLLM()
    providers, geocode = build_providers(llm=llm), KakaoClient().geocode
    samples = []
    for spec in PREFERENCE_CASES:                   # one at a time: the search recorder is shared
        case = by_id[spec["id"]] if spec["input"] is None else {
            "id": spec["id"], "turns": [t.strip() for t in spec["input"].split(TURN_SEP) if t.strip()]}
        t = time.monotonic()
        try:
            out = collect_preference_case(case, providers, geocode, llm.extract)
        except Exception as e:                      # one broken case does not stop the run
            print(f"#{spec['id']} failed: {e!r}", flush=True)
            continue
        print(f"#{spec['id']}: {len(out)} samples ({time.monotonic() - t:.0f}s)", flush=True)
        samples += out
    PREF_SAMPLES.parent.mkdir(parents=True, exist_ok=True)
    PREF_SAMPLES.write_text(json.dumps({"collected": date.today().isoformat(), "cases": PREFERENCE_CASES,
                                        "samples": samples}, ensure_ascii=False, indent=2), encoding="utf-8")
    print(f"{len(samples)} samples -> {PREF_SAMPLES.relative_to(ROOT)}")


# ---------------------------------------------------------------- score (eval venv)

def _mean(values: list) -> float | None:
    vals = [v for v in values if isinstance(v, (int, float)) and not math.isnan(v)]
    return round(sum(vals) / len(vals), 3) if vals else None


def _summarize(rows: list[dict], metrics: tuple) -> tuple[dict, dict]:
    summary = {m: _mean([r.get(m) for r in rows]) for m in metrics}
    counts = {m: sum(1 for r in rows if isinstance(r.get(m), (int, float)) and not math.isnan(r[m]))
              for m in metrics}
    return summary, counts


def _load_scores() -> dict:
    """Saved scores; a file from before the split (context_precision on reviews) becomes the
    review part without context_precision."""
    if not SCORES.exists():
        return {}
    out = json.loads(SCORES.read_text(encoding="utf-8"))
    if "review" not in out and "rows" in out:
        rows = [{k: v for k, v in r.items() if k != "context_precision"} for r in out["rows"]]
        summary, counts = _summarize(rows, REVIEW_METRICS)
        out = {"llm": out.get("llm"), "embeddings": out.get("embeddings"),
               "review": {"scored": out.get("scored"), "collected": out.get("collected"),
                          "case_ids": out.get("case_ids"), "samples": len(rows),
                          "summary": summary, "counts": counts, "rows": rows}}
    return out


def score(only: str | None = None) -> None:
    from dotenv import load_dotenv
    load_dotenv(ROOT / ".env", override=False)

    import warnings
    warnings.filterwarnings("ignore", category=DeprecationWarning)
    from langchain_aws import BedrockEmbeddings, ChatBedrockConverse
    from ragas import EvaluationDataset, evaluate
    from ragas.embeddings import LangchainEmbeddingsWrapper
    from ragas.llms import LangchainLLMWrapper
    from ragas.metrics import (Faithfulness, LLMContextPrecisionWithoutReference, LLMContextRecall,
                               ResponseRelevancy)
    from ragas.run_config import RunConfig

    llm = LangchainLLMWrapper(ChatBedrockConverse(model=RAGAS_LLM_MODEL, region_name=RAGAS_LLM_REGION,
                                                  temperature=0, max_tokens=4096))
    emb = LangchainEmbeddingsWrapper(BedrockEmbeddings(model_id=RAGAS_EMBED_MODEL, region_name=RAGAS_EMBED_REGION))
    run_config = RunConfig(max_workers=4, timeout=300, max_retries=10, max_wait=60)

    def run(rows: list[dict], metrics: list) -> list[dict]:
        ds = EvaluationDataset.from_list([{k: r[k] for k in ("user_input", "retrieved_contexts", "response")}
                                          | ({"reference": r["reference"]} if r.get("reference") else {})
                                          for r in rows])
        result = evaluate(ds, metrics=metrics, llm=llm, embeddings=emb, run_config=run_config,
                          show_progress=True, raise_exceptions=False)
        return result.to_pandas().to_dict("records")

    out = _load_scores()
    today = date.today().isoformat()

    if only in (None, "review"):
        data = json.loads(SAMPLES.read_text(encoding="utf-8"))
        samples = data["samples"]
        base = run(samples, [Faithfulness(), ResponseRelevancy(strictness=1)])
        with_ref = [i for i, s in enumerate(samples) if s.get("reference")]
        recall = run([samples[i] for i in with_ref], [LLMContextRecall()]) if with_ref else []
        recall_by_index = dict(zip(with_ref, recall))
        rows = []
        for i, s in enumerate(samples):
            b, r = base[i], recall_by_index.get(i, {})
            rows.append({
                "case_id": s["case_id"], "rank": s["rank"], "place": s["place"],
                "contexts": len(s["retrieved_contexts"]), "has_reference": bool(s.get("reference")),
                "faithfulness": b.get("faithfulness"),
                "answer_relevancy": b.get("answer_relevancy"),
                "context_recall": r.get("context_recall"),
            })
        summary, counts = _summarize(rows, REVIEW_METRICS)
        out["review"] = {"scored": today, "collected": data.get("collected"), "case_ids": data.get("case_ids"),
                         "samples": len(rows), "summary": summary, "counts": counts, "rows": rows}

    if only in (None, "preference"):
        data = json.loads(PREF_SAMPLES.read_text(encoding="utf-8"))
        samples = data["samples"]
        scored = run(samples, [LLMContextPrecisionWithoutReference()])
        rows = [{
            "case_id": s["case_id"], "rank": s["rank"], "place": s["place"], "level": s["level"],
            "contexts": len(s["retrieved_contexts"]),
            "context_precision": scored[i].get("llm_context_precision_without_reference"),
        } for i, s in enumerate(samples)]
        summary, counts = _summarize(rows, ("context_precision",))
        out["preference"] = {"scored": today, "collected": data.get("collected"),
                             "case_ids": [c["id"] for c in data.get("cases") or []],
                             "samples": len(rows), "summary": summary, "counts": counts, "rows": rows}

    out["llm"], out["embeddings"] = f"{RAGAS_LLM_REGION}/{RAGAS_LLM_MODEL}", RAGAS_EMBED_MODEL
    out["summary"] = {**(out.get("review") or {}).get("summary", {}),
                      **(out.get("preference") or {}).get("summary", {})}
    out["counts"] = {**(out.get("review") or {}).get("counts", {}),
                     **(out.get("preference") or {}).get("counts", {})}
    SCORES.write_text(json.dumps(out, ensure_ascii=False, indent=2, default=str), encoding="utf-8")
    write_report(out)
    print(json.dumps({"summary": out["summary"], "counts": out["counts"]}, ensure_ascii=False))


def _fmt(v) -> str:
    return "-" if not isinstance(v, (int, float)) or math.isnan(v) else f"{v:.2f}"


def _ids(ids: list) -> str:
    return ", ".join(f"#{i}" for i in ids or [])


def write_report(out: dict) -> None:
    rv, pf = out.get("review") or {}, out.get("preference") or {}
    s, n = out.get("summary") or {}, out.get("counts") or {}
    by_level: dict[str, list] = {}
    for r in pf.get("rows") or []:
        by_level.setdefault(r["level"], []).append(r["context_precision"])
    level_text = " · ".join(f"{lv} {_fmt(_mean(v))} ({len(v)}개)" for lv, v in
                            sorted(by_level.items(), key=lambda t: "높음보통낮음".find(t[0])))
    lines = [
        "# RAGAS 평가 결과",
        "",
        "추천 시나리오를 실제 서비스로 돌리고, 나온 추천 카드마다 샘플을 만들어 잰다.",
        "",
        "| 지표 | 무엇을 보나 | 샘플 |",
        "|---|---|---|",
        "| faithfulness | 후기 3줄 요약의 문장이 검색된 후기에 근거하는가 | 후기 요약 |",
        "| answer_relevancy | 후기 요약이 질문에 맞는 답인가 | 후기 요약 |",
        "| context_recall | 공식 정보(공공데이터)를 검색된 후기가 얼마나 담는가 | 후기 요약 (공공데이터가 있는 카드만) |",
        "| context_precision | 취향 매칭 벡터 검색이 돌려준 문장이 일치도 판단에 쓸모 있고 위에 있는가 | 취향 매칭 |",
        "",
        f"- 평가 LLM: `{out.get('llm')}` · 임베딩: `{out.get('embeddings')}` (ragas 0.4.3)",
        "- 원본: [results/ragas_samples.json](results/ragas_samples.json) · "
        "[results/ragas_preference_samples.json](results/ragas_preference_samples.json) · "
        "[results/ragas_scores.json](results/ragas_scores.json) · 실행 방법: [docs/evaluation.md](../docs/evaluation.md)",
        "",
        "## 요약",
        "",
        "| 지표 | 대상 | 점수 | 샘플 수 | 목표 (SERVICE.md) |",
        "|---|---|---:|---:|---|",
        f"| context_recall | 후기 요약 | {_fmt(s.get('context_recall'))} | {n.get('context_recall', 0)} | - |",
        f"| context_precision | 취향 매칭 | {_fmt(s.get('context_precision'))} | {n.get('context_precision', 0)} | 0.7 이상 |",
        f"| faithfulness | 후기 요약 | {_fmt(s.get('faithfulness'))} | {n.get('faithfulness', 0)} | 0.8 이상 |",
        f"| answer_relevancy | 후기 요약 | {_fmt(s.get('answer_relevancy'))} | {n.get('answer_relevancy', 0)} | - |",
        "",
        "## 후기 요약 샘플",
        "",
        f"- 수집일: {rv.get('collected')} · 채점일: {rv.get('scored')}",
        f"- 시나리오: 인-아웃 세트 {_ids(rv.get('case_ids'))} (실제 서비스로 실행, 후기 요약이 있는 추천 카드 "
        f"{rv.get('samples', 0)}개 = 샘플 {rv.get('samples', 0)}개)",
        "",
        "| 필드 | 내용 |",
        "|---|---|",
        "| question | \"{월령} 아기와 '{장소}'에 가려고 해요. 후기를 아기 동반 관점으로 3줄 요약해 주세요.\" |",
        "| contexts | 후기 요약에 실제로 들어간 네이버 블로그·카페 검색 결과(제목 + 요약문, 최대 10건) |",
        "| answer | 카드에 표시된 후기 3줄 요약 |",
        "| reference | 공공데이터(TourAPI) 편의시설 판정(있음/없음) + 개요 앞 3문장. 카카오에서만 찾은 장소는 공공데이터가 없어 context_recall에서만 빠짐 |",
        "",
        "- **faithfulness (목표 달성):** 요약 문장 대부분이 검색된 후기에 근거가 있다. 낮은 샘플은 "
        "후기 요약문에 없는 표현(예: '먹이주기 체험')이 한두 개 섞인 경우다.",
        "- **answer_relevancy:** 요약에서 거꾸로 만든 질문과 원래 질문의 임베딩 유사도다. Titan V2는 한국어 문장 유사도가 "
        "낮게 압축돼 나온다(같은 Titan으로 잰 기준점: 관련 질문 0.35, 무관한 질문 0.07). 그래서 절대값보다 "
        "무관한 질문 대비 차이로 읽어야 한다. 더 나은 다국어 임베딩(Cohere multilingual)은 계정 권한이 없어 쓰지 못했다.",
        "- **context_recall:** 공식 정보(편의시설·장소 개요)를 검색된 후기가 얼마나 담는지다. 후기가 공식 개요(연혁·소개)를 "
        "다루지 않으므로 낮은 것이 자연스럽다. 편의시설(주차 등)은 후기에서 자주 확인된다.",
        "",
        "| 케이스 | 순위 | 장소 | 후기 수 | recall | faithfulness | relevancy |",
        "|---:|---:|---|---:|---:|---:|---:|",
    ]
    for r in rv.get("rows") or []:
        lines.append(f"| {r['case_id']} | {r['rank']} | {r['place']} | {r['contexts']} | {_fmt(r.get('context_recall'))} | "
                     f"{_fmt(r.get('faithfulness'))} | {_fmt(r.get('answer_relevancy'))} |")
    lines += [
        "",
        "## 취향 매칭 샘플",
        "",
        f"- 수집일: {pf.get('collected')} · 채점일: {pf.get('scored')}",
        f"- 시나리오: {_ids(pf.get('case_ids'))} (#3·#4·#17은 인-아웃 세트, P1·P2는 유사도만으로 정해지는 취향을 보려고 "
        f"추가한 시나리오. 취향 일치도가 붙은 추천 카드 {pf.get('samples', 0)}개 = 샘플 {pf.get('samples', 0)}개)",
        "",
        "| 필드 | 내용 |",
        "|---|---|",
        "| question | \"아기와 나들이 갈 곳을 찾고 있어요. 원하는 곳: {취향 문장 또는 '서울숲' 같은 곳}. '{장소}'이(가) 여기에 맞는지 판단할 근거가 되는 장소 정보를 찾아 주세요.\" |",
        "| contexts | 그 장소의 정보 문장(분류·소개·실내/야외·편의시설·후기 요약) 중 벡터 검색이 돌려준 문장, 유사도 높은 순 (질의 문장마다 상위 2개) |",
        "| answer | 카드에 표시된 취향 일치도 (\"'{장소}'의 취향 일치도는 높음입니다.\") |",
        "",
        "- **context_precision**은 정답 없이(`LLMContextPrecisionWithoutReference`) 검색된 문장 각각이 일치도 판단에 "
        "쓸모 있었는지, 쓸모 있는 문장이 위에 있는지를 본다.",
        f"- 일치도별 평균: {level_text or '-'}",
        "",
        "**해석 (목표 0.7 미달):**",
        "- **'비 와도 괜찮은 곳'(#17)은 검색이 실내 문장을 못 찾는다.** Titan에서 \"비 와도 괜찮은 곳\"과 \"실내 장소입니다\"의 "
        "유사도는 0.10이라 검색 결과에 실내 문장이 들어오지 않는다. 서비스는 이 경우 일치도를 유사도가 아니라 실내/야외 "
        "판정 규칙으로 정하고(`agents/preference.py` `apply_setting`) 카드 근거도 실내 문장으로 바꾸지만, 이 지표는 "
        "검색 결과만 보므로 높음 카드가 0점이 된다. 같은 실내 취향이라도 '실내 위주로'(#3)는 1.00이다.",
        "- **비슷한 말을 근거로 인정하지 않는 판정이 있다.** '숲길 산책' 취향에 \"나무 그늘이 있는 산책하기 좋은 공원\""
        "(성남 중앙공원), '동물 먹이주기 체험'에 \"동물원입니다\"(서울어린이대공원)가 검색됐는데도 평가 LLM은 숲길·먹이주기라는 "
        "말이 직접 없다며 0으로 판정했다.",
        "- **기준 장소(#4 '서울숲 같은 곳')는 질의 문장이 여러 개라 검색 문장이 4~8개로 많다.** 일치도가 낮음인 장소는 "
        "관련 없는 문장(편의시설·연령 후기)이 함께 검색돼 0.4 안팎이다.",
        "- 실제 검색이 쓸모 있는 문장을 맨 위에 둔 경우(예: '동물 먹이주기' → 온동물체험농장의 먹이 주기 체험 문장, 0.56)는 1.00이다.",
        "",
        "| 케이스 | 순위 | 장소 | 일치도 | 검색 문장 수 | precision |",
        "|---:|---:|---|---|---:|---:|",
    ]
    for r in pf.get("rows") or []:
        lines.append(f"| {r['case_id']} | {r['rank']} | {r['place']} | {r['level']} | {r['contexts']} | "
                     f"{_fmt(r.get('context_precision'))} |")
    REPORT.write_text("\n".join(lines) + "\n", encoding="utf-8")
    print(f"report -> {REPORT.relative_to(ROOT)}")


def main() -> None:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    sub = ap.add_subparsers(dest="cmd", required=True)
    c = sub.add_parser("collect", help="run the cases on the real service and record samples (service env)")
    c.add_argument("--ids", default=DEFAULT_IDS, help="in-out case ids, comma separated")
    sub.add_parser("collect-preference", help="run the preference scenarios and record samples (service env)")
    sc = sub.add_parser("score", help="score the recorded samples with RAGAS (eval venv)")
    sc.add_argument("--only", choices=("review", "preference"), help="re-score one part, keep the other")
    sub.add_parser("report", help="rewrite ragas_report.md from results/ragas_scores.json")
    args = ap.parse_args()
    if args.cmd == "collect":
        collect([int(x) for x in args.ids.split(",") if x.strip()])
    elif args.cmd == "collect-preference":
        collect_preference()
    elif args.cmd == "score":
        score(args.only)
    else:
        write_report(json.loads(SCORES.read_text(encoding="utf-8")))


if __name__ == "__main__":
    main()
