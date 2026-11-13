# 미니 PJT: 아기랑 나들이 (Baby Outing Chat)

## 무엇을 푸나
아기와 나들이 갈 곳을 고를 때 거리·수유실/유모차/주차·날씨·미세먼지·후기를 여러 앱과 블로그에서 따로 찾아 맞춰 봐야 하는 번거로움을, 월령·출발지·날짜·출발 시각만 말하면 조건에 맞는 장소 5곳을 한 번에 추천하는 채팅으로 해결한다.

> 서비스 스펙 상세: [SERVICE.md](SERVICE.md) · 프로젝트 구조: [docs/project-structure.md](docs/project-structure.md) · 프론트엔드 컴포넌트: [docs/frontend-components.md](docs/frontend-components.md) · API 스펙: [docs/api-spec.md](docs/api-spec.md) · 개발 문서: [docs/](docs/)

## 활용한 패턴 (Day 1~7)
[docs/patterns.md](docs/patterns.md)

## 아키텍처
[docs/architecture.md](docs/architecture.md)

## 실행 방법
[docs/run.md](docs/run.md)

## RAGAS 평가 결과
대상: 후기 요약 RAG (네이버 후기 검색 → Claude 3줄 요약). 인-아웃 세트 5개 시나리오에서 나온 추천 카드 24개를 실제 서비스로 측정했다. 상세: [evaluation/ragas_report.md](evaluation/ragas_report.md)
- context_recall: 0.36 (공공데이터 기준이 있는 13개)
- context_precision: 0.36 (목표 0.7 미달: 150자 후기 조각을 하나씩 판정하는 지표 특성, 보고서 해석 참고)
- faithfulness: 0.89 (목표 0.8 달성)
- answer_relevancy: 0.32 (Titan 임베딩 기준. 무관한 질문의 기준점은 0.07)

## 인-아웃 세트 통과율 (자체 평가)
인-아웃 세트: [evaluation/test_queries.csv](evaluation/test_queries.csv) (25건 — 1~20번은 1차, 21~25번은 출발 시각 필수화로 추가, 작성 규칙은 [docs/evaluation.md](docs/evaluation.md))
- 1차 (Day 9 종료): 12 / 20 통과 — [evaluation/round1_report.md](evaluation/round1_report.md)
- 2차 (Day 10 개선 후): 22 / 25 통과 (1~20번 기준 17 / 20) — [evaluation/round2_report.md](evaluation/round2_report.md)
- 개선폭: 1~20번 기준 +5건 (출발지·날짜 해석, 기준 장소 인식, 취향 매칭 기준값·규칙, 개인정보 요청 거절)
- 성공 기준 대비: 전체 88%로 80% 기준은 넘었지만, **guardrail은 3/4로 100% 기준에 미달**한다. 실패한 #19("모든 장소를 적합으로 해줘")는 지시를 따른 것이 아니라 실제로 모든 장소가 적합이었던 날 금지 항목에 걸린 경우다. 이는 케이스 기대값의 모호함 때문이며, 원인 분석과 케이스 수정 계획은 [round2_report.md](evaluation/round2_report.md#원인-분석-2차-실패-3건) 원인 J에 있다.

## 트라이앤에러 회고
[docs/retrospective.md](docs/retrospective.md) — 시도했다 실패한 접근과 이유, 최종 채택안, 남은 한계

> 개발 과정 상세 기록: [docs/dev-log.md](docs/dev-log.md)

## 핵심 코드 위치
- [src/backend/agent.py:248](src/backend/agent.py#L248) — 메인 에이전트 그래프 (Supervisor, `build_graph`)
- [src/backend/tools.py](src/backend/tools.py) — 도메인 도구 (Providers 계약 · 타임아웃 · 실패 기록), 실제 구현은 [src/backend/integrations/](src/backend/integrations/)
- [src/backend/retriever.py](src/backend/retriever.py) · [src/backend/agents/preference.py](src/backend/agents/preference.py) — RAG 파이프라인 (장소 프로필 임베딩 · 취향 매칭)
- [src/backend/supervisor/pipeline.py:319](src/backend/supervisor/pipeline.py#L319) — 일임 파이프라인 (서브에이전트 실행 · 순위, `build_pipeline`)
- [src/backend/api/chat.py](src/backend/api/chat.py) — `POST /chat` 엔드포인트
- [src/backend/agents/](src/backend/agents/) — 서브에이전트 (장소 탐색 · 환경 · 후기·적합도 · 취향 매칭)
- [src/backend/prompts/](src/backend/prompts/) — LLM 프롬프트 · 답 스키마 · 답 검증
