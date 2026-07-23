FROM python:3.11-slim-bookworm
RUN apt-get update && apt-get install -y --no-install-recommends ffmpeg && rm -rf /var/lib/apt/lists/*
WORKDIR /app
COPY backend_requirements.txt .
RUN pip install --no-cache-dir -r backend_requirements.txt
COPY . .
# Sits behind the nginx TLS proxy: honor X-Forwarded-* so the app sees the real
# client IP (slowapi rate-limits the unauthenticated login routes by IP) and the
# real scheme. --forwarded-allow-ips=* is safe because port 8000 is never
# published; only nginx (on the internal network) reaches it. 1 worker to start
# (scale only on metrics, 6.1): each is a full copy incl. the ~0.5-1 GB TF model.
CMD ["uvicorn", "app.main:app", "--host", "0.0.0.0", "--port", "8000", "--proxy-headers", "--forwarded-allow-ips=*"]
