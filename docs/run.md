# 실행 방법

요구 사항: Python 3.11+, Node.js 18+

API 키는 저장소 루트의 `.env`에 둔다 (git에 올리지 않음).

### 외부 API 키 (`.env`)
| 키 | 발급처 | 비고 |
|---|---|---|
| `KAKAO_KEY` | Kakao Developers → 앱 → REST API 키 | 같은 앱에서 **카카오맵 사용 설정 ON** 필요 |
| `PUBLIC_DATA_DECODED_KEY` | 공공데이터포털 (디코딩 키) | TourAPI(국문 관광정보, 무장애 여행정보)·기상청·에어코리아 활용 신청 필요 |
| `NAVER_CLIENT_ID` / `NAVER_CLIENT_KEY` | NAVER Cloud Platform → NAVER API HUB 의 Client ID / Client Secret | 네이버 개발자센터 키가 아님 (헤더 `X-NCP-APIGW-API-KEY-ID`/`-KEY`) |

### Bedrock
- `.env`의 `AWS_ACCESS_KEY_ID`, `AWS_SECRET_ACCESS_KEY`로 인증한다. 해당 IAM 사용자에 `bedrock:InvokeModel` 권한이 있어야 한다.
- AWS 콘솔(us-east-1)의 Bedrock 모델 액세스에서 Claude Sonnet 4.6, Claude Sonnet 4.5, Claude Haiku 4.5, Titan Text Embeddings V2를 활성화해야 한다.
- 작업별 (지역, 모델) 체인 — 429면 다음 항목으로: 판정은 Sonnet만(us-west-2·ap-northeast-2·us-east-1의 Sonnet 4.6 → Sonnet 4.5), 입력 추출은 Haiku 4.5(ap-northeast-2 → us-east-1 → us-west-2), 실내/야외는 Haiku 4.5(us-west-2 → us-east-1). 세 지역 모두 Bedrock 모델 액세스가 켜져 있어야 한다. 바꾸려면 `.env`에 `BEDROCK_JUDGE_MODELS` 등을 `지역/모델ID,지역/모델ID` 형식으로 넣는다. 임베딩은 `BEDROCK_REGION`(기본 us-east-1)의 `BEDROCK_EMBED_MODEL_ID`(기본 `amazon.titan-embed-text-v2:0`).

## 백엔드 (FastAPI, 포트 8000)
저장소 루트에서:
```bash
pip install -r requirements.txt
uvicorn backend.main:app --app-dir src --reload --port 8000
```
헬스 체크: `curl http://localhost:8000/health` → `{"status":"ok"}`

## 프론트엔드 (React, 포트 5173)
```bash
cd src/frontend
npm install
npm run dev
```
브라우저에서 http://localhost:5173 을 연다.

## 채팅 API 호출 예
백엔드를 띄운 뒤:
```bash
curl -s -X POST http://localhost:8000/chat -H "Content-Type: application/json" \
     -d '{"message": "30개월 아기랑 이번 토요일에 강남역에서 출발해요"}'
# 응답의 session_id를 다음 요청에 넣으면 대화가 이어진다
curl -s -X POST http://localhost:8000/chat -H "Content-Type: application/json" \
     -d '{"session_id": "<위 응답의 session_id>", "message": "2번째 곳 더 알려줘"}'
```
연동 서비스는 첫 `/chat` 요청 때 준비된다. `.env` 키가 빠져 있으면 500 `internal error`가 돌아오고 서버 로그에 원인이 남는다.

## 테스트
저장소 루트에서:
```bash
python -m pytest
```
