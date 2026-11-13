# Baby Outing Chat: one container = FastAPI backend + the built React frontend (same origin).
#   docker build -t baby-outing . && docker run -p 8000:8000 --env-file .env baby-outing

# 1) frontend build (Node 22.18+: `npm test` runs .ts files with node --test)
FROM node:22-slim AS frontend
WORKDIR /app/src/frontend
COPY src/frontend/package.json src/frontend/package-lock.json ./
RUN npm ci
COPY src/frontend/ ./
RUN npm run build

# 2) backend (Python 3.12) + the frontend build in src/frontend/dist
FROM python:3.12-slim
ENV PYTHONDONTWRITEBYTECODE=1 PYTHONUNBUFFERED=1
WORKDIR /app
COPY requirements.txt ./
RUN pip install --no-cache-dir -r requirements.txt
COPY src/backend/ src/backend/
COPY --from=frontend /app/src/frontend/dist src/frontend/dist
# Render sets PORT; 8000 locally
EXPOSE 8000
CMD ["sh", "-c", "uvicorn backend.main:app --app-dir src --host 0.0.0.0 --port ${PORT:-8000}"]
