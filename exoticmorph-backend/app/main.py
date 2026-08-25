"""
ExoticMorph FastAPI Main Application
~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~
Entrypoint khởi chạy FastAPI Server cho môi trường Production (Render.com),
tích hợp CORS middleware động cho Vercel Frontend và cung cấp endpoint /health.
"""

import logging
from fastapi import FastAPI, Request
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse

from app.config import settings
from app.api.routes import router as api_router

# Cấu hình logging
logging.basicConfig(
    level=logging.INFO if not settings.DEBUG else logging.DEBUG,
    format="%(asctime)s [%(levelname)s] %(name)s: %(message)s",
)
logger = logging.getLogger("exoticmorph.main")

# Khởi tạo ứng dụng FastAPI
app = FastAPI(
    title="ExoticMorph AI Backend",
    description="Backend API tạo bài thuyết trình PowerPoint có hiệu ứng Morph tự động bằng AI.",
    version="1.0.0",
    docs_url="/docs",
    redoc_url="/redoc",
)

# Xử lý danh sách CORS Origins
origins_list = settings.ALLOWED_ORIGINS if isinstance(settings.ALLOWED_ORIGINS, list) else [settings.ALLOWED_ORIGINS]

# Bật wildcard nếu có '*' hoặc chuẩn hóa danh sách
is_wildcard = "*" in origins_list

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"] if is_wildcard else origins_list,
    allow_origin_regex=r"^https:\/\/.*\.vercel\.app$" if not is_wildcard else None,
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
    expose_headers=["Content-Disposition", "X-Slide-Count", "X-Morph-Style"],
)


@app.exception_handler(Exception)
async def global_exception_handler(request: Request, exc: Exception):
    """Xử lý ngoại lệ toàn cục để luôn trả về phản hồi JSON có cấu trúc."""
    logger.error("Unhandled Exception tại %s: %s", request.url.path, str(exc), exc_info=True)
    return JSONResponse(
        status_code=500,
        content={
            "success": False,
            "error": "InternalServerError",
            "message": f"Đã xảy ra lỗi trên hệ thống ExoticMorph: {str(exc)}",
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
    }


if __name__ == "__main__":
    import uvicorn

    uvicorn.run(
        "app.main:app",
        host=settings.HOST,
        port=settings.PORT,
        reload=settings.DEBUG,
    )
