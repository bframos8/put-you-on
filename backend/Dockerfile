FROM python:3.11-slim-bookworm
RUN apt-get update && apt-get install -y --no-install-recommends ffmpeg && rm -rf /var/lib/apt/lists/*
WORKDIR /app
COPY backend_requirements.txt .
RUN pip install --no-cache-dir -r backend_requirements.txt
COPY . .
# Run as an unprivileged user — a container escape or RCE shouldn't land as root.
# spotdl downloads audio under app/services/downloads (created at runtime), so that
# dir alone must be writable by `app`; the rest of /app stays root-owned/read-only.
RUN useradd --create-home app \
    && mkdir -p /app/app/services/downloads \
    && chown app:app /app/app/services/downloads
USER app
# Container self-health via the existing /health endpoint (app/api/v1/health.py).
# Uses the image's own Python (no curl in the base image → no extra package). A
# non-200 or any exception (connection refused, timeout) exits non-zero = unhealthy.
# --start-period covers the TF model load at boot so startup isn't counted as failing.
HEALTHCHECK --interval=30s --timeout=5s --start-period=40s --retries=3 \
    CMD ["python", "-c", "import urllib.request,sys; sys.exit(0 if urllib.request.urlopen('http://localhost:8000/health', timeout=4).status==200 else 1)"]
# Sits behind the nginx TLS proxy: honor X-Forwarded-* so the app sees the real
# client IP (slowapi rate-limits the unauthenticated login routes by IP) and the
# real scheme. --forwarded-allow-ips=* is safe because port 8000 is never
# published; only nginx (on the internal network) reaches it. 1 worker to start
# (scale only on metrics, 6.1): each is a full copy incl. the ~0.5-1 GB TF model.
CMD ["uvicorn", "app.main:app", "--host", "0.0.0.0", "--port", "8000", "--proxy-headers", "--forwarded-allow-ips=*"]
