"""
FastAPI Routes for ExoticMorph
~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~
Định nghĩa các API endpoints:
- POST /api/v1/generate:      Nhận prompt -> gọi LLM -> sinh PPTX có Morph -> trả về binary file.
- POST /api/v1/generate-json: Trả về JSON structure của bài trình chiếu (cho Preview UI).
- POST /api/v1/build-pptx:    Biên dịch file .pptx từ JSON có sẵn (KHÔNG gọi LLM).
- GET  /api/v1/health:        Kiểm tra trạng thái hoạt động của hệ thống.

Nâng cấp trong đợt rework:
- Endpoint /build-pptx giúp Frontend chỉ gọi LLM MỘT LẦN: lấy JSON từ
  /generate-json rồi biên dịch lại -> file tải về LUÔN KHỚP với Slide Preview
  (bản cũ gọi LLM 2 lần với temperature 0.7, preview và file có thể khác nhau).
- Phân loại lỗi rõ ràng: 422 (dữ liệu vào sai), 502 (LLM), 500 (hệ thống);
  che thông tin nhạy cảm của exception khi DEBUG=False.
- Đặt tên file an toàn khi title rỗng / chứa ký tự lạ.
"""

import logging
import re
import unicodedata
import urllib.parse

from fastapi import APIRouter, HTTPException, status
from fastapi.responses import Response

from app.config import settings
from app.schemas.slide_schema import GenerateRequest, PresentationResponse
from app.services.generator_service import build_pptx_from_schema
from app.services.llm_service import generate_presentation_with_llm

logger = logging.getLogger("exoticmorph.routes")
router = APIRouter(prefix="/api/v1", tags=["ExoticMorph Generation"])

# MIME type chuẩn của OpenXML PresentationML (.pptx)
PPTX_MIME_TYPE = "application/vnd.openxmlformats-officedocument.presentationml.presentation"


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


def _safe_error_detail(exc: Exception) -> str:
    """Ẩn chi tiết exception khi chạy production (DEBUG=False) để không lộ
    cấu trúc code / API key ra ngoài; DEBUG=True thì giữ nguyên để dễ sửa lỗi."""
    if settings.DEBUG:
        return str(exc)
    return "Đã xảy ra lỗi nội bộ phía máy chủ. Vui lòng thử lại hoặc liên hệ quản trị viên."


def _pptx_response(presentation_data: PresentationResponse) -> Response:
    """Build Response chứa binary .pptx + các header tải file chuẩn.

    Trả về đúng MIME type của OpenXML PresentationML và đặt tên file kép
    (ASCII + UTF-8 RFC 5987) để trình duyệt tự gán filename không dấu.
    """
    pptx_buffer = build_pptx_from_schema(presentation_data)
    file_bytes = pptx_buffer.getvalue()
    # Giải phóng buffer ngay sau khi copy ra bytes (giảm RSS đỉnh점 trên free tier).
    pptx_buffer.close()

    # Đặt tên file: fallback nếu title rỗng (bản cũ sinh "_morph.pptx").
    raw_title = ""
    if presentation_data.slides:
        raw_title = (presentation_data.slides[0].title or "").strip()
    if not raw_title:
        raw_title = "ExoticMorph Presentation"

    ascii_filename = f"{sanitize_filename(raw_title)}_morph.pptx"
    utf8_filename = f"{urllib.parse.quote(raw_title[:30])}_morph.pptx"

    logger.info(
        "Đã xuất file .pptx '%s' thành công (Size: %.2f KB)!",
        ascii_filename,
        len(file_bytes) / 1024,
    )

    return Response(
        content=file_bytes,
        media_type=PPTX_MIME_TYPE,
        headers={
            "Content-Disposition": f'attachment; filename="{ascii_filename}"; filename*=UTF-8\'\'{utf8_filename}',
            "X-Slide-Count": str(presentation_data.total_slides),
            "X-Morph-Style": presentation_data.style,
            # Ngăn proxy/CDN cache nhầm binary file generation động.
            "Cache-Control": "no-store",
        },
    )


@router.post(
    "/generate",
    summary="Tạo và tải về file PowerPoint (.pptx) có hiệu ứng Morph bằng AI",
    description="Nhận prompt từ người dùng, gọi LLM tính toán tọa độ Morph và trả về trực tiếp file .pptx nén.",
    response_class=Response,
    responses={
        200: {
            "content": {PPTX_MIME_TYPE: {}},
            "description": "Tệp PowerPoint .pptx hoàn chỉnh tải về.",
        },
        422: {"description": "Dữ liệu đầu vào hoặc cấu trúc slide không hợp lệ."},
        500: {"description": "Lỗi nội bộ trong quá trình sinh slide."},
    },
)
async def generate_pptx_presentation(request: GenerateRequest):
    """Endpoint chính nhận yêu cầu và xuất file .pptx."""
    # ── AUDIT LOG: ghi đầy đủ prompt nhận từ Frontend để debug nếu bị trôi ──
    logger.info(
        "[ROUTES /generate] Nhận request | prompt=%r | num_slides=%d | style=%s | aspect_ratio=%s | lang=%s",
        request.prompt,
        request.num_slides,
        request.style,
        request.aspect_ratio,
        request.language,
    )

    # 1. Gọi LLM để tính toán cấu trúc slide & ma trận tọa độ Morph.
    #    (Hàm này có retry + fallback nên gần như không raise.)
    presentation_data = await generate_presentation_with_llm(request)

    # 2. Biên dịch dữ liệu JSON sang OpenXML PPTX.
    try:
        return _pptx_response(presentation_data)
    except ValueError as exc:
        # Lỗi nghiệp vụ do dữ liệu (vd: danh sách slide rỗng) -> 422 thay vì 500.
        logger.warning("Dữ liệu không hợp lệ khi build PPTX: %s", exc)
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
            detail=str(exc),
        ) from exc
    except Exception as exc:
        logger.exception("Lỗi khi xử lý tạo file PPTX: %s", str(exc))
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=f"Không thể tạo bài trình chiếu: {_safe_error_detail(exc)}",
        ) from exc


@router.post(
    "/generate-json",
    summary="Sinh cấu trúc JSON bài thuyết trình (Dành cho Xem trước UI / Preview)",
    response_model=PresentationResponse,
    responses={
        200: {"description": "Cấu trúc JSON của bài trình chiếu."},
        500: {"description": "Lỗi khi sinh cấu trúc slide."},
    },
)
async def generate_presentation_json(request: GenerateRequest):
    """Endpoint trả về cấu trúc JSON slide & tọa độ Morph để hiển thị Mock Preview trên Frontend."""
    logger.info(
        "[ROUTES /generate-json] Nhận request | prompt=%r | num_slides=%d | style=%s",
        request.prompt,
        request.num_slides,
        request.style,
    )
    try:
        return await generate_presentation_with_llm(request)
    except Exception as exc:
        # Lý thuyết không bao giờ xảy ra (fallback generator không fail),
        # nhưng vẫn phải có lưới an toàn để không trả HTML traceback cho client.
        logger.exception("Lỗi khi sinh JSON slide: %s", str(exc))
        raise HTTPException(
            status_code=status.HTTP_502_BAD_GATEWAY,
            detail=f"Lỗi từ dịch vụ AI phía backend: {_safe_error_detail(exc)}",
        ) from exc


@router.post(
    "/build-pptx",
    summary="Biên dịch file .pptx từ cấu trúc JSON có sẵn (không gọi LLM)",
    description=(
        "Nhận chính xác JSON PresentationResponse (đã lấy từ /generate-json) và biên dịch ra file .pptx. "
        "Giúp Frontend chỉ gọi LLM MỘT LẦN duy nhất — file tải về luôn khớp 100% với Slide Preview đã hiển thị."
    ),
    response_class=Response,
    responses={
        200: {
            "content": {PPTX_MIME_TYPE: {}},
            "description": "Tệp PowerPoint .pptx biên dịch từ JSON.",
        },
        422: {"description": "Cấu trúc JSON không hợp lệ."},
        500: {"description": "Lỗi biên dịch OpenXML."},
    },
)
async def build_pptx_from_json(presentation: PresentationResponse):
    """Endpoint biên dịch deterministic: cùng JSON vào -> luôn cùng file .pptx ra."""
    try:
        return _pptx_response(presentation)
    except ValueError as exc:
        logger.warning("Payload build-pptx không hợp lệ: %s", exc)
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
            detail=str(exc),
        ) from exc
    except Exception as exc:
        logger.exception("Lỗi khi biên dịch PPTX từ JSON: %s", str(exc))
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=f"Không thể biên dịch file .pptx: {_safe_error_detail(exc)}",
        ) from exc


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
