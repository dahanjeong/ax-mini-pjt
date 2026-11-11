# 아기와 나들이 추천 채팅

로컬에서 실행하는 데모입니다 (배포 없음). React 개발 서버 + FastAPI 서버로 구성됩니다.
외부 API 키는 저장소 루트의 `.env`에만 두며 백엔드에서만 사용합니다. 프론트엔드에는 키가 없습니다.
대화 기록은 서버 메모리에만 저장되며 재시작 시 사라집니다.

## 요구 사항
- Python 3.11+
- Node.js 18+

## 백엔드 실행 (FastAPI, 포트 8000)
저장소 루트에서:

```bash
pip install -r backend/requirements.txt
uvicorn backend.app.main:app --reload --port 8000
```

헬스 체크: `curl http://localhost:8000/health` → `{"status":"ok"}`

## 프론트엔드 실행 (React, 포트 5173)
```bash
cd frontend
npm install
npm run dev
```
브라우저에서 http://localhost:5173 을 엽니다.

## 테스트
저장소 루트에서:

```bash
python -m pytest
```
