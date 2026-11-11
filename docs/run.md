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
- AWS 콘솔(us-east-1)의 Bedrock 모델 액세스에서 Claude Sonnet 4.6, Claude Haiku 4.5, Titan Text Embeddings V2를 활성화해야 한다.
- 기본값: 지역 `us-east-1`, 판정 모델 `global.anthropic.claude-sonnet-4-6`, 추출·분류 모델 `global.anthropic.claude-haiku-4-5-20251001-v1:0`, 임베딩 `amazon.titan-embed-text-v2:0`. 바꾸려면 `.env`에 `BEDROCK_REGION`, `BEDROCK_MODEL_ID`, `BEDROCK_FAST_MODEL_ID`, `BEDROCK_EMBED_MODEL_ID`를 넣는다.

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

## 테스트
저장소 루트에서:
```bash
python -m pytest
```
