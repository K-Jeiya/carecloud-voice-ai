FROM python:3.12-slim

ENV PYTHONDONTWRITEBYTECODE=1 PYTHONUNBUFFERED=1
WORKDIR /app

COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

COPY app ./app
COPY dashboard ./dashboard
RUN mkdir -p /app/data

# Default SQLite path lives in /app/data -> mount a persistent volume there in production,
# or set DATABASE_URL to a managed PostgreSQL instance.
ENV DATABASE_URL=sqlite:////app/data/patients.db
EXPOSE 8000

# $PORT is injected by Render/Railway/Fly; fall back to 8000 locally.
CMD ["sh", "-c", "uvicorn app.main:app --host 0.0.0.0 --port ${PORT:-8000}"]
