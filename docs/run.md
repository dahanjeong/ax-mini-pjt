# 실행 방법

요구 사항: Python 3.11+, Node.js 18+

API 키는 저장소 루트의 `.env`에 둔다 (git에 올리지 않음).

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
