# 미니 PJT: 아기랑 나들이 (Baby Outing Chat)

## 무엇을 푸나
아기와 나들이 갈 곳을 고를 때 거리·수유실/유모차/주차·날씨·미세먼지·후기를 여러 앱과 블로그에서 따로 찾아 맞춰 봐야 하는 번거로움을, 월령·출발지·날짜만 말하면 조건에 맞는 장소 5곳을 한 번에 추천하는 채팅으로 해결한다.

> 서비스 스펙 상세: [SERVICE.md](SERVICE.md) · 개발 문서: [docs/](docs/)

## 활용한 패턴 (Day 1~7)
<!-- TODO: 각 패턴이 몇 일차 내용인지 채우기 -->
- Day ?: LangGraph 상태 그래프 — 월령 → 낮잠 → 출발지 → 날짜 순서로 확인하고, 빠진 정보가 있으면 조건부 분기로 되묻기
- Day ?: 체크포인터 기반 대화 메모리 — `MemorySaver`로 thread별 대화 상태를 서버 메모리에만 보관 (DB 저장 없음)
- Day ?: 도구 호출 — 카카오 로컬·TourAPI·기상청·에어코리아·네이버 검색을 `Providers`로 주입하고 장소별로 병렬 호출
- Day ?: 구조화 출력 — LLM의 월령 적합도 판정·후기 3줄 요약을 고정 JSON 형식으로만 받고 검증
- Day ?: 가드레일 — 필수 정보 되묻기, "정보 없음" 표시(지어내기 금지), 외부 글 프롬프트 인젝션 방어, 비밀값 비노출
- Day ?: RAG — (도입 예정)

## 아키텍처

```
[React 채팅 UI] ──HTTP──▶ [FastAPI]
 src/frontend               src/backend/main.py
                                 │
                                 ▼
                     [에이전트 그래프 · LangGraph]  src/backend/agent.py
                       extract → check_age → check_nap → check_departure → check_date → ready
                       (빠진 정보가 있으면 END로 빠져 되묻기)
                                 │ 입력이 모두 모이면
                                 ▼
                     [추천 엔진 · 도메인 도구]  src/backend/tools.py
                       1. 월령별 최대 이동시간 → 반경 계산
                       2. 후보 수집 (TourAPI + 카카오) → 같은 장소 병합
                       3. 장소별 병렬 평가: 편의시설 · 날씨 · 미세먼지 · 후기 · LLM 적합도 판정
                       4. 나쁜 날 판정 → 순위 → 상위 5곳
                                 │
                                 ▼
                     [결과 카드 생성]  src/backend/cards.py
```

- 외부 API 하나가 실패하거나 5초 안에 응답하지 않으면 해당 항목만 "정보를 불러오지 못함"으로 표시한다.
- API 키는 저장소 루트 `.env`에만 두고 백엔드에서만 사용한다.

## 실행 방법

요구 사항: Python 3.11+, Node.js 18+

**백엔드 (FastAPI, 포트 8000)** — 저장소 루트에서:
```bash
pip install -r requirements.txt
uvicorn backend.main:app --app-dir src --reload --port 8000
```
헬스 체크: `curl http://localhost:8000/health` → `{"status":"ok"}`

**프론트엔드 (React, 포트 5173)**
```bash
cd src/frontend
npm install
npm run dev
```
브라우저에서 http://localhost:5173 을 연다.

**테스트** — 저장소 루트에서:
```bash
python -m pytest
```

## RAGAS 평가 결과
- context_recall: 0.XX
- context_precision: 0.XX
- faithfulness: 0.XX
- answer_relevancy: 0.XX

## 인-아웃 세트 통과율 (자체 평가)
- 1차 (Day 9 종료): XX / XX 통과 — [evaluation/round1_report.md](evaluation/round1_report.md)
- 2차 (Day 10 개선 후): XX / XX 통과 — [evaluation/round2_report.md](evaluation/round2_report.md)
- 개선폭: +XX 건 (주요 개선 사항: ...)

## 트라이앤에러 회고
- 시도했지만 실패한 접근 · 왜 실패했는가
- 최종 채택한 접근 · 왜 그것으로 갔는가
- 남은 한계 · 향후 개선 방향

> 개발 과정 상세 기록은 [docs/](docs/)에 정리한다.

## 핵심 코드 위치
- [src/backend/agent.py:169](src/backend/agent.py#L169) — 메인 에이전트 그래프 (`build_graph`)
- [src/backend/tools.py:252](src/backend/tools.py#L252) — 도메인 도구 · 추천 엔진 (`recommend`, 외부 API 주입은 `Providers` :92)
- [src/backend/cards.py](src/backend/cards.py) — LLM 출력 검증 · 결과 카드 생성
- `src/backend/retriever.py` — RAG 파이프라인 (도입 예정)
