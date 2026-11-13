"""RAGAS evaluation of the review-summary RAG (NAVER review search -> Claude 3-line summary).

Two steps, two environments (ragas 0.4 needs Python <= 3.13 and langchain-community < 0.4,
so it lives in its own venv and never touches the service dependencies):

    python evaluation/run_ragas.py collect [--ids 1,2,3,4,8]
        service env: runs the in-out cases through the real service and records, for every
        result card, the reviews the summary was written from -> results/ragas_samples.json
    .venv-eval/Scripts/python evaluation/run_ragas.py score
        eval venv (evaluation/requirements-ragas.txt): scores the samples with RAGAS on Bedrock
        -> results/ragas_scores.json + ragas_report.md

One sample per result card that has a review summary:
- user_input          "{월령} 아기와 '{장소}'에 가려고 해요. 후기를 아기 동반 관점으로 요약해 주세요."
- retrieved_contexts  the NAVER review snippets passed to the judge (title + snippet)
- response            the 3-line review summary shown on the card
- reference           public data on the place (TourAPI facility statuses + the first sentences
                      of its overview): an official source independent of the reviews. Cards
                      without public data (Kakao-only places) have no reference and are left
                      out of context_recall only.

Metrics: faithfulness, answer_relevancy (ResponseRelevancy), context_precision
(LLMContextPrecisionWithoutReference: was each retrieved review useful for the summary?),
context_recall (LLMContextRecall: how much of the official facts the retrieved reviews cover).
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
SCORES = EVAL_DIR / "results" / "ragas_scores.json"
REPORT = EVAL_DIR / "ragas_report.md"
DEFAULT_IDS = "1,2,3,4,8"        # recommendation cases with different departures / ages

QUESTION = ("{age} 아기와 '{name}'에 가려고 해요. 다녀온 사람들의 후기를 아기 동반 관점"
            "(이용 연령, 유모차·수유실·주차, 머무는 시간, 주의할 점)으로 3줄 요약해 주세요.")
FACILITY_TEXT = {"nursing_room": "수유실", "stroller_rental": "유모차 대여", "parking": "주차"}
OVERVIEW_SENTENCES = 3

RAGAS_LLM_REGION = os.getenv("RAGAS_LLM_REGION", "us-west-2")
RAGAS_LLM_MODEL = os.getenv("RAGAS_LLM_MODEL", "us.anthropic.claude-sonnet-4-6")
RAGAS_EMBED_REGION = os.getenv("RAGAS_EMBED_REGION", "us-east-1")
RAGAS_EMBED_MODEL = os.getenv("RAGAS_EMBED_MODEL", "amazon.titan-embed-text-v2:0")
METRIC_NAMES = ("context_recall", "context_precision", "faithfulness", "answer_relevancy")


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


# ---------------------------------------------------------------- score (eval venv)

def _mean(values: list) -> float | None:
    vals = [v for v in values if isinstance(v, (int, float)) and not math.isnan(v)]
    return round(sum(vals) / len(vals), 3) if vals else None


def score() -> None:
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

    data = json.loads(SAMPLES.read_text(encoding="utf-8"))
    samples = data["samples"]
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

    base = run(samples, [Faithfulness(), ResponseRelevancy(strictness=1),
                         LLMContextPrecisionWithoutReference()])
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
            "context_precision": b.get("llm_context_precision_without_reference"),
            "context_recall": r.get("context_recall"),
        })
    summary = {m: _mean([r[m] for r in rows]) for m in METRIC_NAMES}
    counts = {m: sum(1 for r in rows if isinstance(r[m], (int, float)) and not math.isnan(r[m]))
              for m in METRIC_NAMES}
    out = {"scored": date.today().isoformat(), "collected": data.get("collected"), "case_ids": data.get("case_ids"),
           "llm": f"{RAGAS_LLM_REGION}/{RAGAS_LLM_MODEL}", "embeddings": RAGAS_EMBED_MODEL,
           "samples": len(rows), "summary": summary, "counts": counts, "rows": rows}
    SCORES.write_text(json.dumps(out, ensure_ascii=False, indent=2, default=str), encoding="utf-8")
    write_report(out)
    print(json.dumps({"summary": summary, "counts": counts}, ensure_ascii=False))


def _fmt(v) -> str:
    return "-" if not isinstance(v, (int, float)) or math.isnan(v) else f"{v:.2f}"


def write_report(out: dict) -> None:
    s, n = out["summary"], out["counts"]
    lines = [
        "# RAGAS 평가 결과 (후기 요약 RAG)",
        "",
        f"- 수집일: {out['collected']} · 채점일: {out['scored']}",
        f"- 시나리오: 인-아웃 세트 #{', #'.join(str(i) for i in out['case_ids'])} "
        f"(실제 서비스로 실행, 후기 요약이 있는 추천 카드 {out['samples']}개 = 샘플 {out['samples']}개)",
        f"- 평가 LLM: `{out['llm']}` · 임베딩: `{out['embeddings']}` (ragas 0.4.3)",
        "- 원본: [results/ragas_samples.json](results/ragas_samples.json) · "
        "[results/ragas_scores.json](results/ragas_scores.json) · 실행 방법: [docs/evaluation.md](../docs/evaluation.md)",
        "",
        "## 요약",
        "",
        "| 지표 | 점수 | 샘플 수 | 목표 (SERVICE.md) |",
        "|---|---:|---:|---|",
        f"| context_recall | {_fmt(s['context_recall'])} | {n['context_recall']} | - |",
        f"| context_precision | {_fmt(s['context_precision'])} | {n['context_precision']} | 0.7 이상 |",
        f"| faithfulness | {_fmt(s['faithfulness'])} | {n['faithfulness']} | 0.8 이상 |",
        f"| answer_relevancy | {_fmt(s['answer_relevancy'])} | {n['answer_relevancy']} | - |",
        "",
        "## 샘플 구성",
        "",
        "| 필드 | 내용 |",
        "|---|---|",
        "| question | \"{월령} 아기와 '{장소}'에 가려고 해요. 후기를 아기 동반 관점으로 3줄 요약해 주세요.\" |",
        "| contexts | 후기 요약에 실제로 들어간 네이버 블로그·카페 검색 결과(제목 + 요약문, 최대 10건) |",
        "| answer | 카드에 표시된 후기 3줄 요약 |",
        "| reference | 공공데이터(TourAPI) 편의시설 판정(있음/없음) + 개요 앞 3문장. 카카오에서만 찾은 장소는 공공데이터가 없어 context_recall에서만 빠짐 |",
        "",
        "- **context_precision**은 정답 없이(`LLMContextPrecisionWithoutReference`) 각 후기가 요약에 쓸모 있었는지로 본다.",
        "- **context_recall**은 공식 정보(편의시설·장소 개요)를 검색된 후기가 얼마나 담고 있는지로 본다. "
        "후기는 공식 개요의 연혁·소개 문구를 거의 다루지 않으므로, 낮을수록 '후기만으로는 공식 정보를 다 확인할 수 없다'는 뜻이다.",
        "",
        "## 해석",
        "",
        "- **faithfulness (목표 달성):** 요약 문장 대부분이 검색된 후기에 근거가 있다. 낮은 샘플은 "
        "후기 요약문에 없는 표현(예: '먹이주기 체험')이 한두 개 섞인 경우다.",
        "- **context_precision (목표 미달):** 평가 LLM은 후기 하나하나가 요약에 쓸모 있었는지 따로 판정한다. "
        "네이버 검색 API가 주는 요약문은 150자 남짓의 조각이라(본문 수집 안 함, 정책) 글 하나에 사실이 한두 개뿐이고, "
        "'이 글만으로는 요약을 만들 수 없다'며 0으로 판정되는 경우가 많다. 같은 이름의 다른 지점 글이 섞인 경우"
        "(예: 오마이쥬 여러 지점)도 0이 된다.",
        "- **answer_relevancy:** 요약에서 거꾸로 만든 질문과 원래 질문의 임베딩 유사도다. Titan V2는 한국어 문장 유사도가 "
        "낮게 압축돼 나온다(같은 Titan으로 잰 기준점: 관련 질문 0.35, 무관한 질문 0.07). 그래서 절대값보다 "
        "무관한 질문 대비 차이로 읽어야 한다. 더 나은 다국어 임베딩(Cohere multilingual)은 계정 권한이 없어 쓰지 못했다.",
        "- **context_recall:** 후기가 공식 개요(연혁·소개)를 다루지 않으므로 낮은 것이 자연스럽다. "
        "편의시설(주차 등)은 후기에서 자주 확인된다.",
        "",
        "## 샘플별 점수",
        "",
        "| 케이스 | 순위 | 장소 | 후기 수 | recall | precision | faithfulness | relevancy |",
        "|---:|---:|---|---:|---:|---:|---:|---:|",
    ]
    for r in out["rows"]:
        lines.append(f"| {r['case_id']} | {r['rank']} | {r['place']} | {r['contexts']} | {_fmt(r['context_recall'])} | "
                     f"{_fmt(r['context_precision'])} | {_fmt(r['faithfulness'])} | {_fmt(r['answer_relevancy'])} |")
    REPORT.write_text("\n".join(lines) + "\n", encoding="utf-8")
    print(f"report -> {REPORT.relative_to(ROOT)}")


def main() -> None:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    sub = ap.add_subparsers(dest="cmd", required=True)
    c = sub.add_parser("collect", help="run the cases on the real service and record samples (service env)")
    c.add_argument("--ids", default=DEFAULT_IDS, help="in-out case ids, comma separated")
    sub.add_parser("score", help="score the recorded samples with RAGAS (eval venv)")
    sub.add_parser("report", help="rewrite ragas_report.md from results/ragas_scores.json")
    args = ap.parse_args()
    if args.cmd == "collect":
        collect([int(x) for x in args.ids.split(",") if x.strip()])
    elif args.cmd == "score":
        score()
    else:
        write_report(json.loads(SCORES.read_text(encoding="utf-8")))


if __name__ == "__main__":
    main()
