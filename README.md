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
- context_recall: 0.XX
- context_precision: 0.XX
- faithfulness: 0.XX
- answer_relevancy: 0.XX

## 인-아웃 세트 통과율 (자체 평가)
인-아웃 세트: [evaluation/test_queries.csv](evaluation/test_queries.csv) (25건 — 1~20번은 1차, 21~25번은 출발 시각 필수화로 추가, 작성 규칙은 [docs/evaluation.md](docs/evaluation.md))
- 1차 (Day 9 종료): 12 / 20 통과 — [evaluation/round1_report.md](evaluation/round1_report.md)
- 2차 (Day 10 개선 후): 22 / 25 통과 (1~20번 기준 17 / 20) — [evaluation/round2_report.md](evaluation/round2_report.md)
- 개선폭: 1~20번 기준 +5건 (출발지·날짜 해석, 기준 장소 인식, 취향 매칭 기준값·규칙, 개인정보 요청 거절)

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
