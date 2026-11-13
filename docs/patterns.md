# 활용한 패턴 (Day 1~7)

## 적용한 패턴

| 패턴 | Day | 이 프로젝트에서 적용한 방식 | 코드 |
|---|---|---|---|
| 구조화 출력 | Day 1 | 월령 적합도 판정·후기 3줄 요약·입력 추출·실내/야외 분류를 LLM이 정해진 도구 하나를 강제로 호출하게 해서 고정 JSON 형식으로만 받고, 받은 값을 다시 검증한다. LCEL 체인 대신 Anthropic SDK의 도구 강제 호출을 쓴다. | `integrations/bedrock.py`, `prompts/` |
| RAG | Day 2 | 장소 정보(분류·소개·편의시설·후기 요약)를 문장 단위 문서로 나눠 Titan 임베딩으로 메모리 벡터 저장소를 만들고, 사용자 취향 문장·기준 장소("서울숲 같은 곳")와의 코사인 유사도로 취향 일치도(높음/보통/낮음)와 근거 문장을 고른다. "높음"이 3곳보다 적으면 취향 키워드로 장소를 한 번 더 검색해 후보를 보강한다. 하이브리드 검색·리랭킹 모델은 쓰지 않는다. | `retriever.py`, `agents/preference.py`, `supervisor/pipeline.py` (`augment`) |
| 도구 다중 | Day 4 | 한 번의 추천 요청에 카카오 로컬·TourAPI·기상청·에어코리아·네이버 검색·Bedrock을 함께 호출한다. 도구는 `Providers`로 주입하고 장소별로 병렬 호출하며, 실패한 도구는 해당 정보만 "불러오지 못함"으로 표시한다. 어떤 도구를 부를지는 LLM이 아니라 파이프라인이 정한다. | `tools.py`, `integrations/` |
| 가드레일 | Day 5 | 필수 정보(월령·출발지·날짜·출발 시각) 되묻기와 24개월 미만이면 낮잠 시간 이동 여부 한 번 묻기, 근거 없는 내용은 "정보 없음"으로 표시(지어내기 금지), 후기·사용자 메시지 속 지시문 무시(프롬프트 인젝션 방어), 서비스 범위 밖 질문 거절, 프론트엔드에 비밀값 비노출(테스트로 확인). | `agent.py`, `prompts/`, `tests/test_frontend_no_secrets.py` |
| 미들웨어 (재시도) | Day 5 | LLM 호출의 429·5xx는 지수 백오프로 재시도한 뒤 다른 리전·모델로 넘어가고, 모델별 동시 호출 수를 제한한다. 외부 API 호출은 모두 시간 제한을 둔다. 대화 요약·PII 마스킹은 적용하지 않았다. | `integrations/bedrock.py`, `tools.py` |
| Multi-Agent Supervisor | Day 6 | 슈퍼바이저 그래프가 대화를 이해하고 필요한 정보를 모은 뒤 장소 검색·환경(날씨·미세먼지)·후기·취향 서브 에이전트에 위임한다. 후보별 평가는 `Send`로 병렬 실행한다. | `agent.py`, `supervisor/pipeline.py`, `agents/` |
| 평가 (LLM-as-Judge) | Day 7 | 인-아웃 세트 25건(`evaluation/test_queries.csv`)을 실제 서비스로 돌리고, 도구 호출은 규칙으로, 답변은 Sonnet 채점기로 항목별(기대 특성 충족·금지 사항 위반) 판정한다. RAGAS로는 후기 요약 RAG(네이버 후기 검색 → Claude 3줄 요약)의 context_recall·faithfulness·answer_relevancy와, 취향 매칭 RAG(장소 정보 벡터 검색)의 context_precision을 따로 잰다. | `evaluation/run_eval.py`, `evaluation/run_ragas.py`, [evaluation.md](evaluation.md) |
