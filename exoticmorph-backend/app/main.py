"""
ExoticMorph FastAPI Main Application
~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~
Entrypoint khởi chạy FastAPI Server cho môi trường Production (Render.com),
tích hợp CORS middleware động cho Vercel Frontend và cung cấp endpoint /health.

Nâng cấp trong đợt rework:
- FIX lỗi vi phạm CORS spec: bản cũ gộp `allow_origins=["*"]` với
  `allow_credentials=True` (browsers từ chối; Starlette còn phản ánh mọi origin
  khiến chính sách CORS rộng hơn dự kiến). Giờ wildcard sẽ tắt credentials.
- Regex CORS hoạt động ở CẢ HAI chế độ (trước đây wildcard làm regex tắt ngấm).
- Lọc các entry kiểu "https://*.vercel.app" ra khỏi danh sách literal (CORSMiddleware
  chỉ khớp chuỗi chính xác nên entry có dấu sao là vô nghĩa).
"""

import logging

from fastapi import FastAPI, Request
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse

from app.config import log_llm_status, settings
from app.api.routes import router as api_router

# Cấu hình logging
logging.basicConfig(
    level=logging.INFO if not settings.DEBUG else logging.DEBUG,
    format="%(asctime)s [%(levelname)s] %(name)s: %(message)s",
)
logger = logging.getLogger("exoticmorph.main")

# STARTUP DIAGNOSTICS: in trạng thái LLM (provider, model, API key đã mask,
# file .env có đọc được không) ra console MỘT LẦN khi boot — để phát hiện ngay
# sự cố dạng "biến môi trường rỗng" / "sai tên biến" / ".env không được nạp"
# trước khi request đầu tiên đến (thay vì debug mò qua từng request lỗi).
log_llm_status()

# Khởi tạo ứng dụng FastAPI
app = FastAPI(
    title="ExoticMorph AI Backend",
    description="Backend API tạo bài thuyết trình PowerPoint có hiệu ứng Morph tự động bằng AI.",
    version="1.0.0",
    docs_url="/docs",
    redoc_url="/redoc",
)

# ==============================================================================
# CORS Middleware
# ==============================================================================
# Chuẩn hóa danh sách origins (validator của config luôn trả về List[str],
# nhưng giữ isinstance check để phòng gọi main.py ngoài vòng pydantic).
origins_list = settings.ALLOWED_ORIGINS if isinstance(settings.ALLOWED_ORIGINS, list) else [settings.ALLOWED_ORIGINS]
is_wildcard = "*" in origins_list

# Entry chứa dấu '*' (vd "https://*.vercel.app") không khớp literal trong
# CORSMiddleware — việc khớp domain động đã do regex bên dưới đảm nhiệm.
explicit_origins = [o for o in origins_list if o and o != "*"]

# Regex phủ: mọi deployment *.vercel.app (kể cả preview branch) + dev server localhost.
DYNAMIC_ORIGIN_REGEX = (
    r"https://[a-z0-9-]+(?:\.[a-z0-9-]+)*\.vercel\.app"
    r"|https?://(?:localhost|127\.0\.0\.1)(?::\d+)?"
)

cors_kwargs = dict(
    allow_methods=["*"],
    allow_headers=["*"],
    expose_headers=["Content-Disposition", "X-Slide-Count", "X-Morph-Style"],
)

if is_wildcard:
    # API công khai, không dùng cookie/session -> KHÔNG kết hợp "*" với
    # credentials (vi phạm CORS spec, trình duyệt sẽ từ chối request).
    logger.warning(
        "ALLOWED_ORIGINS chứa '*' — CORS đang mở cho MỌI domain (chỉ dùng khi debug)."
    )
    cors_kwargs.update(allow_origins=["*"], allow_credentials=False)
else:
    cors_kwargs.update(
        allow_origins=explicit_origins,
        allow_origin_regex=DYNAMIC_ORIGIN_REGEX,
        # API thuần stateless (không cookie) -> credentials không cần thiết.
        allow_credentials=False,
    )

app.add_middleware(CORSMiddleware, **cors_kwargs)


@app.exception_handler(Exception)
async def global_exception_handler(request: Request, exc: Exception):
    """Xử lý ngoại lệ toàn cục để luôn trả về phản hồi JSON có cấu trúc
    (tránh trình duyệt nhận về HTML traceback của Starlette)."""
    logger.error("Unhandled Exception tại %s: %s", request.url.path, str(exc), exc_info=True)
    return JSONResponse(
        status_code=500,
        content={
            "success": False,
            "error": "InternalServerError",
            "message": "Đã xảy ra lỗi trên hệ thống ExoticMorph. Vui lòng thử lại.",
        },
    )


# Đăng ký Router chính
app.include_router(api_router)


# ==============================================================================
# HEALTH CHECK ENDPOINTS (Dành riêng cho Render / Docker probes)
# ==============================================================================
@app.get("/health", tags=["Health"])
@app.get("/api/health", tags=["Health"])
async def render_health_check():
    """Endpoint kiểm tra trạng thái sống của Server dành riêng cho Render.com Health Check."""
    return {
        "status": "ok",
        "service": "ExoticMorph AI Backend",
        "version": "1.0.0",
        "port": settings.PORT,
    }


@app.get("/", tags=["Root"])
async def root():
    """Trang thông tin tổng quan của API."""
    return {
        "app": "ExoticMorph AI PowerPoint Morph Generator API",
        "docs": "/docs",
        "health": "/health",
        "generate_endpoint": "/api/v1/generate",
        "build_pptx_endpoint": "/api/v1/build-pptx",
    }


if __name__ == "__main__":
    import uvicorn

    uvicorn.run(
        "app.main:app",
        host=settings.HOST,
        port=settings.PORT,
        reload=settings.DEBUG,
    )
