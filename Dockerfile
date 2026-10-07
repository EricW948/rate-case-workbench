# Rate Case Workbench — hosted deploy image (Railway).
# Railway: attach a volume at /data and set RATECASE_DB=/data/ratecase.db so the
# SQLite database survives redeploys. Set APP_PASSWORD to lock the app behind
# the team sign-in. Railway injects $PORT automatically.
FROM python:3.12-slim

ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1

WORKDIR /srv/app

COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

COPY . .

# Render (and most hosts) inject $PORT; default to 8000 for local runs.
CMD ["sh", "-c", "uvicorn main:app --host 0.0.0.0 --port ${PORT:-8000}"]
