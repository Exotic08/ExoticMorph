# ==============================================================================
# STAGE 1: BUILDER (Tạo virtualenv và biên dịch thư viện C/C++)
# ==============================================================================
FROM python:3.10-slim AS builder

WORKDIR /build

# Cài đặt công cụ build hệ thống cần thiết cho lxml và Pillow
RUN apt-get update && apt-get install -y --no-install-recommends \
    gcc \
    libxml2-dev \
    libxslt1-dev \
    zlib1g-dev \
    libjpeg-dev \
    && rm -rf /var/lib/apt/lists/*

# Tạo Virtual Environment độc lập tại /opt/venv
RUN python -m venv /opt/venv
ENV PATH="/opt/venv/bin:$PATH"

# Cài đặt toàn bộ dependencies vào Virtual Environment
COPY requirements.txt .
RUN pip install --no-cache-dir --upgrade pip setuptools wheel && \
    pip install --no-cache-dir -r requirements.txt

# ==============================================================================
# STAGE 2: PRODUCTION RUNNER (Image siêu nhẹ & an toàn cho Render)
# ==============================================================================
FROM python:3.10-slim AS runner

WORKDIR /app

# Thiết lập biến môi trường
ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    PYTHONPATH=/app \
    PATH="/opt/venv/bin:$PATH" \
    PORT=8000

# Cài đặt các thư viện shared C runtime cần thiết
RUN apt-get update && apt-get install -y --no-install-recommends \
    libxml2 \
    libxslt1.1 \
    zlib1g \
    libjpeg62-turbo \
    curl \
    && rm -rf /var/lib/apt/lists/*

# Tạo người dùng non-root appuser vì lý do bảo mật
RUN addgroup --system --gid 1001 appgroup && \
    adduser --system --uid 1001 --ingroup appgroup appuser

# Copy toàn bộ virtualenv từ Builder stage và gán quyền cho appuser
COPY --from=builder --chown=appuser:appgroup /opt/venv /opt/venv

# Copy toàn bộ mã nguồn Backend vào /app
COPY --chown=appuser:appgroup . /app

# Chuyển sang non-root user
USER appuser

# Mở cổng mặc định
EXPOSE 8000

# Health check định kỳ
HEALTHCHECK --interval=30s --timeout=5s --start-period=10s --retries=3 \
    CMD curl -f http://localhost:${PORT}/health || exit 1

# Khởi chạy FastAPI Server bằng Uvicorn với biến $PORT động của Render
CMD ["sh", "-c", "uvicorn app.main:app --host 0.0.0.0 --port ${PORT:-8000} --workers 2 --access-log"]
