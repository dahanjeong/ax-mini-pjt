# API 스펙

백엔드: FastAPI (`http://localhost:8000`). 모든 요청·응답은 `application/json` (UTF-8).

| 메서드 | 경로 | 설명 | 상태 |
|---|---|---|---|
| GET | `/health` | 서버 상태 확인 | 구현됨 |
| POST | `/chat` | 채팅 1턴 처리 (되묻기 또는 장소 추천) | 구현됨 ([src/backend/api/chat.py](../src/backend/api/chat.py)) |

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
- 월령·출발지·날짜·출발 시각 중 빠지거나 잘못된 정보가 있으면 되묻는다 (`status: "ask"`). 출발 시각이 없으면 "대략 언제쯤 출발할 예정이신가요?"라고 묻는다.
- 정보가 모두 모이면 장소를 추천한다 (`status: "ready"`).

### Request

| 필드 | 타입 | 필수 | 설명 |
|---|---|---|---|
| `session_id` | string | X | 이어서 대화할 세션 ID (LangGraph `thread_id`, 최대 100자). 없으면 서버가 새로 만든다. 모르는 ID면 새 대화로 시작한다 |
| `message` | string | O | 사용자 메시지 (1~500자, 앞뒤 공백 제거) |

```json
{"session_id": "3f2a9c1e-...", "message": "18개월 아기랑 이번 토요일 오전 10시에 강남역에서 출발해요"}
```

세션은 서버 메모리에만 보관하며, 서버가 재시작되면 사라진다.

### Response 200 — 공통 필드

| 필드 | 타입 | 설명 |
|---|---|---|
| `session_id` | string | 이 대화의 세션 ID. 다음 요청에 그대로 보낸다 |
| `status` | `"ask"` \| `"ready"` | 되묻기 / 추천 완료 (장소 상세 응답도 `ready`) |
| `intent` | string | 판정한 의도: `ask`, `new_search`, `change_date`, `change_time`(출발 시각만 변경 → 이동시간만 재확인), `change_exclusion`(제외 조건 추가 → 저장된 후보에서 빼고 재순위, 5곳 미만이면 반경 확대), `change_inclusion`(추가 요청 → 그 종류를 목록에 넣음, 후보에 없으면 키워드 검색), `change_departure`, `change_age`, `change_preference`, `similar_place`, `no_change`, `place_detail`, `reset`, `out_of_scope`, `privacy`(다른 사용자의 대화 기록·출발지 등을 요구 → 거절하고 본인 입력 유도) |
| `reply` | string \| null | 에이전트 응답 문구 (되묻기 질문 등) |
| `messages` | string[] | 화면에 순서대로 보여줄 메시지 (`reply` + 추천 진행 메시지) |
| `notice` | string \| null | 안내 문구 (예: 조회 가능한 날짜 안내, 장소가 5곳 미만) |
| `missing_inputs` | string[] | 빠진 정보: `baby_age_months`, `travels_during_nap`(24개월 미만일 때 한 번), `departure_location`, `outing_date`, `departure_time`, `reference_place`(기준 장소를 못 찾았거나 여러 곳일 때) |
| `candidates` | array | 출발지가 애매할 때 후보 목록 |
| `available_date_range` | object \| null | 날짜가 범위 밖일 때 조회 가능 범위 |
| `baby_age_months` | number \| null | 확인된 월령 |
| `travels_during_nap` | boolean \| null | 낮잠 시간에 이동하는지 |
| `departure_location` | object \| null | 확인된 출발지 (`lat`, `lng` 포함) |
| `outing_date` | string \| null | 확인된 날짜 (YYYY-MM-DD) |
| `departure_time` | string \| null | 확인된 출발 시각 (HH:MM, KST). 차량 이동시간 예측 기준 |
| `exclude_keywords` | string[] | 제외 조건: 장소 종류(`물놀이`·`키즈카페`·`실내`·`야외` 등) 또는 추천 카드의 장소 이름. "처음부터" 전까지 유지 |
| `include_keywords` | string[] | 추가 요청한 장소 종류 ("물놀이 장소도 추천해주세요" → `물놀이`). 같은 종류의 제외 조건은 풀린다 |
| `preference_text` | string \| null | 확인된 취향 문장 |
| `reference_place` | string \| null | "비슷한 곳" 요청의 기준 장소명 |
| `reference_candidates` | array | 기준 장소 이름이 여러 곳일 때 후보 목록 `[{name, address}]` (번호나 이름으로 고름) |

### Response 200 — 추천 필드 (이번 턴에 추천을 실행했을 때만, 아니면 `null`)

| 필드 | 타입 | 설명 |
|---|---|---|
| `result_cards` | array | 추천 장소 카드 (최대 5개, 순위순). 아래 [결과 카드](#결과-카드) |
| `max_drive_hours` | number | 월령별 최대 이동시간 (시간) |
| `radius_km` | number | 실제 사용한 후보 검색 반경 (km). 반경은 후보를 모으는 근사치이고, 추천 여부는 카드의 `drive`(실제 차량 예상 이동시간)로 정한다 |
| `radius_expanded` | boolean | 후보가 부족해 반경을 1.5배로 넓혔는지 |
| `failed_sources` | string[] | 실패하거나 시간 초과(5초)된 외부 API (`tourapi` · `kakao` · `kakao_navi`(이동시간) · `public_data` · `naver` · `kma` · `airkorea` · `llm` · `embedding` · `keyword_search`) |
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
  "intent": "ask",
  "reply": "아기는 몇 개월인가요? (0~72개월)",
  "messages": ["아기는 몇 개월인가요? (0~72개월)"],
  "notice": null,
  "missing_inputs": ["baby_age_months", "departure_location", "outing_date", "departure_time"],
  "candidates": [],
  "available_date_range": null,
  "baby_age_months": null,
  "travels_during_nap": null,
  "departure_location": null,
  "outing_date": null,
  "departure_time": null,
  "exclude_keywords": [],
  "include_keywords": [],
  "preference_text": null,
  "reference_place": null,
  "reference_candidates": [],
  "result_cards": null,
  "max_drive_hours": null,
  "radius_km": null,
  "radius_expanded": null,
  "failed_sources": null,
  "elapsed_s": null,
  "preference_status": null
}
```

### 예시 2 — 추천

18개월이라 낮잠 질문("이동이 아기 낮잠 시간과 겹치나요?")에 "아니요"로 답한 뒤, 출발 시각을 말한 턴이다.

```json
// Request
{"session_id": "3f2a9c1e-...", "message": "오전 10시"}

// Response
{
  "session_id": "3f2a9c1e-...",
  "status": "ready",
  "intent": "new_search",
  "reply": "입력이 모두 확인됐어요 (18개월, 강남역 출발, 2026-11-14 10:00). 추천 장소를 찾아볼게요!",
  "messages": [
    "입력이 모두 확인됐어요 (18개월, 강남역 출발, 2026-11-14 10:00). 추천 장소를 찾아볼게요!",
    "주변 장소를 찾고 있어요...",
    "추천 후보의 실제 차량 이동시간을 확인하고 있어요...",
    "날씨·편의시설·후기를 확인해 순위를 정했어요."
  ],
  "notice": null,
  "missing_inputs": [],
  "candidates": [],
  "available_date_range": {"start": "2026-11-11", "end": "2026-11-21"},
  "baby_age_months": 18,
  "travels_during_nap": false,
  "departure_location": {"name": "강남역 2호선", "address": "서울 강남구 강남대로 396", "lat": 37.4979, "lng": 127.0276},
  "outing_date": "2026-11-14",
  "departure_time": "10:00",
  "exclude_keywords": [],
  "include_keywords": [],
  "preference_text": null,
  "reference_place": null,
  "reference_candidates": [],
  "result_cards": [
    {
      "name": "온동물체험농장",
      "image": "https://tong.visitkorea.or.kr/cms/resource/57/3514757_image2_1.jpg",
      "distance_km": 25.1,
      "drive": {"status": "확인됨", "minutes": 42, "departure_time": "2026-11-14T10:00"},
      "indoor_outdoor": "indoor",
      "age_suitability": "적합",
      "facilities": {
        "nursing_room": {"label": "수유실", "status": "정보 없음", "source": null},
        "stroller_rental": {"label": "유모차 대여", "status": "정보 없음", "source": null},
        "parking": {"label": "주차", "status": "있음", "source": "public_data"}
      },
      "weather": {"forecast_source": "short_term", "precip_prob_max": 60, "temp_max": 14, "temp_min": 11},
      "dust": {"forecast_source": "daily", "pm10_grade": "보통", "pm25_grade": "보통"},
      "is_bad_day": false,
      "warnings": [],
      "review_summary": [
        "18개월·32개월 아기와 방문한 후기가 있으며, 24개월 미만은 입장료 무료.",
        "동물 먹이 주기 체험과 모래놀이터를 즐길 수 있고, 실내라 우천 시에도 방문 가능하다.",
        "약 2시간 머물렀다는 후기가 많고, 전자레인지와 아기의자가 있다."
      ],
      "review_sources": [{"title": "34개월 아기랑 시흥 온동물체험농장", "link": "https://blog.naver.com/...", "source": "blog"}],
      "failed_sources": [],
      "preference_match": null,
      "includes": []
    }
    /* … 최대 5개 */
  ],
  "max_drive_hours": 1.5,
  "radius_km": 46.2,
  "radius_expanded": false,
  "failed_sources": [],
  "elapsed_s": 24.8,
  "preference_status": "off"
}
```

### 결과 카드

| 필드 | 타입 | 설명 |
|---|---|---|
| `name` | string | 장소명 |
| `image` | string \| null | 대표 사진 URL (한국관광공사 TourAPI `firstimage`, https로 바꿔서 줌). TourAPI에 사진이 없거나 카카오에서만 찾은 장소는 `null`이며, 화면은 기본 이미지를 보여준다 |
| `distance_km` | number | 출발지와의 직선거리 (소수 1자리) |
| `drive` | object | 차량 예상 이동시간 `{status, minutes, departure_time}`. `departure_time`(`"YYYY-MM-DDTHH:MM"`, KST)은 계산 기준 출발 시각(나들이 날짜 + 사용자가 말한 출발 시각)이며, 그 시각의 미래 교통 예측으로 계산한다. `status: "확인됨"`이면 `minutes`(정수, 분, 월령별 최대 이동시간 이하), `"이동시간 확인 필요"`이면 `minutes: null` (길찾기 실패·확인 한도 초과로 반경 기준으로만 추린 후보, 월령별 반경 안의 장소만) |
| `indoor_outdoor` | `"indoor"` \| `"outdoor"` | 실내/야외 |
| `age_suitability` | `"적합"` \| `"보통"` | 월령 적합도 (`"부적합"`은 결과에서 제외) |
| `facilities` | object | `nursing_room`, `stroller_rental`, `parking` 각각 `{label, status, source}` |
| `facilities.*.status` | string | `있음` · `없음` · `정보 없음` · `정보를 불러오지 못함` |
| `weather` | object | `{forecast_source, precip_prob_max, temp_max, temp_min}`, 실패 시 `{status}` |
| `dust` | object | `{forecast_source, pm10_grade, pm25_grade}` (`forecast_source`: `"daily"` 일별 예보 · `"weekly"` 주간 예보), 예보 없음 시 `{status}` |
| `is_bad_day` | boolean | 비·미세먼지 나쁨·폭염·한파 여부 |
| `warnings` | string[] | 경고 문구 (나쁜 날의 야외 장소) |
| `review_summary` | string[] | 후기 3줄 요약 (없으면 `["후기 정보 없음"]`) |
| `review_sources` | array | 요약에 쓴 후기 원문 링크 `[{title, link, source}]` (최대 3개, `link`는 http(s)만, `source`는 `"blog"` \| `"cafe"` \| `null`). 후기가 없으면 `[]` |
| `failed_sources` | string[] | 이 장소에서 실패한 외부 API |
| `includes` | string[] | 같은 시설로 묶인 세부 장소 이름 (예: 서울대공원의 어린이동물원·제1아프리카관). 없으면 `[]` |
| `preference_match` | object \| null | 취향을 말한 경우 `{level: "높음"\|"보통"\|"낮음", evidence: [{doc_id, text}]}` (근거 문장 최대 2개). 취향이 없으면 `null` |

### 오류

외부 API가 일부 실패해도 **200**으로 응답하고 해당 항목만 `"정보를 불러오지 못함"`으로 표시한다.

| 코드 | 상황 |
|---|---|
| 422 | `message`가 없거나 공백뿐이거나 500자 초과, `session_id`가 100자 초과 |
| 500 | 처리 중 예기치 못한 오류, 또는 서버가 연동 서비스를 준비하지 못함(`.env` 키 누락 등). 응답은 항상 `{"detail": "internal error"}`이고 원인은 서버 로그에만 남긴다 (내부 정보·API 키 노출 금지) |

---

## 보안
- 외부 API 키는 백엔드 `.env`에서만 읽고, 응답과 프론트엔드에 넣지 않는다.
- CORS는 로컬 프론트엔드(`http://localhost`, `http://127.0.0.1`의 모든 포트)만 허용한다. 5173이 사용 중이면 Vite가 5174 등으로 옮겨 가기 때문이다. 배포에서는 프론트를 백엔드가 같은 주소로 제공하므로 CORS가 필요 없다.
- 환경변수 `APP_PASSWORD`가 있으면 `/health`를 뺀 모든 경로(화면·`/chat`)에 HTTP Basic 인증이 걸린다(사용자 이름 `APP_USERNAME`, 기본 `family`). 없으면 인증 없이 열린다(로컬 개발). 인증 실패는 401.
