# 평가

## 인-아웃 세트 (`evaluation/test_queries.csv`)

과제 §4-4 스키마(7개 컬럼)를 따른다: `id, category, input, expected_traits, forbidden, expected_tools, note`.
UTF-8(BOM 포함)로 저장해 엑셀에서도 한글이 깨지지 않는다. 필드 안의 여러 항목은 세미콜론(`;`)으로 구분한다.

| category | 건수 | 비율 | 다루는 내용 |
|---|---|---|---|
| positive | 10 | 40% | 기본 추천, 낮잠 이동, 취향(실내), 유사 장소(서울숲), 멀티턴 되묻기, 날짜 변경, 장소 상세, 중기예보 날짜, 대략적인 출발 시각(점심 먹고), 출발 시각 변경 |
| negative | 5 | 20% | 필수 정보 없음, 월령 범위 밖, 지난 날짜, 예보 범위 밖 날짜, 출발 시각 없음 |
| edge | 6 | 24% | 애매한 출발지(시청), 서비스 범위 밖, 기준 장소 없음, 처음부터, "2살"·"비 와도" 표현, 오늘 이미 지난 출발 시각 |
| guardrail | 4 | 16% | 시스템 프롬프트·API 키 요구, 판정 기준 무시 유도, 다른 사용자 정보 요구, 출발 시각을 임의로 정하게 하는 요청 |

**출발 시각 필수화(2차 전 요건 변경):** 출발 시각이 필수 입력이 되어, 1~20번 중 추천이나 후속 요청까지 가야 하는 케이스(1~8, 15~17, 19)는 시각 질문에 답하는 턴(`오전 10시`)을 넣었다. 마지막 턴이 바뀐 케이스는 `expected_tools`를 그 턴 기준으로 맞췄다 (앞 턴에서 끝난 `geocode` 제외, 카드를 만드는 턴에 `drive_minutes` 추가). 출발 시각 자체는 21~25번 새 케이스로 검증한다. 1차(20건)와 2차(25건)를 비교할 때는 1~20번끼리 비교한다.

### 이 서비스에 맞춘 작성 규칙

- **멀티턴 입력:** 되묻기·후속 요청은 한 메시지로 표현할 수 없어서, 같은 세션으로 차례로 보낼 메시지를 `input`에 ` >> `로 이어 적는다.
  `expected_traits` · `forbidden` · `expected_tools`는 **마지막 턴의 응답** 기준이다.
- **상대 날짜:** "내일", "이번 토요일" 같은 상대 날짜를 쓴다. 날짜 범위 판단(지난 날짜, 10일 초과)은 평가하는 날 기준이다. 24번(오늘 새벽 1시 = 지난 시각)은 00~01시에 실행하면 성립하지 않는다.
- **`expected_tools` 이름:** 코드의 도구 이름과 같게 쓴다. 비어 있으면 그 턴에 외부 도구 호출이 없어야 한다는 뜻이다.

| 이름 | 하는 일 | 구현 |
|---|---|---|
| `geocode` | 출발지 좌표 확인 | `integrations/kakao.py` `geocode` |
| `tour_search` | 반경 내 관광지·문화시설·레포츠 | `integrations/tourapi.py` `location_search` |
| `kakao_search` | 반경 내 관광명소·문화시설·공원·키즈카페 | `integrations/kakao.py` `category_search` |
| `facilities` | 수유실·유모차 대여·주차, 장소 개요 | `integrations/tourapi.py` `facilities` |
| `reviews` | 블로그·카페 후기 요약문 | `integrations/naver.py` `reviews` |
| `weather` | 강수확률·기온 | `integrations/kma.py` `weather` |
| `dust` | 미세먼지 예보 | `integrations/airkorea.py` `dust` |
| `llm_judge` | 월령 적합도 판정·후기 요약 | `integrations/bedrock.py` `judge` |
| `llm_indoor_outdoor` | 실내/야외 판정 (카테고리로 정해지지 않을 때만) | `integrations/bedrock.py` `classify_indoor_outdoor` |
| `keyword_search` | 기준 장소 조회 · 취향 키워드 추가 검색 | TourAPI + 카카오 키워드 검색 |
| `embed` | 취향 매칭 임베딩 | `integrations/bedrock.py` `BedrockEmbedder.embed` |
| `drive_minutes` | 추천 후보의 차량 예상 이동시간 (출발 시각 기준 미래 교통) | `integrations/kakao.py` `drive_minutes` |

입력 추출 LLM(`extractor`)은 매 메시지마다 호출되므로 `expected_tools`에 따로 적지 않는다.

## 실행과 채점 (`evaluation/run_eval.py`)

```bash
python evaluation/run_eval.py --round 1                 # 전체 → results/round1.json + round1_report.md
python evaluation/run_eval.py --round 1 --ids 1,9       # 일부만 다시 실행해 해당 차수 결과에 합침
python evaluation/run_eval.py --round 1 --ids 1 --dry   # 출력만, 파일 저장 없음
python evaluation/run_eval.py --round 1 --report-only   # 저장된 결과로 보고서만 다시 생성
```

실제 연동 서비스(Bedrock·카카오·TourAPI·네이버·기상청·에어코리아)를 호출하므로 비용과 공공데이터 호출 한도를 쓴다.

케이스마다 새 세션으로 턴을 차례로 보내고, **마지막 턴**을 채점한다.
- **도구 검사 (규칙):** `expected_tools`가 모두 호출돼야 한다. 그 밖의 호출은 보조 도구(`llm_indoor_outdoor`, `keyword_search`, `embed`)만 허용한다. 비어 있으면 외부 호출이 없어야 한다.
- **응답 검사 (LLM 채점, Sonnet):** 사용자가 보는 응답(메시지·안내·후보·카드)을 텍스트로 펼쳐 `expected_traits` 항목별 충족 여부와 `forbidden` 항목별 위반 여부를 근거와 함께 판정한다. 채점 응답에 빠진 항목이 있으면 다시 채점한다(최대 3번).
- **통과:** 모든 기대 항목 충족 + 금지 항목 위반 없음 + 도구 검사 통과. 판정은 채점 LLM의 총평이 아니라 스크립트가 내린다.

## 자체 평가 결과
- 1차: [evaluation/round1_report.md](../evaluation/round1_report.md) — **12 / 20** (positive 3/8, negative 4/4, edge 3/5, guardrail 2/3)
- 2차: [evaluation/round2_report.md](../evaluation/round2_report.md) — **22 / 25** (positive 8/10, negative 5/5, edge 6/6, guardrail 3/4)

## RAGAS 평가

추천 시나리오를 실제 서비스로 돌리고, 나온 추천 카드마다 샘플을 만들어 잰다(ragas 0.4.3, 평가 LLM Claude Sonnet 4.6, 임베딩 Titan V2).

| 지표 | 무엇을 보나 | 샘플 |
|---|---|---|
| faithfulness | 후기 3줄 요약의 문장이 검색된 후기에 근거하는가 (정책 2 "지어내지 않는다") | 후기 요약 |
| answer_relevancy | 후기 요약이 질문에 맞는 답인가 | 후기 요약 |
| context_recall | 공식 정보(공공데이터)를 검색된 후기가 얼마나 담는가 | 후기 요약 (공공데이터가 있는 카드만) |
| context_precision | 취향 매칭 벡터 검색이 돌려준 문장이 일치도 판단에 쓸모 있고, 쓸모 있는 문장이 위에 있는가 (`LLMContextPrecisionWithoutReference`) | 취향 매칭 |

**후기 요약 샘플:** 인-아웃 세트 #1·2·3·4·8(출발지·월령이 서로 다른 추천 케이스)에서 후기 요약이 있는 카드마다 하나(`run_ragas.py collect`).

| RAGAS 필드 | 값 |
|---|---|
| user_input | "{월령} 아기와 '{장소}'에 가려고 해요. 후기를 아기 동반 관점(이용 연령, 유모차·수유실·주차, 머무는 시간, 주의할 점)으로 3줄 요약해 주세요." |
| retrieved_contexts | 요약 판정에 실제로 들어간 네이버 후기(제목 + 요약문, 최대 10건) |
| response | 카드에 표시된 3줄 요약 |
| reference | 공공데이터(TourAPI)의 편의시설 판정(있음/없음) + 개요 앞 3문장. 카카오에서만 찾은 장소는 없음 |

**취향 매칭 샘플:** 취향이 있는 인-아웃 세트 #3(실내 위주)·#4(서울숲 같은 곳)·#17(비 와도)과 시나리오 P1(동물 먹이주기 체험)·P2(숲길 산책)에서 취향 일치도가 붙은 카드마다 하나(`run_ragas.py collect-preference`).

| RAGAS 필드 | 값 |
|---|---|
| user_input | "아기와 나들이 갈 곳을 찾고 있어요. 원하는 곳: {취향 문장 또는 '서울숲' 같은 곳}. '{장소}'이(가) 여기에 맞는지 판단할 근거가 되는 장소 정보를 찾아 주세요." |
| retrieved_contexts | 그 장소의 정보 문장 중 벡터 검색이 돌려준 문장, 유사도 높은 순 (질의 문장마다 상위 2개, 서비스와 같은 방식) |
| response | 카드의 취향 일치도 ("'{장소}'의 취향 일치도는 높음입니다.") |

**결과:** context_recall 0.36 · context_precision 0.63 · faithfulness 0.89 · answer_relevancy 0.32. faithfulness는 목표(0.8)를 넘었고 context_precision은 목표(0.7)에 못 미친다.
- '비 와도 괜찮은 곳'(#17)은 Titan에서 "실내 장소입니다"와의 유사도가 0.10이라 검색 결과에 실내 문장이 들어오지 않는다. 서비스는 이때 일치도를 실내/야외 판정 규칙으로 정하지만, 이 지표는 검색 결과만 보기 때문에 0점이 된다.
- '숲길 산책'에 "산책하기 좋은 공원"이 검색된 경우처럼, 비슷한 말을 근거로 인정하지 않는 판정이 있다.
- answer_relevancy는 Titan이 한국어 유사도를 낮게 압축하는 영향이 크다(무관한 질문의 기준점 0.07).

샘플별 점수와 해석은 [evaluation/ragas_report.md](../evaluation/ragas_report.md)에 있다.

**실행:** [run.md](run.md#ragas-평가). ragas는 Python 3.14에서 설치되지 않아 채점만 Python 3.12 가상환경(`.venv-eval`)에서 돌린다.
