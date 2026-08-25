# ==============================================================================
# STAGE 1: BUILDER (Cài đặt dependencies và biên dịch thư viện C/C++)
# ==============================================================================
FROM python:3.10-slim AS builder

WORKDIR /build

# Cài đặt các công cụ build hệ thống cần thiết cho lxml và Pillow
RUN apt-get update && apt-get install -y --no-install-recommends \
    gcc \
    libxml2-dev \
    libxslt1-dev \
    zlib1g-dev \
    libjpeg-dev \
    && rm -rf /var/lib/apt/lists/*

# Copy file requirements và cài đặt packages
COPY requirements.txt .
RUN pip install --no-cache-dir --user -r requirements.txt

# ==============================================================================
# STAGE 2: PRODUCTION RUNNER (Image siêu nhẹ cho Render Deployment)
# ==============================================================================
FROM python:3.10-slim AS runner

WORKDIR /app

# Thiết lập biến môi trường tối ưu hóa runtime Python
ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    PYTHONPATH=/app \
    PORT=8000

# Cài đặt các runtime shared libraries cần thiết cho lxml và Pillow
RUN apt-get update && apt-get install -y --no-install-recommends \
    libxml2 \
    libxslt1.1 \
    zlib1g \
    libjpeg62-turbo \
    curl \
    && rm -rf /var/lib/apt/lists/*

# Tạo người dùng non-root vì lý do bảo mật container
RUN addgroup --system --gid 1001 appgroup && \
    adduser --system --uid 1001 --ingroup appgroup appuser

# Copy Python packages từ Builder stage
COPY --from=builder /root/.local /home/appuser/.local

# Cập nhật PATH để sử dụng user packages
ENV PATH=/home/appuser/.local/bin:$PATH

# Copy toàn bộ mã nguồn Backend vào container
COPY --chown=appuser:appgroup . /app

# Đổi quyền sở hữu cho non-root user
USER appuser

# Mở cổng giao tiếp (Render sẽ tự động ghi đè qua biến $PORT)
EXPOSE 8000

# Health check định kỳ để đảm bảo container đang hoạt động
HEALTHCHECK --interval=30s --timeout=5s --start-period=10s --retries=3 \
    CMD curl -f http://localhost:${PORT}/health || exit 1

# Khởi chạy FastAPI Server bằng Uvicorn với dynamic $PORT
CMD ["sh", "-c", "uvicorn app.main:app --host 0.0.0.0 --port ${PORT:-8000} --workers 2 --access-log"]
