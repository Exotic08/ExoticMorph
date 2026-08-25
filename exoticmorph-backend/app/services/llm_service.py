"""
LLM Service Module for ExoticMorph
~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~
Tích hợp OpenAI GPT-4o và Google Gemini 1.5 Pro với Structured JSON Mode
để phân tích prompt, sinh dàn ý và tính toán tọa độ Morph cho từng slide.

Nâng cấp trong đợt rework:
- Retry với exponential backoff cho lỗi tạm thời (429 / rate limit / timeout / 5xx).
- Cross-provider fallback: OpenAI lỗi -> thử Gemini (nếu có key) -> heuristic generator.
- Parser JSON chịu lỗi: bóc JSON khỏi markdown code fence, quét ngoặc cân bằng.
- Sanitizer sửa các lỗi nhỏ của LLM (tọa độ tràn biên, thiếu key) thay vì vứt cả kết quả.
- System Prompt nâng cấp quy tắc tính tọa độ chính xác theo lưới 12 cột.
- Reuse AsyncOpenAI client (connection pooling) + timeout mỗi lần gọi.
"""

import asyncio
import json
import logging
import re
from typing import Any, Callable, Optional, TypeVar

from app.config import settings
from app.schemas.slide_schema import (
    GenerateRequest,
    PresentationResponse,
    Slide,
    SlideElement,
)

logger = logging.getLogger("exoticmorph.llm")

# ==============================================================================
# Cấu hình Retry / Timeout cho LLM
# ==============================================================================
LLM_MAX_ATTEMPTS = 3          # Số lần thử tối đa mỗi provider
LLM_RETRY_BASE_DELAY_S = 1.5  # Backoff: 1.5s -> 3s -> 6s
LLM_REQUEST_TIMEOUT_S = 60.0  # Timeout mỗi lần gọi API

T = TypeVar("T")

# ==============================================================================
# System Prompt: Master Motion Designer & Presentation Architect (v2)
# ==============================================================================
SYSTEM_PROMPT = """Bạn là một "Master Motion Designer & Presentation Architect" hàng đầu thế giới, chuyên gia thiết kế bài thuyết trình PowerPoint chuẩn OpenXML có hiệu ứng Morph chuyển động liền mạch.

NHIỆM VỤ CỦA BẠN:
Nhận chủ đề/prompt từ người dùng và thiết kế một bài trình chiếu hoàn chỉnh. Bạn phải tính toán chính xác bố cục không gian (tọa độ x, y, width, height từ 0.0 đến 100.0%) và đặc biệt là hệ thống liên kết MORPH ID giữa các slide.

QUY TẮC BẮT BUỘC VỀ HIỆU ỨNG MORPH (THE GOLDEN RULES OF MORPHING):
1. **BẢO TOÀN MORPH_ID LIÊN KẾT**:
   - Để PowerPoint tự động biến đổi vật thể giữa Slide N và Slide N+1, hai phần tử tương ứng ở 2 slide BẮT BUỘC PHẢI DÙNG CHUNG MỘT `morph_id` (ví dụ: `card_kpi_1`, `hero_box`, `badge_status`).
   - Ví dụ: Ở Slide 1, một thẻ nằm ở trung tâm (x: 25, y: 30, w: 50, h: 40) với `morph_id: "core_card"`. Sang Slide 2, thẻ đó thu nhỏ và dạt sang góc trái (x: 5, y: 15, w: 25, h: 70) VẪN PHẢI GIỮ NGUYÊN `morph_id: "core_card"`.
   - Đối tượng mới xuất hiện/biến mất thì dùng morph_id MỚI (không trùng với slide trước).

2. **TỌA ĐỘ VÀ KHÔNG GIAN (% MÀN HÌNH) — TÍNH TOÁN SỐ HỌC CHÍNH XÁC**:
   - Hệ tọa độ: (x, y) là góc TRÊN-TRÁI của phần tử; x/width tính theo % chiều ngang, y/height theo % chiều dọc của slide.
   - Lưới chuẩn 12 cột: lề trái/phải 6%; mỗi cột rộng 7.33%; rãnh giữa 2 cột 0.5%.
     Vị trí x căn lưới hợp lệ: 6.0, 13.8, 21.7, 29.5, 37.3, 45.2, 53.0, 60.8, 68.7, 76.5, 84.3, 92.2.
   - TRƯỚC KHI XUẤT JSON, HÃY KIỂM TRA PHÉP TÍNH: bắt buộc x + width <= 94 và y + height <= 92.
   - KHÔNG ĐƯỢC CHỒNG LẤN: hai phần tử bất kỳ trên cùng một slide không được giao nhau (khoảng cách tối thiểu giữa 2 hộp là 1% theo cả 2 trục).
   - Để chuyển động Morph tự nhiên: giữa 2 slide liên tiếp, mỗi morph_id chỉ nên thay đổi TỐI ĐA 2 trong 4 thông số (x, y, width, height). Giữ nguyên trục và chiều rộng nếu chỉ muốn trượt dọc.

3. **FONT SIZE TỶ LỆ VỚI KHỐI** (tránh chữ tràn hộp):
   - height 5-8% -> font 10-12pt | height 10-20% -> font 13-18pt
   - height 20-35% -> font 18-28pt | height > 35% -> font 28-44pt.
   - Badge (height <= 6%) -> font 10-11pt. Metric số lớn -> font 32-44pt.

4. **MÀU SẮC & PHONG CÁCH (THEME PALETTE)**:
   - **Futuristic**: Nền `#090A0F`, Thẻ `#131622`, Chữ `#FFFFFF`, Điểm nhấn `#8B5CF6`, `#06B6D4`, `#EC4899`.
   - **Minimal**: Nền `#0F172A`, Thẻ `#1E293B`, Chữ `#F8FAFC`, Điểm nhấn `#6366F1`, `#38BDF8`.
   - **Corporate**: Nền `#0A1128`, Thẻ `#1C2541`, Chữ `#FFFFFF`, Điểm nhấn `#3A86FF`, `#10B981`.
   - **Creative**: Nền `#120A1F`, Thẻ `#241438`, Chữ `#FFFFFF`, Điểm nhấn `#D946EF`, `#F59E0B`.
   - Tiêu đề slide lớn nhất (28-40pt), nhãn phụ 10-11pt IN HOA, nội dung chính 14-18pt.

5. **SỐ LƯỢNG SLIDE**: PHẢI trả về ĐÚNG BẰNG số slide được yêu cầu trong đề bài (không hơn, không kém).

CẤU TRÚC JSON TRẢ VỀ:
Trả về DUY NHẤT MỘT JSON Object hợp lệ (KHÔNG bọc trong markdown code fence, KHÔNG giải thích thêm) theo đúng Schema:
{
  "topic": string,
  "style": "Futuristic" | "Minimal" | "Corporate" | "Creative",
  "aspect_ratio": "16:9" | "4:3",
  "total_slides": number,
  "morph_strategy": string,
  "slides": [
    {
      "slide_number": number,
      "title": string,
      "subtitle": string,
      "speaker_notes": string,
      "morph_description": string,
      "bg_color": string (hex),
      "elements": [
        {
          "id": string,
          "type": "heading" | "text" | "card" | "metric" | "shape" | "badge",
          "content": string,
          "label": string | null,
          "sub_text": string | null,
          "x": number (0-100),
          "y": number (0-100),
          "width": number (0-100),
          "height": number (0-100),
          "bg_color": string (hex),
          "text_color": string (hex),
          "morph_id": string,
          "font_size": number | null,
          "shape_type": "rounded_rectangle" | "rectangle" | "circle",
          "border_color": string | null
        }
      ]
    }
  ]
}
"""


def _coerce_float(value: Any, default: float) -> float:
    """Ép kiểu an toàn sang float; trả về default nếu LLM trả chuỗi rác."""
    try:
        return float(value)
    except (TypeError, ValueError):
        return default


def _clamp(value: float, lo: float, hi: float) -> float:
    return max(lo, min(value, hi))


def _extract_json_object(text: str) -> dict:
    """Trích JSON object đầu tiên từ phản hồi LLM.

    Chịu được các lỗi format phổ biến:
    - LLM bọc JSON trong markdown code fence ```json ... ```
    - Văn bản giải thích thừa trước/sau khối JSON.
    """
    if not text or not text.strip():
        raise ValueError("LLM trả về nội dung rỗng")

    cleaned = text.strip()

    # Bóc khỏi markdown code fence nếu có (rất phổ biến kể cả khi đã bật JSON mode).
    fence_match = re.match(r"^```[a-zA-Z]*\s*(.*?)\s*```$", cleaned, re.DOTALL)
    if fence_match:
        cleaned = fence_match.group(1).strip()

    # Thử parse thẳng cả chuỗi trước (nhanh nhất).
    try:
        parsed = json.loads(cleaned)
        if isinstance(parsed, dict):
            return parsed
    except json.JSONDecodeError:
        pass

    # Quét tìm object có ngoặc nhọn cân bằng đầu tiên (xử lý chuỗi có chứa '{').
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
                        break  # object này hỏng -> quét '{' kế tiếp
        start = cleaned.find("{", start + 1)

    raise ValueError("Không tìm thấy JSON object hợp lệ trong phản hồi của LLM")


def _sanitize_llm_payload(data: dict, req: GenerateRequest) -> dict:
    """Sửa các lỗi 'vặt' thường gặp của LLM thay vì vứt bỏ toàn bộ kết quả
    (mỗi lần vứt bỏ là một lần gọi API tốn tiền + người dùng chờ thêm).

    Các lỗi được sửa: tọa độ tràn biên, thiếu morph_id, thiếu key bắt buộc,
    style/aspect_ratio sai giá trị, slide_number sai thứ tự, thiếu slides.
    """
    if not isinstance(data, dict):
        raise ValueError("LLM trả về không phải JSON object")

    raw_slides = data.get("slides")
    if not isinstance(raw_slides, list) or not raw_slides:
        raise ValueError("LLM không trả về slide nào")

    clean_slides: list[dict] = []
    for slide in raw_slides:
        if not isinstance(slide, dict):
            continue
        raw_elements = slide.get("elements")
        if not isinstance(raw_elements, list):
            raw_elements = []

        clean_elements: list[dict] = []
        for elem in raw_elements:
            if not isinstance(elem, dict):
                continue
            # Kéo tọa độ về trong biên [0, 100] — ưu tiên giữ nguyên kích thước.
            x = _clamp(_coerce_float(elem.get("x"), 6.0), 0.0, 100.0)
            y = _clamp(_coerce_float(elem.get("y"), 8.0), 0.0, 100.0)
            w = _clamp(_coerce_float(elem.get("width"), 20.0), 1.0, 100.0)
            h = _clamp(_coerce_float(elem.get("height"), 10.0), 1.0, 100.0)
            elem["x"], elem["y"], elem["width"], elem["height"] = x, y, w, h
            if not elem.get("morph_id"):
                elem["morph_id"] = f"obj_{len(clean_elements) + 1}"
            if not elem.get("id"):
                elem["id"] = f"el_{len(clean_elements) + 1}"
            elem.setdefault("content", "")
            clean_elements.append(elem)

        slide["elements"] = clean_elements
        clean_slides.append(slide)

    if not clean_slides:
        raise ValueError("Tất cả slide do LLM sinh ra đều không hợp lệ")

    # Cắt bớt nếu LLM sinh nhiều hơn số slide yêu cầu.
    if len(clean_slides) > req.num_slides:
        logger.warning(
            "LLM sinh %d slide (yêu cầu %d) — cắt bớt cho đúng yêu cầu.",
            len(clean_slides), req.num_slides,
        )
        clean_slides = clean_slides[:req.num_slides]

    # Đánh lại số thứ tự slide liên tục 1..N.
    for idx, slide in enumerate(clean_slides, start=1):
        slide["slide_number"] = idx

    data["slides"] = clean_slides
    data["total_slides"] = len(clean_slides)

    # Ép style/aspect_ratio theo lựa chọn của người dùng (LLL hay quên).
    if data.get("style") not in ("Futuristic", "Minimal", "Corporate", "Creative"):
        data["style"] = req.style
    if data.get("aspect_ratio") not in ("16:9", "4:3"):
        data["aspect_ratio"] = req.aspect_ratio
    if not data.get("topic"):
        data["topic"] = req.prompt

    return data


def _is_transient_error(exc: Exception) -> bool:
    """Phân biệt lỗi tạm thời (đáng retry) với lỗi logic (retry cũng vô ích).

    Lỗi tạm thời: HTTP 429 (rate limit), 5xx, mất kết nối, timeout.
    Lỗi logic: JSON sai định dạng, thiếu key... -> chuyển fallback ngay.
    """
    status = getattr(exc, "status_code", None)
    if isinstance(status, int) and status in (408, 429, 500, 502, 503, 504):
        return True
    # Tên class của openai/google SDK: không import cứng để tránh phụ thuộc thời
    # điểm import — so khớp theo tên là đủ an toàn cho mục đích retry.
    name = type(exc).__name__
    return name in {
        "APIConnectionError", "APITimeoutError", "APIConnectionTimeoutError",
        "TimeoutError", "ConnectError", "ReadTimeout", "RemoteProtocolError",
    }


async def _call_with_retry(
    provider_name: str,
    operation: Callable[[], Any],
) -> Any:
    """Thực thi coroutine factory với retry + exponential backoff.

    `operation` phải là hàm trả về coroutine MỚI mỗi lần gọi (không reuse
    coroutine đã await — await lại coroutine cũ là no-op và gây bug ngầm).
    """
    last_exc: Optional[Exception] = None
    for attempt in range(1, LLM_MAX_ATTEMPTS + 1):
        try:
            # asyncio.wait_for đảm bảo request không treo vô hạn làm UI
            # phía Frontend rơi vào trạng thái Loading vĩnh viễn.
            return await asyncio.wait_for(operation(), timeout=LLM_REQUEST_TIMEOUT_S)
        except asyncio.TimeoutError:
            last_exc = TimeoutError(f"{provider_name} vượt quá {LLM_REQUEST_TIMEOUT_S:.0f}s")
            retryable = True
        except Exception as exc:  # noqa: BLE001 — cần bắt rộng để phân loại
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

    raise last_exc  # pragma: no cover — vòng lặp luôn return/raise bên trong


# ==============================================================================
# OpenAI client: khởi tạo MỘT lần duy nhất để tái sử dụng connection pool
# (bản cũ tạo AsyncOpenAI mới cho mỗi request -> bắt tay TLS lặp lại, tốn latency).
# ==============================================================================
_openai_client: Optional[Any] = None


def _get_openai_client() -> Any:
    global _openai_client
    if _openai_client is None:
        from openai import AsyncOpenAI
        _openai_client = AsyncOpenAI(
            api_key=settings.OPENAI_API_KEY,
            timeout=LLM_REQUEST_TIMEOUT_S,
            max_retries=0,  # Tự quản lý retry ở _call_with_retry (tránh retry chồng)
        )
    return _openai_client


def _build_user_prompt(req: GenerateRequest) -> str:
    return f"""YÊU CẦU CỦA NGƯỜI DÙNG:
Chủ đề: {req.prompt}
Số lượng slide: {req.num_slides} (PHẢI đúng con số này)
Phong cách: {req.style}
Tỉ lệ khung hình: {req.aspect_ratio}
Ngôn ngữ nội dung: {req.language}
Sinh speaker notes: {"Có" if req.include_speaker_notes else "Không"}

Hãy tính toán chính xác tọa độ Morphing (kiểm tra x+width<=94, y+height<=92, không chồng lấn)
và trả về JSON PresentationResponse đầy đủ, đúng schema, không markdown fence."""


def _parse_llm_response(raw_text: Optional[str], req: GenerateRequest, provider: str) -> PresentationResponse:
    """Pipeline: trích JSON -> sanitize -> validate Pydantic."""
    data = _extract_json_object(raw_text or "")
    data = _sanitize_llm_payload(data, req)
    parsed = PresentationResponse.model_validate(data)
    logger.info("%s đã sinh thành công %d slide!", provider, len(parsed.slides))
    return parsed


async def _generate_with_openai(req: GenerateRequest) -> PresentationResponse:
    logger.info("Đang gọi OpenAI Model %s với JSON Mode...", settings.OPENAI_MODEL)

    async def _call() -> Any:
        client = _get_openai_client()
        return await client.chat.completions.create(
            model=settings.OPENAI_MODEL,
            messages=[
                {"role": "system", "content": SYSTEM_PROMPT},
                {"role": "user", "content": _build_user_prompt(req)},
            ],
            response_format={"type": "json_object"},
            temperature=0.7,
        )

    response = await _call_with_retry("OpenAI", _call)
    content = response.choices[0].message.content if response.choices else None
    return _parse_llm_response(content, req, "OpenAI")


async def _generate_with_gemini(req: GenerateRequest) -> PresentationResponse:
    logger.info("Đang gọi Google Gemini Model %s...", settings.GEMINI_MODEL)
    import google.generativeai as genai

    genai.configure(api_key=settings.GEMINI_API_KEY)
    model = genai.GenerativeModel(
        model_name=settings.GEMINI_MODEL,
        generation_config={"response_mime_type": "application/json"},
    )

    prompt_full = (
        f"{SYSTEM_PROMPT}\n\n{_build_user_prompt(req)}"
    )

    async def _call() -> Any:
        return await model.generate_content_async(prompt_full)

    response = await _call_with_retry("Gemini", _call)
    return _parse_llm_response(getattr(response, "text", None), req, "Gemini")


_PROVIDER_FUNCS = {
    "openai": _generate_with_openai,
    "gemini": _generate_with_gemini,
}


def _provider_ready(provider: str) -> bool:
    """Provider chỉ sẵn sàng khi có API key tương ứng."""
    if provider == "openai":
        return bool(settings.OPENAI_API_KEY)
    if provider == "gemini":
        return bool(settings.GEMINI_API_KEY)
    return False


def generate_fallback_presentation(req: GenerateRequest) -> PresentationResponse:
    """Hàm sinh dữ liệu dự phòng thông minh (Heuristic Fallback Generator)
    khi chưa có API Key hoặc khi dịch vụ AI bên ngoài gặp sự cố mạng.
    Đảm bảo 100% hệ thống luôn hoạt động mượt mà và trả về dữ liệu đúng schema.
    """
    logger.info("Sử dụng Heuristic Fallback Generator cho prompt: %s", req.prompt[:60])

    # Schema cho phép tối đa 20 slide — đồng bộ với GenerateRequest.num_slides.
    num_slides = max(1, min(req.num_slides, 20))
    style = req.style

    # Bảng màu theo style
    palettes = {
        "Futuristic": {
            "bg": "#090A0F",
            "card1": "#161926",
            "card2": "#1E2235",
            "accent1": "#8B5CF6",
            "accent2": "#06B6D4",
            "accent3": "#EC4899",
            "text": "#FFFFFF",
            "sub": "#94A3B8"
        },
        "Minimal": {
            "bg": "#0F172A",
            "card1": "#1E293B",
            "card2": "#334155",
            "accent1": "#6366F1",
            "accent2": "#38BDF8",
            "accent3": "#10B981",
            "text": "#F8FAFC",
            "sub": "#CBD5E1"
        },
        "Corporate": {
            "bg": "#0A1128",
            "card1": "#141F36",
            "card2": "#1E2D4A",
            "accent1": "#2563EB",
            "accent2": "#10B981",
            "accent3": "#F59E0B",
            "text": "#FFFFFF",
            "sub": "#94A3B8"
        },
        "Creative": {
            "bg": "#120A1F",
            "card1": "#241438",
            "card2": "#341D4E",
            "accent1": "#D946EF",
            "accent2": "#F59E0B",
            "accent3": "#06B6D4",
            "text": "#FFFFFF",
            "sub": "#E2E8F0"
        }
    }
    p = palettes.get(style, palettes["Futuristic"])

    # Tạo tiêu đề sạch
    title = req.prompt.split("\n")[0].strip()
    if len(title) > 60:
        title = title[:60] + "..."
    if not title:
        title = "Chiến Lược Đột Phá AI ExoticMorph"

    def notes(slide_number: int, slide_title: str) -> Optional[str]:
        """Sinh lời dẫn ngắn gọn cho từng slide (nếu người dùng bật tùy chọn)."""
        if not req.include_speaker_notes:
            return None
        return (
            f"Lời dẫn slide {slide_number}: Trình bày trọng tâm '{slide_title}'. "
            "Giữ nhịp chậm ở các con số then chốt và nhấn mạnh chuyển động Morph khi đổi slide."
        )

    slides: list[Slide] = []

    # ==================== SLIDE 1: COVER HERO ====================
    slides.append(
        Slide(
            slide_number=1,
            title=title,
            subtitle=f"Bản trình chiếu tối ưu hóa Morph tự động ({style} Style)",
            speaker_notes=notes(1, title),
            morph_description="Khối tiêu đề chính phóng to và 3 thẻ tóm tắt dạt sang 3 cột ở slide tiếp theo",
            bg_color=p["bg"],
            elements=[
                SlideElement(
                    id="s1_badge",
                    type="badge",
                    content="EXOTICMORPH AI ENGINE",
                    x=6.0, y=10.0, width=28.0, height=6.0,
                    bg_color=p["accent1"],
                    text_color="#FFFFFF",
                    morph_id="badge_header",
                    font_size=11,
                ),
                SlideElement(
                    id="s1_card_main",
                    type="card",
                    content=title,
                    label="TỔNG QUAN CHIẾN LƯỢC",
                    sub_text="Chuyển đổi số & Tự động hóa bài thuyết trình bằng Generative AI",
                    x=6.0, y=20.0, width=88.0, height=36.0,
                    bg_color=p["card1"],
                    text_color=p["text"],
                    morph_id="morph_card_main",
                    font_size=24,
                ),
                SlideElement(
                    id="s1_card_sub1",
                    type="card",
                    content="Tăng trưởng +45%",
                    label="Mục tiêu cốt lõi",
                    x=6.0, y=60.0, width=27.0, height=28.0,
                    bg_color=p["card2"],
                    text_color=p["text"],
                    morph_id="morph_col_1",
                    font_size=16,
                ),
                SlideElement(
                    id="s1_card_sub2",
                    type="card",
                    content="Kiến trúc Microservices",
                    label="Giải pháp kỹ thuật",
                    x=36.5, y=60.0, width=27.0, height=28.0,
                    bg_color=p["card2"],
                    text_color=p["text"],
                    morph_id="morph_col_2",
                    font_size=16,
                ),
                SlideElement(
                    id="s1_card_sub3",
                    type="card",
                    content="Go-to-Market Q4",
                    label="Lộ trình thương mại",
                    x=67.0, y=60.0, width=27.0, height=28.0,
                    bg_color=p["card2"],
                    text_color=p["text"],
                    morph_id="morph_col_3",
                    font_size=16,
                ),
            ]
        )
    )

    # ==================== SLIDE 2: EXPANDED COLUMNS ====================
    if num_slides >= 2:
        slides.append(
            Slide(
                slide_number=2,
                title="Phân Tích Chi Tiết 3 Trụ Cột Trọng Tâm",
                subtitle="Dữ liệu và giải pháp chuyển đổi liền mạch từ tổng quan",
                speaker_notes=notes(2, "Phân Tích Chi Tiết 3 Trụ Cột Trọng Tâm"),
                morph_description="3 Thẻ nhỏ ở đáy Slide 1 mở rộng toàn màn hình thành 3 cột chi tiết tại Slide 2",
                bg_color=p["bg"],
                elements=[
                    SlideElement(
                        id="s2_badge",
                        type="badge",
                        content="TRỤ CỘT CHIẾN LƯỢC",
                        x=6.0, y=10.0, width=24.0, height=6.0,
                        bg_color=p["accent2"],
                        text_color="#FFFFFF",
                        morph_id="badge_header",
                        font_size=11,
                    ),
                    SlideElement(
                        id="s2_card_1",
                        type="card",
                        content="Chỉ Số Tăng Trưởng & Traction",
                        label="TRỤ CỘT 01",
                        sub_text="• Doanh thu ARR đạt $12.5M (+45% YoY)\n• 1,200+ Doanh nghiệp Enterprise\n• Retention Rate duy trì mức 128%",
                        x=6.0, y=20.0, width=27.0, height=68.0,
                        bg_color=p["card1"],
                        text_color=p["text"],
                        morph_id="morph_col_1",  # CÙNG ID VỚI SLIDE 1
                        font_size=15,
                    ),
                    SlideElement(
                        id="s2_card_2",
                        type="card",
                        content="Kiến Trúc Hệ Thống & AI Core",
                        label="TRỤ CỘT 02",
                        sub_text="• Khả năng chịu tải 100K TPS\n• Tự động khớp tọa độ Morph XML\n• Pipeline biên dịch OpenXML < 3s",
                        x=36.5, y=20.0, width=27.0, height=68.0,
                        bg_color=p["card1"],
                        text_color=p["text"],
                        morph_id="morph_col_2",  # CÙNG ID VỚI SLIDE 1
                        font_size=15,
                    ),
                    SlideElement(
                        id="s2_card_3",
                        type="card",
                        content="Kế Hoạch Triển Khai & Phân Phối",
                        label="TRỤ CỘT 03",
                        sub_text="• Mở rộng thị trường APAC & US\n• Tích hợp trực tiếp Microsoft Office\n• Đào tạo chuyển giao công nghệ",
                        x=67.0, y=20.0, width=27.0, height=68.0,
                        bg_color=p["card1"],
                        text_color=p["text"],
                        morph_id="morph_col_3",  # CÙNG ID VỚI SLIDE 1
                        font_size=15,
                    ),
                ]
            )
        )

    # ==================== SLIDE 3: METRIC FOCUS & HIGHLIGHT ====================
    if num_slides >= 3:
        slides.append(
            Slide(
                slide_number=3,
                title="Đột Phá Hiệu Suất Vận Hành & ROI",
                subtitle="Cột 1 thu về góc trái và khối số liệu trọng tâm phóng đại toàn diện",
                speaker_notes=notes(3, "Đột Phá Hiệu Suất Vận Hành & ROI"),
                morph_description="Cột số 1 biến đổi thành thẻ chỉ số khổng lồ bên phải màn hình",
                bg_color=p["bg"],
                elements=[
                    SlideElement(
                        id="s3_badge",
                        type="badge",
                        content="HIỆU QUẢ ĐẦU TƯ",
                        x=6.0, y=10.0, width=22.0, height=6.0,
                        bg_color=p["accent3"],
                        text_color="#FFFFFF",
                        morph_id="badge_header",
                        font_size=11,
                    ),
                    SlideElement(
                        id="s3_sidebar",
                        type="card",
                        content="Tổng Kết Các Lợi Thế",
                        label="TÓM LƯỢC NHANH",
                        sub_text="• Tốc độ tạo slide x10\n• Không cần plugin add-in\n• File tương thích 100%",
                        x=6.0, y=20.0, width=27.0, height=68.0,
                        bg_color=p["card1"],
                        text_color=p["text"],
                        morph_id="morph_col_1",  # CÙNG ID VỚI SLIDE 1 & 2
                        font_size=15,
                    ),
                    SlideElement(
                        id="s3_giant_kpi",
                        type="metric",
                        content="99.995%",
                        label="ĐỘ SẴN SÀNG HỆ THỐNG SLA",
                        sub_text="Vận hành liên tục đa vùng (Multi-Region Active-Active) với độ trễ phản hồi dưới 5ms.",
                        x=36.5, y=20.0, width=57.5, height=32.0,
                        bg_color=p["card2"],
                        text_color=p["accent2"],
                        morph_id="morph_card_main",  # CÙNG ID VỚI SLIDE 1
                        font_size=36,
                    ),
                    SlideElement(
                        id="s3_sub_kpi",
                        type="card",
                        content="Tiết kiệm 65% Chi phí Vận hành",
                        label="TỐI ƯU HÓA NGUỒN LỰC",
                        sub_text="Giảm thiểu 80% thời gian thiết kế thủ công cho đội ngũ Sales & Marketing.",
                        x=36.5, y=56.0, width=57.5, height=32.0,
                        bg_color=p["card1"],
                        text_color=p["text"],
                        morph_id="morph_col_2",  # CÙNG ID VỚI SLIDE 2
                        font_size=18,
                    ),
                ]
            )
        )

    # ==================== SLIDE 4 & 5 (NẾU YÊU CẦU >= 4) ====================
    if num_slides >= 4:
        slides.append(
            Slide(
                slide_number=4,
                title="Lộ Trình Triển Khai Chi Tiết (Roadmap)",
                subtitle="Các mốc thời gian chuyển đổi từ Pilot sang Enterprise Scale",
                speaker_notes=notes(4, "Lộ Trình Triển Khai Chi Tiết"),
                morph_description="Các khối thông tin sắp xếp lại thành dòng thời gian 4 giai đoạn nối tiếp",
                bg_color=p["bg"],
                elements=[
                    SlideElement(
                        id="s4_stage1",
                        type="card",
                        content="Giai đoạn 1: Q1/2025",
                        label="HOÀN THIỆN MVP",
                        sub_text="Ra mắt phiên bản Web App & Morph XML Compiler",
                        x=6.0, y=24.0, width=20.5, height=60.0,
                        bg_color=p["card1"],
                        text_color=p["text"],
                        morph_id="roadmap_s1",
                        font_size=14,
                    ),
                    SlideElement(
                        id="s4_stage2",
                        type="card",
                        content="Giai đoạn 2: Q2/2025",
                        label="TÍCH HỢP LLM AGENTS",
                        sub_text="Hỗ trợ GPT-4o, Gemini và tối ưu hóa chuyển động 60fps",
                        x=28.5, y=24.0, width=20.5, height=60.0,
                        bg_color=p["card2"],
                        text_color=p["text"],
                        morph_id="roadmap_s2",
                        font_size=14,
                    ),
                    SlideElement(
                        id="s4_stage3",
                        type="card",
                        content="Giai đoạn 3: Q3/2025",
                        label="MỞ RỘNG THƯƠNG MẠI",
                        sub_text="Mở rộng gói Enterprise và tích hợp Google Slides / Figma",
                        x=51.0, y=24.0, width=20.5, height=60.0,
                        bg_color=p["card1"],
                        text_color=p["text"],
                        morph_id="roadmap_s3",
                        font_size=14,
                    ),
                    SlideElement(
                        id="s4_stage4",
                        type="card",
                        content="Giai đoạn 4: Q4/2025",
                        label="HỆ SINH THÁI TOÀN CẦU",
                        sub_text="Cung cấp API cho bên thứ 3 và kho Template Marketplace",
                        x=73.5, y=24.0, width=20.5, height=60.0,
                        bg_color=p["card2"],
                        text_color=p["text"],
                        morph_id="roadmap_s4",
                        font_size=14,
                    ),
                ]
            )
        )

    if num_slides >= 5:
        slides.append(
            Slide(
                slide_number=5,
                title="Tổng Kết & Kêu Gọi Hành Động (Call to Action)",
                subtitle="Sẵn sàng kiến tạo những bài thuyết trình ấn tượng cùng ExoticMorph",
                speaker_notes=notes(5, "Tổng Kết & Kêu Gọi Hành Động"),
                morph_description="Tất cả các khối hội tụ về trung tâm tạo nên thẻ kết luận mạnh mẽ",
                bg_color=p["bg"],
                elements=[
                    SlideElement(
                        id="s5_badge",
                        type="badge",
                        content="SẴN SÀNG HỢP TÁC",
                        x=35.0, y=14.0, width=30.0, height=6.0,
                        bg_color=p["accent1"],
                        text_color="#FFFFFF",
                        morph_id="badge_header",
                        font_size=12,
                    ),
                    SlideElement(
                        id="s5_main_cta",
                        type="card",
                        content="Bắt Đầu Trải Nghiệm ExoticMorph Ngay Hôm Nay",
                        label="HÀNH ĐỘNG NGAY",
                        sub_text="Truy cập https://github.com/Exotic08/ExoticMorph để xem mã nguồn và tài liệu đầy đủ.",
                        x=15.0, y=24.0, width=70.0, height=60.0,
                        bg_color=p["card1"],
                        text_color=p["text"],
                        morph_id="morph_card_main",  # CÙNG ID VỚI SLIDE 1 & 3
                        font_size=24,
                    ),
                ]
            )
        )

    # Tạo thêm slide nếu người dùng yêu cầu 6-20 slide
    if num_slides > 5:
        for s_idx in range(6, num_slides + 1):
            slide_title = f"Chuyên Đề Mở Rộng #{s_idx - 5}: Phân Tích Kỹ Thuật"
            slides.append(
                Slide(
                    slide_number=s_idx,
                    title=slide_title,
                    subtitle="Đào sâu vào các chi tiết cấu trúc và số liệu cụ thể",
                    speaker_notes=notes(s_idx, slide_title),
                    morph_description=f"Slide {s_idx} tiếp nối chuyển động từ slide trước",
                    bg_color=p["bg"],
                    elements=[
                        SlideElement(
                            id=f"s{s_idx}_c1",
                            type="card",
                            content=f"Thông số vận hành Module {s_idx - 5}",
                            label="DỮ LIỆU CHUYÊN SÂU",
                            sub_text="Tự động phân tích và tối ưu hóa ma trận chuyển đổi tọa độ OpenXML.",
                            x=6.0, y=24.0, width=42.0, height=60.0,
                            bg_color=p["card1"],
                            text_color=p["text"],
                            morph_id=f"extra_card_{s_idx}_1",
                            font_size=16,
                        ),
                        SlideElement(
                            id=f"s{s_idx}_c2",
                            type="card",
                            content="Độ tin cậy & SLA",
                            label="TIÊU CHUẨN ĐÁNH GIÁ",
                            sub_text="Đạt chuẩn kiểm định tương thích Microsoft Office OpenXML.",
                            x=52.0, y=24.0, width=42.0, height=60.0,
                            bg_color=p["card2"],
                            text_color=p["text"],
                            morph_id=f"extra_card_{s_idx}_2",
                            font_size=16,
                        ),
                    ]
                )
            )

    return PresentationResponse(
        topic=req.prompt,
        style=req.style,
        aspect_ratio=req.aspect_ratio,
        total_slides=len(slides),
        slides=slides,
        morph_strategy="Liên kết đối tượng xuyên suốt các slide bằng Morph ID đồng bộ hóa tọa độ hình học."
    )


async def generate_presentation_with_llm(req: GenerateRequest) -> PresentationResponse:
    """Gọi LLM (OpenAI GPT-4o hoặc Google Gemini) với Structured Output để sinh dữ liệu.

    Chuỗi chống lỗi 3 tầng:
      1. Provider chính (theo LLM_PROVIDER) — có retry + exponential backoff.
      2. Provider còn lại (nếu có key) — cross-fallback khi provider chính chết.
      3. Heuristic Fallback Generator — KHÔNG BAO GIỜ fail (luôn trả schema đúng).
    """
    provider = settings.LLM_PROVIDER.lower()

    # Xây dựng chuỗi provider sẽ thử, ví dụ: ["openai", "gemini"] hoặc ["gemini", "openai"].
    provider_chain: list[str] = []
    if provider != "mock":
        if _provider_ready(provider):
            provider_chain.append(provider)
        else:
            logger.warning(
                "LLM_PROVIDER='%s' nhưng chưa cấu hình API key — bỏ qua provider này.",
                provider,
            )
        for alt in ("openai", "gemini"):
            if alt != provider and _provider_ready(alt):
                provider_chain.append(alt)

    for idx, name in enumerate(provider_chain):
        try:
            return await _PROVIDER_FUNCS[name](req)
        except Exception as exc:  # noqa: BLE001 — fallback phải bắt mọi thứ
            is_last = idx == len(provider_chain) - 1
            logger.warning(
                "Provider '%s' thất bại sau %d lần thử: %s.%s",
                name, LLM_MAX_ATTEMPTS, exc,
                "" if is_last else " Chuyển sang provider dự phòng...",
            )

    # Fallback Heuristic Generator (Luôn đảm bảo hoạt động an toàn & tin cậy)
    if provider_chain:
        logger.warning("Tất cả LLM provider đều thất bại — dùng Heuristic Fallback Generator.")
    return generate_fallback_presentation(req)
