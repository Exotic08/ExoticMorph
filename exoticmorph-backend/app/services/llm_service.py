"""
LLM Service Module for ExoticMorph (Refactored v3)
~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~
TÁCH BIỆT TRÁCH NHIỆM:
  - AI (LLM) CHỈ làm: sáng tạo nội dung (chữ, ý tưởng), chọn màu,
    cấp morph_id cho từng thẻ và GIỮ NGUYÊN morph_id giữa slide N và N+1.
  - Python (layout_engine.py) làm: tính hình học (x, y, width, height).

CẢI TIẾN CHÍNH so với v2:
  1. **Few-Shot Prompting**: Nhúng 3 ví dụ JSON hoàn chỉnh vào System Prompt
     để LLM "noi gương" chính xác 100% cấu trúc `LLMOutput`.
  2. **Structured Output Bắt Buộc**: Dùng `response_format` kèm JSON Schema
     (OpenAI) và `response_mime_type` + `response_schema` (Gemini) để ép
     LLM trả về JSON đúng schema không lệch một ký tự.
  3. **Pydantic Strict Validation + Retry**: Nếu parse lỗi, tự động Retry
     tối đa 2 lần kèm thông báo lỗi rõ ràng cho LLM tự sửa.
  4. **KHÔNG còn x, y, width, height** trong prompt hay output của LLM.
"""

import asyncio
import json
import logging
from typing import Any, Callable, Optional, TypeVar

from app.config import settings
from app.schemas.slide_schema import (
    GenerateRequest,
    LLMOutput,
    PresentationResponse,
)
from app.services.layout_engine import compute_layout

logger = logging.getLogger("exoticmorph.llm")

# ==============================================================================
# CẤU HÌNH RETRY
# ==============================================================================
LLM_MAX_ATTEMPTS = 3              # Số lần gọi LLM tối đa (1 lần đầu + 2 retry)
LLM_RETRY_BASE_DELAY_S = 1.5      # Exponential backoff
LLM_REQUEST_TIMEOUT_S = 90.0      # Timeout mỗi lần gọi
MAX_VALIDATION_RETRIES = 2        # Số lần retry khi Pydantic Validation fail

T = TypeVar("T")


# ==============================================================================
# FEW-SHOT EXAMPLES (JSON mẫu) — nhúng trực tiếp vào System Prompt
# ==============================================================================
# 3 ví dụ bao phủ: 2-slide cover+detail, 3-slide 3-cột, 5-slide nhiều cards.

_FEW_SHOT_EXAMPLE_1 = json.dumps(
    {
        "topic": "Giới thiệu Nền tảng AI ExoticMorph",
        "slides": [
            {
                "slide_number": 1,
                "slide_title": "ExoticMorph — AI Tạo Slide PowerPoint Tự Động",
                "cards": [
                    {
                        "morph_id": "hero_card",
                        "title": "Morph Thông Minh",
                        "body": "Tự động tính toán tọa độ và liên kết đối tượng giữa các slide để tạo hiệu ứng Morph chuyển động mượt mà như phim.",
                        "color_theme": "#8B5CF6",
                        "order": 0,
                    },
                    {
                        "morph_id": "speed_card",
                        "title": "Tốc Độ Chớp Nhoáng",
                        "body": "Tạo bài trình chiếu 10 slide chỉ trong 10 giây. Tích hợp GPT-4o & Gemini 1.5 Pro cho nội dung chất lượng cao.",
                        "color_theme": "#06B6D4",
                        "order": 1,
                    },
                    {
                        "morph_id": "compat_card",
                        "title": "Tương Thích 100%",
                        "body": "File .pptx xuất ra tương thích hoàn toàn với Microsoft PowerPoint 2019+ và Microsoft 365, không cần add-in.",
                        "color_theme": "#EC4899",
                        "order": 2,
                    },
                ],
            },
            {
                "slide_number": 2,
                "slide_title": "Kiến Trúc 3 Lớp Cốt Lõi",
                "cards": [
                    {
                        "morph_id": "hero_card",
                        "title": "LLM Creative Layer",
                        "body": "Sử dụng Few-Shot Prompting và Structured Output để sinh nội dung sáng tạo, bám sát yêu cầu người dùng.",
                        "color_theme": "#161926",
                        "order": 0,
                    },
                    {
                        "morph_id": "speed_card",
                        "title": "Python Geometry Engine",
                        "body": "Tính toán hình học (x, y, w, h) bằng công thức toán học chính xác, đảm bảo không chồng lấn, không tràn khung.",
                        "color_theme": "#1E2235",
                        "order": 1,
                    },
                    {
                        "morph_id": "compat_card",
                        "title": "OpenXML Morph Builder",
                        "body": "Chèn trực tiếp transition XML chuẩn ECMA-376 và gán '!!' morph name để PowerPoint nhận diện đối tượng Morph.",
                        "color_theme": "#241438",
                        "order": 2,
                    },
                ],
            },
        ],
    },
    ensure_ascii=False,
    indent=2,
)

_FEW_SHOT_EXAMPLE_2 = json.dumps(
    {
        "topic": "Báo Cáo Tài Chính Q3/2025",
        "slides": [
            {
                "slide_number": 1,
                "slide_title": "Tổng Quan Tài Chính Quý 3",
                "cards": [
                    {
                        "morph_id": "kpi_revenue",
                        "title": "Doanh Thu $12.5M",
                        "body": "Tăng 45% so với cùng kỳ năm ngoái, vượt chỉ tiêu 12%.",
                        "color_theme": "#10B981",
                        "order": 0,
                    },
                    {
                        "morph_id": "kpi_customers",
                        "title": "1,200 Khách Hàng Enterprise",
                        "body": "Tỷ lệ giữ chân (Net Retention) đạt 128%, dẫn đầu ngành.",
                        "color_theme": "#3A86FF",
                        "order": 1,
                    },
                    {
                        "morph_id": "kpi_nps",
                        "title": "NPS Score: 72",
                        "body": "Mức hài lòng khách hàng ở mức World-Class (top 5% ngành SaaS).",
                        "color_theme": "#F59E0B",
                        "order": 2,
                    },
                ],
            },
            {
                "slide_number": 2,
                "slide_title": "Phân Tích Chi Tiết Doanh Thu",
                "cards": [
                    {
                        "morph_id": "kpi_revenue",
                        "title": "Subscription: $9.2M",
                        "body": "Chiếm 74% tổng doanh thu, tăng trưởng 52% YoY nhờ mở rộng Enterprise.",
                        "color_theme": "#10B981",
                        "order": 0,
                    },
                    {
                        "morph_id": "rev_services",
                        "title": "Professional Services: $2.1M",
                        "body": "Dịch vụ triển khai và đào tạo đóng góp 17% với biên lợi nhuận 45%.",
                        "color_theme": "#1C2541",
                        "order": 1,
                    },
                    {
                        "morph_id": "rev_marketplace",
                        "title": "Marketplace: $1.2M",
                        "body": "Kho Template & API của bên thứ ba tăng trưởng 120% QoQ.",
                        "color_theme": "#1C2541",
                        "order": 2,
                    },
                ],
            },
            {
                "slide_number": 3,
                "slide_title": "Kế Hoạch Q4/2025",
                "cards": [
                    {
                        "morph_id": "plan_apac",
                        "title": "Mở Rộng APAC",
                        "body": "Ra mắt văn phòng Singapore & Tokyo, mục tiêu +$3M ARR từ thị trường châu Á.",
                        "color_theme": "#8B5CF6",
                        "order": 0,
                    },
                    {
                        "morph_id": "plan_ai",
                        "title": "Ra Mắt AI Copilot",
                        "body": "Tích hợp trực tiếp vào PowerPoint, cho phép sửa slide bằng giọng nói.",
                        "color_theme": "#D946EF",
                        "order": 1,
                    },
                    {
                        "morph_id": "plan_channel",
                        "title": "Kênh Phân Phối Đối Tác",
                        "body": "Ký hợp tác chiến lược với Microsoft AppSource và 5 đại lý cấp 1.",
                        "color_theme": "#06B6D4",
                        "order": 2,
                    },
                ],
            },
        ],
    },
    ensure_ascii=False,
    indent=2,
)

_FEW_SHOT_EXAMPLE_3 = json.dumps(
    {
        "topic": "Giới Thiệu Sản Phẩm Tối Giản (Minimal Style)",
        "slides": [
            {
                "slide_number": 1,
                "slide_title": "Một Giải Pháp, Vạn Bài Trình Chiếu",
                "cards": [
                    {
                        "morph_id": "main_pitch",
                        "title": "ExoticMorph Minimal",
                        "body": "Thiết kế tối giản tập trung vào nội dung cốt lõi. Màu sắc hài hòa, bố cục rõ ràng.",
                        "color_theme": "#6366F1",
                        "order": 0,
                    },
                    {
                        "morph_id": "feature_1",
                        "title": "Một Click",
                        "body": "Nhập ý tưởng, nhận file PPTX chỉ sau một cú nhấp chuột.",
                        "color_theme": "#1E293B",
                        "order": 1,
                    },
                ],
            },
            {
                "slide_number": 2,
                "slide_title": "Trải Nghiệm Người Dùng",
                "cards": [
                    {
                        "morph_id": "ux_fast",
                        "title": "Nhanh",
                        "body": "Xử lý dưới 15 giây cho 10 slide. Không chờ đợi, không phiền phức.",
                        "color_theme": "#1E293B",
                        "order": 0,
                    },
                    {
                        "morph_id": "ux_easy",
                        "title": "Dễ",
                        "body": "Giao diện trực quan, không cần kỹ năng thiết kế hay cài đặt phần mềm.",
                        "color_theme": "#334155",
                        "order": 1,
                    },
                    {
                        "morph_id": "ux_beautiful",
                        "title": "Đẹp",
                        "body": "Mỗi slide được bố cục theo lưới hình học hoàn hảo, font và màu hài hòa.",
                        "color_theme": "#1E293B",
                        "order": 2,
                    },
                    {
                        "morph_id": "ux_smart",
                        "title": "Thông Minh",
                        "body": "AI hiểu ngữ cảnh, chọn morph_id nhất quán để hiệu ứng chuyển động tự nhiên.",
                        "color_theme": "#6366F1",
                        "order": 3,
                    },
                ],
            },
        ],
    },
    ensure_ascii=False,
    indent=2,
)


# ==============================================================================
# SYSTEM PROMPT với FEW-SHOT
# ==============================================================================
SYSTEM_PROMPT = f"""Bạn là "Master Presentation Architect" — kiến trúc sư trình chiếu hàng đầu thế giới, chuyên thiết kế nội dung cho bài thuyết trình PowerPoint với hiệu ứng Morph.

NHIỆM VỤ:
Nhận yêu cầu từ người dùng (chủ đề, số lượng slide, phong cách, ngôn ngữ) và trả về DUY NHẤT một JSON object theo đúng schema được định nghĩa dưới đây.

QUY TẮC BẮT BUỘC (MUST OBEY — KHÔNG ĐƯỢC VI PHẠM):

1. **CHỈ NỘI DUNG, KHÔNG HÌNH HỌC**:
   - Bạn KHÔNG ĐƯỢC trả về các trường `x`, `y`, `width`, `height` ở bất kỳ đâu.
   - Việc tính toán toạ độ và kích thước sẽ do Python Layout Engine xử lý sau.
   - Bạn chỉ được quyết định: nội dung chữ (`title`, `body`), màu sắc (`color_theme`),
     và `morph_id` (liên kết Morph giữa các slide).

2. **BẢO TOÀN MORPH_ID (QUAN TRỌNG NHẤT)**:
   - `morph_id` là mã định danh DUY NHẤT cho một đối tượng nội dung.
   - GIỮ NGUYÊN `morph_id` của một thẻ giữa slide N và slide N+1 nếu thẻ đó biểu diễn
     cùng một nội dung (tiếp nối, mở rộng hoặc thu nhỏ) để PowerPoint Morph hoạt động.
   - Ví dụ: Thẻ "KPI Doanh Thu" ở slide 1 có morph_id="kpi_revenue", sang slide 2
     khi đi vào chi tiết, thẻ đó VẪN PHẢI có morph_id="kpi_revenue".
   - Thẻ mới hoàn toàn ở slide sau phải có morph_id MỚI (chưa từng xuất hiện).
   - Sử dụng morph_id ngắn gọn, gạch dưới, không dấu cách, không ký tự đặc biệt
     (vd: "hero_card", "kpi_revenue", "plan_apac", "col_1").

3. **CẤU TRÚC MỖI SLIDE**:
   - Mỗi slide có: `slide_number`, `slide_title`, và `cards` (danh sách 1-6 thẻ).
   - Mỗi card có: `morph_id`, `title` (ngắn 1-12 từ), `body` (1-5 dòng giải thích),
     `color_theme` (mã hex có dấu #, vd "#1E2235"), `order` (thứ tự từ 0, tăng dần).
   - Sắp xếp `cards` theo `order` từ trái sang phải / trên xuống dưới.

4. **SỐ LƯỢNG SLIDE**: Phải trả về ĐÚNG bằng số slide người dùng yêu cầu.

5. **MÀU SẮC**:
   - Dùng bảng màu phong cách tương ứng (Futuristic/Minimal/Corporate/Creative).
   - Thẻ chính có màu điểm nhấn (accent), thẻ phụ dùng màu nền card tối.
   - Mọi `color_theme` phải là mã hex hợp lệ 6 ký tự có dấu #.

6. **NGÔN NGỮ**: Toàn bộ nội dung (title, body) phải bằng ngôn ngữ người dùng yêu cầu
   ("vi" → Tiếng Việt, "en" → English).

7. **ĐỊNH DẠNG**: Trả về DUY NHẤT một JSON object hợp lệ. KHÔNG bọc trong markdown
   code fence (```json ... ```), KHÔNG thêm văn bản giải thích trước/sau JSON.

---
VÍ DỤ 1 — 2 slide với 3 thẻ/slide, thẻ "hero_card", "speed_card", "compat_card" giữ nguyên morph_id giữa 2 slide:
{_FEW_SHOT_EXAMPLE_1}

---
VÍ DỤ 2 — 3 slide báo cáo tài chính, thẻ KPI "kpi_revenue" giữ nguyên ID từ slide 1 sang slide 2:
{_FEW_SHOT_EXAMPLE_2}

---
VÍ DỤ 3 — 2 slide phong cách Minimal, slide 2 có 4 thẻ (grid 2x2):
{_FEW_SHOT_EXAMPLE_3}
---

Hãy noi gương chính xác cấu trúc của các ví dụ trên khi tạo bài trình chiếu mới."""


# ==============================================================================
# HELPERS
# ==============================================================================

def _clamp(value: float, lo: float, hi: float) -> float:
    return max(lo, min(value, hi))


def _extract_json_object(text: str) -> dict:
    """Trích JSON object đầu tiên từ phản hồi LLM (chịu lỗi markdown fence)."""
    import re

    if not text or not text.strip():
        raise ValueError("LLM trả về nội dung rỗng")

    cleaned = text.strip()

    # Bóc markdown code fence
    fence_match = re.match(r"^```[a-zA-Z]*\s*(.*?)\s*```$", cleaned, re.DOTALL)
    if fence_match:
        cleaned = fence_match.group(1).strip()

    # Parse trực tiếp
    try:
        parsed = json.loads(cleaned)
        if isinstance(parsed, dict):
            return parsed
    except json.JSONDecodeError:
        pass

    # Quét ngoặc cân bằng (xử lý text thừa quanh JSON)
    start = cleaned.find("{")
    while start != -1:
        depth = 0
        in_string = False
        escaped = False
        for idx in range(start, len(cleaned)):
            ch = cleaned[idx]
            if in_string:
                if escaped:
                    escaped = False
                elif ch == "\\":
                    escaped = True
                elif ch == '"':
                    in_string = False
                continue
            if ch == '"':
                in_string = True
            elif ch == "{":
                depth += 1
            elif ch == "}":
                depth -= 1
                if depth == 0:
                    candidate = cleaned[start:idx + 1]
                    try:
                        parsed = json.loads(candidate)
                        if isinstance(parsed, dict):
                            return parsed
                    except json.JSONDecodeError:
                        break
        start = cleaned.find("{", start + 1)

    raise ValueError("Không tìm thấy JSON object hợp lệ trong phản hồi của LLM")


def _is_transient_error(exc: Exception) -> bool:
    """Phân loại lỗi tạm thời (đáng retry với backoff) vs lỗi logic."""
    status = getattr(exc, "status_code", None)
    if isinstance(status, int) and status in (408, 429, 500, 502, 503, 504):
        return True
    name = type(exc).__name__
    return name in {
        "APIConnectionError", "APITimeoutError", "APIConnectionTimeoutError",
        "TimeoutError", "ConnectError", "ReadTimeout", "RemoteProtocolError",
    }


async def _call_with_retry(
    provider_name: str,
    operation: Callable[[], Any],
) -> Any:
    """Gọi LLM với retry + exponential backoff cho lỗi tạm thời."""
    last_exc: Optional[Exception] = None
    for attempt in range(1, LLM_MAX_ATTEMPTS + 1):
        try:
            return await asyncio.wait_for(operation(), timeout=LLM_REQUEST_TIMEOUT_S)
        except asyncio.TimeoutError:
            last_exc = TimeoutError(f"{provider_name} vượt quá {LLM_REQUEST_TIMEOUT_S:.0f}s")
            retryable = True
        except Exception as exc:  # noqa: BLE001
            last_exc = exc
            retryable = _is_transient_error(exc)

        if not retryable or attempt == LLM_MAX_ATTEMPTS:
            raise last_exc

        delay = LLM_RETRY_BASE_DELAY_S * (2 ** (attempt - 1))
        logger.warning(
            "Lỗi tạm thời từ %s (lần %d/%d): %s — thử lại sau %.1fs...",
            provider_name, attempt, LLM_MAX_ATTEMPTS, last_exc, delay,
        )
        await asyncio.sleep(delay)

    raise last_exc  # pragma: no cover


# ==============================================================================
# OPENAI CLIENT (Async, connection pooling)
# ==============================================================================
_openai_client: Optional[Any] = None


def _get_openai_client() -> Any:
    global _openai_client
    if _openai_client is None:
        from openai import AsyncOpenAI
        _openai_client = AsyncOpenAI(
            api_key=settings.OPENAI_API_KEY,
            timeout=LLM_REQUEST_TIMEOUT_S,
            max_retries=0,
        )
    return _openai_client


def _build_user_prompt(req: GenerateRequest) -> str:
    """Xây dựng user prompt mô tả chính xác yêu cầu."""
    lang = "Tiếng Việt" if req.language.lower().startswith("vi") else "English"
    return (
        f"YÊU CẦU:\n"
        f"- Chủ đề: {req.prompt}\n"
        f"- Số lượng slide: {req.num_slides} (BẮT BUỘC đúng con số này)\n"
        f"- Phong cách: {req.style}\n"
        f"- Tỉ lệ: {req.aspect_ratio}\n"
        f"- Ngôn ngữ nội dung: {lang}\n"
        f"- Sinh speaker notes: {'Có' if req.include_speaker_notes else 'Không'}\n\n"
        f"Hãy trả về JSON đúng schema LLMOutput (chỉ nội dung, KHÔNG có x/y/width/height). "
        f"NHỚ GIỮ NGUYÊN morph_id cho các thẻ tương ứng giữa slide N và slide N+1."
    )


# ==============================================================================
# PARSER with PYDANTIC VALIDATION RETRY
# ==============================================================================

def _validate_llm_output(data: dict) -> LLMOutput:
    """Validate dữ liệu thô bằng Pydantic LLMOutput strict schema.

    Raises:
        ValueError: nếu validation fail (kèm thông báo lỗi rõ ràng cho retry).
    """
    try:
        return LLMOutput.model_validate(data)
    except Exception as exc:
        # Tạo thông báo lỗi ngắn gọn để LLM tự sửa
        errors = []
        try:
            from pydantic import ValidationError
            if isinstance(exc, ValidationError):
                for err in exc.errors():
                    loc = " → ".join(str(p) for p in err.get("loc", []))
                    msg = err.get("msg", "")
                    errors.append(f"- Tại '{loc}': {msg}")
        except Exception:  # noqa: BLE001
            errors.append(str(exc)[:300])
        error_msg = "Pydantic Validation Error:\n" + "\n".join(errors[:5])
        raise ValueError(error_msg) from exc


async def _parse_with_retry(
    raw_text_getter: Callable[[str], Any],
    build_messages: Callable[[str], list],
    req: GenerateRequest,
    provider: str,
) -> LLMOutput:
    """Pipeline: gọi LLM -> trích JSON -> validate Pydantic -> retry tối đa 2 lần nếu lỗi.

    Retry với feedback lỗi cụ thể để LLM tự sửa sai.
    """
    last_validation_error: Optional[str] = None

    for attempt in range(1, MAX_VALIDATION_RETRIES + 2):  # 1 chính + 2 retry
        # Gọi LLM (có thể kèm feedback lỗi lần trước)
        messages = build_messages(
            _build_user_prompt(req)
            if last_validation_error is None
            else _build_user_prompt(req) + f"\n\nLẦN TRƯỚC BẠN BỊ LỖI, HÃY SỬA:\n{last_validation_error}\n\nHãy trả về JSON đã sửa, đúng schema, không giải thích thêm."
        )

        try:
            raw_text = await raw_text_getter(messages)
        except Exception as exc:
            # Lỗi mạng/API -> retry với backoff tầng trên (_call_with_retry)
            raise

        # Parse JSON
        try:
            data = _extract_json_object(raw_text or "")
        except ValueError as exc:
            last_validation_error = f"Lỗi parse JSON: {exc}"
            logger.warning(
                "%s parse JSON lỗi (lần %d): %s",
                provider, attempt, last_validation_error,
            )
            if attempt > MAX_VALIDATION_RETRIES:
                raise
            await asyncio.sleep(LLM_RETRY_BASE_DELAY_S * attempt)
            continue

        # Validate Pydantic
        try:
            result = _validate_llm_output(data)
            logger.info(
                "%s đã sinh thành công %d slide (lần thử %d)!",
                provider, len(result.slides), attempt,
            )
            return result
        except ValueError as exc:
            last_validation_error = str(exc)
            logger.warning(
                "%s Pydantic validation lỗi (lần %d): %s",
                provider, attempt, last_validation_error[:200],
            )
            if attempt > MAX_VALIDATION_RETRIES:
                raise
            await asyncio.sleep(LLM_RETRY_BASE_DELAY_S * attempt)

    # Không bao giờ đến được đây (vòng lặp luôn return/raise)
    raise RuntimeError("Unreachable: retry loop exhausted without return or raise")


# ==============================================================================
# PROVIDER IMPLEMENTATIONS
# ==============================================================================

async def _generate_with_openai(req: GenerateRequest) -> LLMOutput:
    """Gọi OpenAI GPT-4o với Structured Output (JSON Schema mode)."""
    logger.info("Đang gọi OpenAI %s (Structured Output)...", settings.OPENAI_MODEL)

    client = _get_openai_client()

    # JSON Schema cho Structured Output — được tạo động từ Pydantic LLMOutput
    json_schema = LLMOutput.model_json_schema()
    # Bỏ trường 'title' mà Pydantic tự sinh để tránh warning của OpenAI
    json_schema.pop("title", None)

    # Xây messages có kèm feedback lỗi nếu retry
    def _messages(user_content: str) -> list:
        return [
            {"role": "system", "content": SYSTEM_PROMPT},
            {"role": "user", "content": user_content},
        ]

    async def _raw_getter(messages: list) -> str:
        async def _call():
            # Ưu tiên dùng structured output (response_format json_schema) nếu SDK hỗ trợ
            try:
                return await client.chat.completions.create(
                    model=settings.OPENAI_MODEL,
                    messages=messages,
                    response_format={
                        "type": "json_schema",
                        "json_schema": {
                            "name": "LLMOutput",
                            "strict": True,
                            "schema": json_schema,
                        },
                    },
                    temperature=0.7,
                )
            except Exception:  # noqa: BLE001
                # Fallback về json_object mode (model cũ / SDK cũ)
                return await client.chat.completions.create(
                    model=settings.OPENAI_MODEL,
                    messages=messages,
                    response_format={"type": "json_object"},
                    temperature=0.7,
                )

        resp = await _call_with_retry("OpenAI", _call)
        return resp.choices[0].message.content if resp.choices else None

    return await _parse_with_retry(_raw_getter, _messages, req, "OpenAI")


async def _generate_with_gemini(req: GenerateRequest) -> LLMOutput:
    """Gọi Google Gemini 1.5 Pro với response_schema (Structured Output)."""
    logger.info("Đang gọi Gemini %s (Structured Output)...", settings.GEMINI_MODEL)

    import google.generativeai as genai
    genai.configure(api_key=settings.GEMINI_API_KEY)

    # Cấu hình Structured Output với Pydantic schema trực tiếp
    generation_config = {
        "response_mime_type": "application/json",
        "response_schema": LLMOutput,
        "temperature": 0.7,
    }

    model = genai.GenerativeModel(
        model_name=settings.GEMINI_MODEL,
        generation_config=generation_config,
        system_instruction=SYSTEM_PROMPT,
    )

    def _messages(user_content: str) -> list:
        # Gemini không có cơ chế messages kiểu OpenAI cho generate_content;
        # ta nối system prompt + user content + feedback thành một prompt.
        return [user_content]

    async def _raw_getter(messages: list) -> str:
        async def _call():
            return await model.generate_content_async(messages[0])
        resp = await _call_with_retry("Gemini", _call)
        return getattr(resp, "text", None)

    return await _parse_with_retry(_raw_getter, _messages, req, "Gemini")


_PROVIDER_FUNCS = {
    "openai": _generate_with_openai,
    "gemini": _generate_with_gemini,
}


def _provider_ready(provider: str) -> bool:
    if provider == "openai":
        return bool(settings.OPENAI_API_KEY)
    if provider == "gemini":
        return bool(settings.GEMINI_API_KEY)
    return False


# ==============================================================================
# FALLBACK GENERATOR (Heuristic — KHÔNG BAO GIỜ fail)
# ==============================================================================

def generate_fallback_presentation(req: GenerateRequest) -> PresentationResponse:
    """Sinh LLMOutput dự phòng bằng thuật toán heuristic rồi chạy qua Layout Engine."""
    logger.info("Dùng Heuristic Fallback Generator cho prompt: %s", req.prompt[:60])

    from app.schemas.slide_schema import ContentCard, RawSlideContent

    num_slides = max(1, min(req.num_slides, 20))
    style = req.style

    # Bảng màu theo style (hex thẻ)
    accent_palettes = {
        "Futuristic": ["#8B5CF6", "#06B6D4", "#EC4899", "#161926", "#1E2235"],
        "Minimal":    ["#6366F1", "#38BDF8", "#10B981", "#1E293B", "#334155"],
        "Corporate":  ["#3A86FF", "#10B981", "#F59E0B", "#1C2541", "#2563EB"],
        "Creative":   ["#D946EF", "#F59E0B", "#06B6D4", "#241438", "#341D4E"],
    }
    accents = accent_palettes.get(style, accent_palettes["Futuristic"])

    title = req.prompt.split("\n")[0].strip()[:60] or "Bài Trình Chiếu ExoticMorph"

    raw_slides: list = []

    # --- Slide 1: Cover (3 thẻ) ---
    raw_slides.append(RawSlideContent(
        slide_number=1,
        slide_title=title,
        cards=[
            ContentCard(
                morph_id="hero_card",
                title="Tổng Quan",
                body=f"Giới thiệu chủ đề: {title}. Các điểm chính sẽ được trình bày trong các slide tiếp theo với hiệu ứng Morph mượt mà.",
                color_theme=accents[0],
                order=0,
            ),
            ContentCard(
                morph_id="col_1",
                title="Điểm Nổi Bật",
                body="Những giá trị cốt lõi và lợi ích nổi trội nhất của giải pháp được làm rõ ở slide sau.",
                color_theme=accents[3],
                order=1,
            ),
            ContentCard(
                morph_id="col_2",
                title="Lộ Trình",
                body="Các bước triển khai và kế hoạch hành động cụ thể sẽ được trình bày chi tiết ở các slide kế tiếp.",
                color_theme=accents[3],
                order=2,
            ),
        ],
    ))

    # --- Slide 2: Chi tiết 3 cột (giữ nguyên morph_id col_1, col_2, hero_card) ---
    if num_slides >= 2:
        raw_slides.append(RawSlideContent(
            slide_number=2,
            slide_title="Phân Tích Chi Tiết 3 Trụ Cột",
            cards=[
                ContentCard(
                    morph_id="hero_card",
                    title="Giá Trị Cốt Lõi",
                    body="Đi sâu vào giá trị chính mà giải pháp mang lại, phân tích các yếu tố then chốt tạo nên thành công.",
                    color_theme=accents[0],
                    order=0,
                ),
                ContentCard(
                    morph_id="col_1",
                    title="Dữ Liệu & Chứng Minh",
                    body="Các số liệu thực tế, nghiên cứu điển hình và bằng chứng thuyết phục minh chứng hiệu quả.",
                    color_theme=accents[1],
                    order=1,
                ),
                ContentCard(
                    morph_id="col_2",
                    title="Giải Pháp Công Nghệ",
                    body="Kiến trúc kỹ thuật, công nghệ sử dụng và khả năng mở rộng trong tương lai.",
                    color_theme=accents[2],
                    order=2,
                ),
            ],
        ))

    # --- Slide 3: 2 thẻ lớn (hero + metric) ---
    if num_slides >= 3:
        raw_slides.append(RawSlideContent(
            slide_number=3,
            slide_title="Kết Quả Đo Lường Được",
            cards=[
                ContentCard(
                    morph_id="hero_card",
                    title="+45% Tăng Trưởng",
                    body="Hiệu suất tăng trưởng vượt trội sau khi áp dụng giải pháp, được đo lường qua các KPI thực tế trong 6 tháng.",
                    color_theme=accents[0],
                    order=0,
                ),
                ContentCard(
                    morph_id="kpi_roi",
                    title="ROI 300%",
                    body="Tỷ lệ hoàn vốn đầu tư đạt 300% trong năm đầu tiên, tiết kiệm 65% chi phí vận hành và nhân lực.",
                    color_theme=accents[4],
                    order=1,
                ),
            ],
        ))

    # --- Slide 4: Roadmap 4 thẻ ---
    if num_slides >= 4:
        raw_slides.append(RawSlideContent(
            slide_number=4,
            slide_title="Lộ Trình Triển Khai",
            cards=[
                ContentCard(
                    morph_id="stage_1",
                    title="Giai Đoạn 1",
                    body="Khởi tạo dự án, thu thập yêu cầu và thiết kế kiến trúc tổng thể.",
                    color_theme=accents[0],
                    order=0,
                ),
                ContentCard(
                    morph_id="stage_2",
                    title="Giai Đoạn 2",
                    body="Phát triển MVP, kiểm thử nội bộ và tinh chỉnh theo phản hồi.",
                    color_theme=accents[3],
                    order=1,
                ),
                ContentCard(
                    morph_id="stage_3",
                    title="Giai Đoạn 3",
                    body="Beta testing với khách hàng chiến lược và tối ưu hiệu năng.",
                    color_theme=accents[3],
                    order=2,
                ),
                ContentCard(
                    morph_id="stage_4",
                    title="Giai Đoạn 4",
                    body="Ra mắt chính thức, mở rộng quy mô và phát triển hệ sinh thái.",
                    color_theme=accents[1],
                    order=3,
                ),
            ],
        ))

    # --- Slide 5: CTA (hero card) ---
    if num_slides >= 5:
        raw_slides.append(RawSlideContent(
            slide_number=5,
            slide_title="Sẵn Sàng Bắt Đầu",
            cards=[
                ContentCard(
                    morph_id="hero_card",
                    title="Hãy Cùng Nhau Kiến Tạo Tương Lai",
                    body="Liên hệ đội ngũ ExoticMorph để bắt đầu hành trình tạo ra những bài thuyết trình ấn tượng. Truy cập GitHub để xem mã nguồn mở.",
                    color_theme=accents[0],
                    order=0,
                ),
            ],
        ))

    # Slide thêm (6..N): 2 thẻ mỗi slide
    if num_slides > 5:
        for s_idx in range(6, num_slides + 1):
            raw_slides.append(RawSlideContent(
                slide_number=s_idx,
                slide_title=f"Chuyên Đề Mở Rộng {s_idx - 5}",
                cards=[
                    ContentCard(
                        morph_id=f"extra_{s_idx}_1",
                        title=f"Phân Tích Sâu #{s_idx - 5}A",
                        body="Nội dung chuyên sâu về khía cạnh kỹ thuật và dữ liệu liên quan đến chủ đề chính.",
                        color_theme=accents[3],
                        order=0,
                    ),
                    ContentCard(
                        morph_id=f"extra_{s_idx}_2",
                        title=f"Phân Tích Sâu #{s_idx - 5}B",
                        body="Đề xuất giải pháp bổ sung và kế hoạch thực thi chi tiết cho các tình huống đặc thù.",
                        color_theme=accents[4],
                        order=1,
                    ),
                ],
            ))

    llm_output = LLMOutput(topic=req.prompt, slides=raw_slides[:num_slides])
    return compute_layout(llm_output, req)


# ==============================================================================
# ENTRY POINT CHÍNH
# ==============================================================================

async def generate_presentation_with_llm(req: GenerateRequest) -> PresentationResponse:
    """Gọi LLM -> nhận LLMOutput (chỉ nội dung) -> chạy Layout Engine -> PresentationResponse.

    Chuỗi chống lỗi 3 tầng:
      1. Provider chính (có retry mạng + retry Pydantic validation).
      2. Provider dự phòng (cross-fallback).
      3. Heuristic Fallback Generator — KHÔNG BAO GIỜ fail.
    """
    provider = settings.LLM_PROVIDER.lower()

    # Xây dựng chuỗi provider thử
    provider_chain: list = []
    if provider != "mock":
        if _provider_ready(provider):
            provider_chain.append(provider)
        else:
            logger.warning("LLM_PROVIDER='%s' chưa có API key — bỏ qua.", provider)
        for alt in ("openai", "gemini"):
            if alt != provider and _provider_ready(alt):
                provider_chain.append(alt)

    for idx, name in enumerate(provider_chain):
        try:
            # 1) Gọi LLM để nhận LLMOutput (strict schema, không geometry)
            raw_output: LLMOutput = await _PROVIDER_FUNCS[name](req)

            # 2) Chạy Python Layout Engine để tính hình học (x, y, w, h)
            presentation = compute_layout(raw_output, req)
            return presentation

        except Exception as exc:  # noqa: BLE001
            is_last = idx == len(provider_chain) - 1
            logger.warning(
                "Provider '%s' thất bại: %s.%s",
                name, exc,
                "" if is_last else " Chuyển sang provider dự phòng...",
            )

    # Fallback cuối cùng: heuristic generator (đã tích hợp sẵn layout engine)
    if provider_chain:
        logger.warning("Tất cả LLM provider đều thất bại — dùng Heuristic Fallback.")
    return generate_fallback_presentation(req)
