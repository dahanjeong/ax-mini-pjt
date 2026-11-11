# API 스펙

백엔드: FastAPI (`http://localhost:8000`). 모든 요청·응답은 `application/json` (UTF-8).

| 메서드 | 경로 | 설명 | 상태 |
|---|---|---|---|
| GET | `/health` | 서버 상태 확인 | 구현됨 |
| POST | `/chat` | 채팅 1턴 처리 (되묻기 또는 장소 추천) | 예정 |

응답 구조는 현재 코드의 출력 그대로다.
- 되묻기: [src/backend/agent.py](../src/backend/agent.py) `chat_turn`
- 추천: [src/backend/agent.py](../src/backend/agent.py) `recommendation_turn`, [src/backend/supervisor/pipeline.py](../src/backend/supervisor/pipeline.py) `recommend`
- 결과 카드: [src/backend/supervisor/cards.py](../src/backend/supervisor/cards.py) `build_card`

---

## GET /health

**Response 200**
```json
{"status": "ok"}
```

---

## POST /chat

사용자 메시지 1개로 에이전트를 한 턴 실행한다.
- 월령·출발지·날짜 중 빠지거나 잘못된 정보가 있으면 되묻는다 (`status: "ask"`).
- 정보가 모두 모이면 장소를 추천한다 (`status: "ready"`).

### Request

| 필드 | 타입 | 필수 | 설명 |
|---|---|---|---|
| `session_id` | string | X | 이어서 대화할 세션 ID (LangGraph `thread_id`). 없으면 서버가 새로 만든다 |
| `message` | string | O | 사용자 메시지 |

```json
{"session_id": "3f2a9c1e-...", "message": "18개월 아기랑 이번 토요일에 강남역에서 출발해요"}
```

세션은 서버 메모리에만 보관하며, 서버가 재시작되면 사라진다.

### Response 200 — 공통 필드

| 필드 | 타입 | 설명 |
|---|---|---|
| `session_id` | string | 이 대화의 세션 ID. 다음 요청에 그대로 보낸다 |
| `status` | `"ask"` \| `"ready"` | 되묻기 / 추천 완료 (장소 상세 응답도 `ready`) |
| `intent` | string | 판정한 의도: `ask`, `new_search`, `change_date`, `change_departure`, `change_age`, `change_preference`, `similar_place`, `no_change`, `place_detail`, `reset`, `out_of_scope` |
| `reply` | string \| null | 에이전트 응답 문구 (되묻기 질문 등) |
| `messages` | string[] | 화면에 순서대로 보여줄 메시지 (`reply` + 추천 진행 메시지) |
| `notice` | string \| null | 안내 문구 (예: 조회 가능한 날짜 안내, 장소가 5곳 미만) |
| `missing_inputs` | string[] | 빠진 정보: `baby_age_months`, `departure_location`, `outing_date` |
| `candidates` | array | 출발지가 애매할 때 후보 목록 |
| `available_date_range` | object \| null | 날짜가 범위 밖일 때 조회 가능 범위 |
| `baby_age_months` | number \| null | 확인된 월령 |
| `travels_during_nap` | boolean \| null | 낮잠 시간에 이동하는지 |
| `departure_location` | object \| null | 확인된 출발지 (`lat`, `lng` 포함) |
| `outing_date` | string \| null | 확인된 날짜 (YYYY-MM-DD) |
| `preference_text` | string \| null | 확인된 취향 문장 |
| `reference_place` | string \| null | "비슷한 곳" 요청의 기준 장소명 |
| `reference_candidates` | array | 기준 장소 이름이 여러 곳일 때 후보 목록 `[{name, address}]` (번호나 이름으로 고름) |

### Response 200 — 추천 필드 (`status: "ready"`일 때만)

| 필드 | 타입 | 설명 |
|---|---|---|
| `result_cards` | array | 추천 장소 카드 (최대 5개, 순위순). 아래 [결과 카드](#결과-카드) |
| `max_drive_hours` | number | 월령별 최대 이동시간 (시간) |
| `radius_km` | number | 실제 사용한 검색 반경 (km) |
| `radius_expanded` | boolean | 후보가 부족해 반경을 1.5배로 넓혔는지 |
| `failed_sources` | string[] | 실패하거나 시간 초과(5초)된 외부 API |
| `elapsed_s` | number | 추천에 걸린 시간 (초) |
| `preference_status` | string | 취향 매칭 상태: `off`(취향 없음) · `ok` · `unavailable`(임베딩 미설정) · `failed`(임베딩 실패, 기본 순위) |

### 예시 1 — 되묻기

```json
// Request
{"message": "아기랑 나들이 갈 곳 추천해줘"}

// Response
{
  "session_id": "3f2a9c1e-...",
  "status": "ask",
  "reply": "아기가 몇 개월인가요?",
  "messages": ["아기가 몇 개월인가요?"],
  "notice": null,
  "missing_inputs": ["baby_age_months", "departure_location", "outing_date"],
  "candidates": [],
  "available_date_range": null,
  "baby_age_months": null,
  "travels_during_nap": null,
  "departure_location": null,
  "outing_date": null
}
```

### 예시 2 — 추천

```json
// Request
{"session_id": "3f2a9c1e-...", "message": "18개월이고 이번 토요일에 강남역에서 출발해요"}

// Response
{
  "session_id": "3f2a9c1e-...",
  "status": "ready",
  "reply": null,
  "messages": [
    "주변 장소를 찾고 있어요...",
    "날씨·편의시설·후기를 확인해 순위를 정했어요."
  ],
  "notice": null,
  "missing_inputs": [],
  "candidates": [],
  "available_date_range": null,
  "baby_age_months": 18,
  "travels_during_nap": false,
  "departure_location": {"lat": 37.4979, "lng": 127.0276},
  "outing_date": "2026-11-14",
  "result_cards": [ /* 결과 카드 최대 5개 */ ],
  "max_drive_hours": 1.5,
  "radius_km": 46.2,
  "radius_expanded": false,
  "failed_sources": [],
  "elapsed_s": 12.4
}
```

### 결과 카드

| 필드 | 타입 | 설명 |
|---|---|---|
| `name` | string | 장소명 |
| `distance_km` | number | 출발지와의 직선거리 (소수 1자리) |
| `indoor_outdoor` | `"indoor"` \| `"outdoor"` | 실내/야외 |
| `age_suitability` | `"적합"` \| `"보통"` | 월령 적합도 (`"부적합"`은 결과에서 제외) |
| `facilities` | object | `nursing_room`, `stroller_rental`, `parking` 각각 `{label, status, source}` |
| `facilities.*.status` | string | `있음` · `없음` · `정보 없음` · `정보를 불러오지 못함` |
| `weather` | object | `{forecast_source, precip_prob_max, temp_max, temp_min}`, 실패 시 `{status}` |
| `dust` | object | `{pm10_grade, pm25_grade}`, 예보 없음 시 `{status}` |
| `is_bad_day` | boolean | 비·미세먼지 나쁨·폭염·한파 여부 |
| `warnings` | string[] | 경고 문구 (나쁜 날의 야외 장소) |
| `review_summary` | string[] | 후기 3줄 요약 (없으면 `["후기 정보 없음"]`) |
| `failed_sources` | string[] | 이 장소에서 실패한 외부 API |
| `includes` | string[] | 같은 시설로 묶인 세부 장소 이름 (예: 서울대공원의 어린이동물원·제1아프리카관). 없으면 `[]` |
| `preference_match` | object \| null | 취향을 말한 경우 `{level: "높음"\|"보통"\|"낮음", evidence: [{doc_id, text}]}` (근거 문장 최대 2개). 취향이 없으면 `null` |

### 오류

외부 API가 일부 실패해도 **200**으로 응답하고 해당 항목만 `"정보를 불러오지 못함"`으로 표시한다.

| 코드 | 상황 |
|---|---|
| 422 | `message`가 없거나 빈 문자열 |
| 500 | 처리 중 예기치 못한 오류 (내부 정보·API 키 노출 금지) |

---

## 보안
- 외부 API 키는 백엔드 `.env`에서만 읽고, 응답과 프론트엔드에 넣지 않는다.
- CORS는 로컬 프론트엔드(`http://localhost:5173`, `http://127.0.0.1:5173`)만 허용한다.
