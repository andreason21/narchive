FROM python:3.12-slim

WORKDIR /app

# 백엔드 의존성
COPY backend/requirements.txt /app/requirements.txt
RUN pip install --no-cache-dir -r requirements.txt

# 백엔드 + 프론트엔드 코드 복사
COPY backend /app/backend
COPY frontend /app/frontend

# Cloud Run은 PORT 환경변수 주입
ENV PORT=8080
EXPOSE 8080

WORKDIR /app/backend
CMD ["sh", "-c", "uvicorn main:app --host 0.0.0.0 --port ${PORT}"]
