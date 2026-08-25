"""
FastAPI Routes for ExoticMorph
~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~
Định nghĩa các API endpoints:
- POST /api/v1/generate: Nhận prompt -> gọi LLM -> sinh PPTX có Morph -> trả về binary file.
- POST /api/v1/generate-json: Trả về JSON structure của bài trình chiếu.
- GET /api/v1/health: Kiểm tra trạng thái hoạt động của hệ thống.
"""

import re
import urllib.parse
import unicodedata
import logging
from fastapi import APIRouter, HTTPException, status
from fastapi.responses import Response

from app.config import settings
from app.schemas.slide_schema import GenerateRequest, PresentationResponse
from app.services.llm_service import generate_presentation_with_llm
from app.services.generator_service import build_pptx_from_schema

logger = logging.getLogger("exoticmorph.routes")
router = APIRouter(prefix="/api/v1", tags=["ExoticMorph Generation"])


def sanitize_filename(name: str) -> str:
    """Tạo tên file chuẩn ASCII an toàn cho HTTP Header theo chuẩn RFC 6266."""
    # Khử dấu Tiếng Việt (Transliteration sang ASCII thuần)
    nfkd = unicodedata.normalize("NFKD", name)
    ascii_str = "".join([c for c in nfkd if not unicodedata.combining(c)])
    
    # Chỉ giữ lại chữ cái, số, gạch dưới và gạch ngang
    clean = re.sub(r"[^a-zA-Z0-9_\-]", "_", ascii_str).strip("_")
    clean = re.sub(r"_+", "_", clean)
    if not clean:
        clean = "exoticmorph_presentation"
    return clean[:40]


@router.post(
    "/generate",
    summary="Tạo và tải về file PowerPoint (.pptx) có hiệu ứng Morph bằng AI",
    description="Nhận prompt từ người dùng, gọi LLM tính toán tọa độ Morph và trả về trực tiếp file .pptx nén.",
    response_class=Response,
    responses={
        200: {
            "content": {
                "application/vnd.openxmlformats-officedocument.presentationml.presentation": {}
            },
            "description": "Tệp PowerPoint .pptx hoàn chỉnh tải về.",
        },
        500: {"description": "Lỗi nội bộ trong quá trình sinh slide hoặc kết nối LLM."},
    },
)
async def generate_pptx_presentation(request: GenerateRequest):
    """Endpoint chính nhận yêu cầu và xuất file .pptx."""
    try:
        logger.info(
            "Nhận yêu cầu tạo slide: '%s' (%d slides, style: %s)",
            request.prompt[:50],
            request.num_slides,
            request.style,
        )

        # 1. Gọi LLM để tính toán cấu trúc slide & ma trận tọa độ Morph
        presentation_data = await generate_presentation_with_llm(request)

        # 2. Biên dịch dữ liệu JSON sang OpenXML PPTX
        pptx_buffer = build_pptx_from_schema(presentation_data)
        file_bytes = pptx_buffer.getvalue()

        # 3. Đặt tên file chuẩn ASCII cho Header và UTF-8 mở rộng
        raw_title = presentation_data.slides[0].title if presentation_data.slides else "presentation"
        ascii_filename = f"{sanitize_filename(raw_title)}_morph.pptx"
        utf8_filename = f"{urllib.parse.quote(raw_title[:30])}_morph.pptx"

        logger.info(
            "Đã xuất file .pptx '%s' thành công (Size: %.2f KB)!",
            ascii_filename,
            len(file_bytes) / 1024,
        )

        return Response(
            content=file_bytes,
            media_type="application/vnd.openxmlformats-officedocument.presentationml.presentation",
            headers={
                "Content-Disposition": f'attachment; filename="{ascii_filename}"; filename*=UTF-8\'\'{utf8_filename}',
                "X-Slide-Count": str(presentation_data.total_slides),
                "X-Morph-Style": presentation_data.style,
            },
        )
    except Exception as e:
        logger.exception("Lỗi khi xử lý tạo file PPTX: %s", str(e))
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=f"Không thể tạo bài trình chiếu: {str(e)}",
        )


@router.post(
    "/generate-json",
    summary="Sinh cấu trúc JSON bài thuyết trình (Dành cho Xem trước UI / Preview)",
    response_model=PresentationResponse,
)
async def generate_presentation_json(request: GenerateRequest):
    """Endpoint trả về cấu trúc JSON slide & tọa độ Morph để hiển thị Mock Preview trên Frontend."""
    try:
        presentation_data = await generate_presentation_with_llm(request)
        return presentation_data
    except Exception as e:
        logger.exception("Lỗi khi sinh JSON slide: %s", str(e))
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=f"Lỗi phân tích prompt: {str(e)}",
        )


@router.get(
    "/health",
    summary="Kiểm tra trạng thái sức khỏe của Backend",
)
async def health_check():
    """Kiểm tra liveness và cấu hình LLM hiện tại."""
    return {
        "status": "online",
        "service": "ExoticMorph AI Backend",
        "version": "1.0.0",
        "llm_provider": settings.LLM_PROVIDER,
        "openai_configured": bool(settings.OPENAI_API_KEY),
        "gemini_configured": bool(settings.GEMINI_API_KEY),
    }
