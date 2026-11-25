# ============================================================
# Production Dockerfile — multi-stage, non-root, healthcheck
# ============================================================

# ---------- Stage 1: builder — cài dependencies vào virtualenv ----------
FROM python:3.11-slim AS builder

WORKDIR /build
RUN python -m venv /opt/venv
# Dùng pip của venv (không dùng --user) để runtime chỉ cần copy cả thư mục /opt/venv
COPY requirements.txt .
RUN /opt/venv/bin/pip install --no-cache-dir -r requirements.txt

# ---------- Stage 2: runtime — chỉ chứa venv + code ----------
FROM python:3.11-slim AS runtime

ENV PATH="/opt/venv/bin:$PATH" \
    PYTHONUNBUFFERED=1 \
    PYTHONDONTWRITEBYTECODE=1

# User non-root
RUN useradd --system --create-home --uid 10001 agent

WORKDIR /app
COPY --from=builder /opt/venv /opt/venv
# Chỉ copy code cần chạy (không copy tài liệu, benchmark, script chấm...)
COPY --chown=agent:agent app/ ./app/
COPY --chown=agent:agent utils/ ./utils/

USER agent
EXPOSE 8000

# Slim không có curl nên gọi /health bằng python; PORT mặc định 8000
HEALTHCHECK --interval=30s --timeout=5s --start-period=10s --retries=3 \
    CMD python -c "import os, urllib.request; urllib.request.urlopen('http://127.0.0.1:' + os.getenv('PORT', '8000') + '/health', timeout=3)"

# `exec` để uvicorn thay thế shell và là PID 1 → nhận SIGTERM trực tiếp khi `docker stop`
CMD ["sh", "-c", "exec uvicorn app.main:app --host 0.0.0.0 --port ${PORT:-8000} --workers 2"]
