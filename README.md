# 미니 PJT: 아기랑 나들이 (Baby Outing Chat)

## 무엇을 푸나
아기와 나들이 갈 곳을 고를 때 거리·수유실/유모차/주차·날씨·미세먼지·후기를 여러 앱과 블로그에서 따로 찾아 맞춰 봐야 하는 번거로움을, 월령·출발지·날짜만 말하면 조건에 맞는 장소 5곳을 한 번에 추천하는 채팅으로 해결한다.

> 서비스 스펙 상세: [SERVICE.md](SERVICE.md) · 프로젝트 구조: [docs/project-structure.md](docs/project-structure.md) · API 스펙: [docs/api-spec.md](docs/api-spec.md) · 개발 문서: [docs/](docs/)

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
- 1차 (Day 9 종료): XX / XX 통과 — [evaluation/round1_report.md](evaluation/round1_report.md)
- 2차 (Day 10 개선 후): XX / XX 통과 — [evaluation/round2_report.md](evaluation/round2_report.md)
- 개선폭: +XX 건 (주요 개선 사항: ...)

## 트라이앤에러 회고
- 시도했지만 실패한 접근 · 왜 실패했는가
- 최종 채택한 접근 · 왜 그것으로 갔는가
- 남은 한계 · 향후 개선 방향

> 개발 과정 상세 기록은 [docs/](docs/)에 정리한다.

## 핵심 코드 위치
- [src/backend/agent.py:194](src/backend/agent.py#L194) — 메인 에이전트 그래프 (Supervisor, `build_graph`)
- [src/backend/tools.py](src/backend/tools.py) — 도메인 도구 (Providers 계약 · 타임아웃 · 실패 기록), 실제 구현은 [src/backend/integrations/](src/backend/integrations/)
- [src/backend/retriever.py](src/backend/retriever.py) · [src/backend/agents/preference.py](src/backend/agents/preference.py) — RAG 파이프라인 (장소 프로필 임베딩 · 취향 매칭)
- [src/backend/supervisor/pipeline.py:165](src/backend/supervisor/pipeline.py#L165) — 일임 파이프라인 (서브에이전트 실행 · 순위, `build_pipeline`)
- [src/backend/api/chat.py](src/backend/api/chat.py) — `POST /chat` 엔드포인트
- [src/backend/agents/](src/backend/agents/) — 서브에이전트 (장소 탐색 · 환경 · 후기·적합도 · 취향 매칭)
- [src/backend/prompts/](src/backend/prompts/) — LLM 프롬프트 · 답 스키마 · 답 검증
