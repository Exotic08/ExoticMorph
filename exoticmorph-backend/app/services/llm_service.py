"""
LLM Service Module for ExoticMorph (Refactored v4)
~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~
FIX LỖI NỘI DUNG KHÔNG BÁM SÁT CHỦ ĐỀ (v4 fixes):
  1. **Topic Adherence Rule được đẩy lên ƯU TIÊN SỐ 1** trong System Prompt,
     kèm cảnh báo nghiêm ngặt chống copy Few-Shot content.
  2. **Few-Shot được làm trừu tượng (Abstract Examples)** — các ví dụ JSON
     dùng placeholder rõ ràng "[NỘI DUNG VÍ DỤ - KHÔNG SAO CHÉP]" thay vì
     nội dung cụ thể (tránh Few-Shot Contamination).
  3. **User Prompt được bao bọc bằng delimiter rõ ràng**
     (=== USER TOPIC TO GENERATE === ... === END OF USER TOPIC ===).
  4. **Temperature = 0.4** (giảm từ 0.7 để bám chặt chủ đề hơn, vẫn đủ sáng tạo).
  5. **Logging toàn bộ prompt flow** (để audit biến req.prompt có bị mất hay không).
"""

import asyncio
import json
import logging
import re
from typing import Any, Callable, Optional, TypeVar

from app.config import settings
from app.schemas.slide_schema import (
    GenerateRequest,
    LLMOutput,
    PresentationResponse,
)
from app.services.layout_engine import CARD_ACCENTS, compute_layout

logger = logging.getLogger("exoticmorph.llm")

# ==============================================================================
# CẤU HÌNH
# ==============================================================================
LLM_MAX_ATTEMPTS = 3              # Retry lỗi tạm thời (mạng/rate-limit/5xx)
LLM_RETRY_BASE_DELAY_S = 1.5
LLM_REQUEST_TIMEOUT_S = 90.0
MAX_VALIDATION_RETRIES = 2        # Retry khi Pydantic Validation fail

# ⚠️ FIX: Nhiệt độ LLM hạ từ 0.7 → 0.4 để bám chủ đề, bớt ngẫu hứng.
# (0.0 quá lặp/lạnh, 0.7+ dễ bịa chuyện lệch topic, 0.4 cân bằng tốt).
LLM_TEMPERATURE = 0.4

T = TypeVar("T")


# ==============================================================================
# FEW-SHOT EXAMPLES — DẠNG ABSTRACT (KHÔNG CHỨA NỘI DUNG CỤ THỂ)
# ==============================================================================
# QUAN TRỌNG: Các ví dụ này CHỈ dùng để minh hoẠ CẤU TRÚC JSON.
# Nội dung (topic, title, description) được viết dạng placeholder [VÍ DỤ] rõ ràng
# để LLM KHÔNG copy nội dung vào output thực tế. Đây là fix chính cho
# lỗi Few-Shot Contamination (ví dụ: "Hệ Mặt Trời" cứ lặp lại).

_FEW_SHOT_EXAMPLE_1 = json.dumps({
    "topic": "[CHỦ ĐỀ CỦA NGƯỜI DÙNG]",
    "slides": [
        {
            "slide_number": 1,
            "section": "VẤN ĐỀ",
            "slide_title": "[THÔNG ĐIỆP CỤ THỂ: vấn đề hoặc luận điểm + con số/mốc thời gian]",
            "cards": [
                {"morph_id": "card_1", "title": "[THÔNG ĐIỆP CỤ THỂ 1]", "description": "[2-4 câu: dữ kiện định lượng hoặc mốc thời gian, ví dụ thực tế và quan hệ nhân quả của nó với chủ đề.]", "color_theme": "#8B5CF6", "order": 0},
                {"morph_id": "card_2", "title": "[THÔNG ĐIỆP CỤ THỂ 2]", "description": "[2-4 câu: cơ chế hoặc luận điểm riêng biệt, kèm bằng chứng cụ thể và ý nghĩa thực tiễn.]", "color_theme": "#10B981", "order": 1},
                {"morph_id": "card_3", "title": "[THÔNG ĐIỆP CỤ THỂ 3]", "description": "[2-4 câu: ví dụ hoặc số liệu liên quan trực tiếp, giải thích rõ bản chất vấn đề.]", "color_theme": "#06B6D4", "order": 2}
            ]
        },
        {
            "slide_number": 2,
            "section": "NGUYÊN NHÂN",
            "slide_title": "[THÔNG ĐIỆP CỤ THỂ KẾ TIẾP — mở rộng từ slide 1]",
            "cards": [
                {"morph_id": "card_1", "title": "[MỞ RỘNG THÔNG ĐIỆP 1]", "description": "[2-4 câu: phân tích nguyên nhân gốc rễ, dữ kiện và hệ quả cụ thể.]", "color_theme": "#8B5CF6", "order": 0},
                {"morph_id": "card_2", "title": "[MỞ RỘNG THÔNG ĐIỆP 2]", "description": "[2-4 câu: rào cản và cơ chế vận hành, kèm ví dụ minh hoạ.]", "color_theme": "#10B981", "order": 1},
                {"morph_id": "card_3", "title": "[MỞ RỘNG THÔNG ĐIỆP 3]", "description": "[2-4 câu: luận điểm bổ sung có dữ kiện và quan hệ nhân quả rõ ràng.]", "color_theme": "#06B6D4", "order": 2}
            ]
        }
    ]
}, ensure_ascii=False, indent=2)

_FEW_SHOT_EXAMPLE_2 = json.dumps({
    "topic": "[CHỦ ĐỀ KHÁC CỦA NGƯỜI DÙNG]",
    "slides": [
        {
            "slide_number": 1,
            "section": "HÀNH ĐỘNG",
            "slide_title": "[THÔNG ĐIỆP CỤ THỂ: lộ trình hoặc kế hoạch hành động]",
            "cards": [
                {"morph_id": "card_1", "title": "[BƯỚC 1 — thông điệp cụ thể]", "description": "[2-4 câu: hành động đầu tiên, người chịu trách nhiệm và mốc thời gian.]", "color_theme": "#8B5CF6", "order": 0},
                {"morph_id": "card_2", "title": "[BƯỚC 2 — thông điệp cụ thể]", "description": "[2-4 câu: bước tiếp theo, nguồn lực cần và tiêu chí hoàn thành.]", "color_theme": "#10B981", "order": 1},
                {"morph_id": "card_3", "title": "[BƯỚC 3 — thông điệp cụ thể]", "description": "[2-4 câu: triển khai thí điểm và cách đo lường kết quả.]", "color_theme": "#06B6D4", "order": 2},
                {"morph_id": "card_4", "title": "[BƯỚC 4 — thông điệp cụ thể]", "description": "[2-4 câu: đánh giá, học hỏi và nhân rộng mô hình thành công.]", "color_theme": "#EC4899", "order": 3}
            ]
        }
    ]
}, ensure_ascii=False, indent=2)


# ==============================================================================
# SYSTEM PROMPT (v4 — Topic Adherence ƯU TIÊN SỐ 1)
# ==============================================================================
# ⚠️ KHÔNG dùng f-string cho phần JSON examples để tránh xung đột ngoặc nhọn
# với Python format. Examples được gắn vào bằng .replace() ở cuối, an toàn 100%.

SYSTEM_PROMPT_TEMPLATE = """Bạn là "Executive Presentation Architect" — kiến trúc sư nội dung trình chiếu hàng đầu, chuyên viết nội dung PowerPoint có hiệu ứng Morph đạt chuẩn Apple Keynote / McKinsey: sâu, thực tế, mỗi tiêu đề là một thông điệp.

══════════════════════════════════════════════════════════════════════
🚨 QUY TẮC QUAN TRỌNG NHẤT — TOPIC ADHERENCE (KHÔNG ĐƯỢC VI PHẠM) 🚨
══════════════════════════════════════════════════════════════════════

1. **BÁM SÁT 100% CHỦ ĐỀ NGƯỜI DÙNG** — nội dung nằm giữa hai dòng
   "=== USER TOPIC TO GENERATE ===" và "=== END OF USER TOPIC ===" bên dưới.
2. **KHÔNG bịa nội dung chung chung, KHÔNG copy placeholder/số liệu từ ví dụ.**
   Mọi chữ trong ngoặc vuông [NHƯ THẾ NÀY] phải được thay bằng nội dung THẬT
   liên quan trực tiếp đến USER TOPIC.
3. `topic` PHẢI là đúng chủ đề người dùng nhập (hoặc tóm tắt đúng chủ đề đó).

══════════════════════════════════════════════════════════════════════
🚫 STRICT BAN LIST — TUYỆT ĐỐI KHÔNG DÙNG (title, slide_title, section):
══════════════════════════════════════════════════════════════════════
"Giới thiệu chủ đề", "Điểm nổi bật", "Cấu trúc bài", "Yếu tố cốt lõi", "Tổng quan",
"Phân tích chuyên sâu", "Dữ liệu & Bằng chứng", "Giải pháp/Công nghệ", "Tác động chính",
"Chỉ số đo lường", "Đặc điểm", "Thành phần", "Lộ trình triển khai", "Kết luận"
(kể cả biến thể viết hoa, dịch tương đương, hoặc tiêu đề không nói rõ đối tượng).

══════════════════════════════════════════════════════════════════════
NỘI DUNG SÂU & THỰC TẾ (DEEP CONTENT RULES)
══════════════════════════════════════════════════════════════════════

A. **MỖI TIÊU ĐỀ LÀ MỘT THÔNG ĐIỆP CỤ THỂ**, không phải nhãn danh mục.
   - ĐÚNG:  "Doanh thu tăng 35% nhờ mở rộng thị trường".
   - SAI:   "Tình hình doanh thu".
   - `title` dài 2-10 từ, chứa thực thể/thuật ngữ của chủ đề và thường kèm một
     con số, mốc thời gian hoặc kết quả cụ thể.

B. **CẤU TRÚC 2 PHẦN CHO MỖI THẺ**: (1) `title` = thông điệp ngắn gọn, cô đọng;
   (2) `description` = đoạn diễn giải chi tiết 2-4 câu (20-60 từ) giải thích RÕ
   bản chất: dữ kiện định lượng, mốc thời gian, đơn vị, ví dụ hoặc quan hệ nhân quả.
   KHÔNG bịa số: nếu chưa chắc, nêu rõ phạm vi/điều kiện hoặc dùng kiến thức nền.

C. **MẠCH KỂ CHUYỆN (NARRATIVE ARC)** — các slide liền mạch theo đúng thứ tự:
   VẤN ĐỀ → NGUYÊN NHÂN GỐC RỄ → GIẢI PHÁP THỰC THI → KẾT QUẢ KỲ VỌNG → HÀNH ĐỘNG.
   Slide sau tiếp nối luận điểm slide trước, không lặp lại, không rời rạc.
   Ghi `section` là nhãn mục VIẾT HOA ngắn gọn thể hiện vị trí trong mạch trên
   (vd "VẤN ĐỀ", "NGUYÊN NHÂN", "GIẢI PHÁP", "KẾT QUẢ", "HÀNH ĐỘNG").

D. **SỐ THẺ LINH HOẠT THEO Ý**: 1 thẻ (tuyên bố lớn), 2 thẻ (so sánh hai bên),
   3 thẻ (3 đặc điểm), 4 thẻ (4 bước lộ trình). Chọn số thẻ TỰ NHIÊN nhất với ý
   đang trình bày; mỗi slide 1-4 thẻ.

══════════════════════════════════════════════════════════════════════
CÁC QUY TẮC CẤU TRÚC (STRUCTURAL RULES)
══════════════════════════════════════════════════════════════════════

1. **CHỈ NỘI DUNG, KHÔNG HÌNH HỌC**: KHÔNG trả `x/y/width/height`. Python tự tính.
   Bạn chỉ quyết định: `section`, `slide_title`, và với mỗi card: `morph_id`,
   `title`, `description`, `color_theme`, `order`.
2. **MORPH_ID**: ngắn, gạch dưới, không dấu/khoảng trắng (vd "hero_card",
   "kpi_revenue", "card_1"). GIỮ NGUYÊN morph_id giữa slide N và N+1 cho cùng
   một đối tượng nội dung (để PowerPoint Morph nội suy mượt mà); thẻ mới dùng id mới.
3. **MÀU color_theme**: là màu ACCENT tươi, bão hòa của thẻ (mã hex 6 ký tự có #).
   - Futuristic: #8B5CF6 (tím), #06B6D4 (cyan), #EC4899 (hồng), #10B981 (ngọc bảo).
   - Minimal:    #6366F1 (indigo), #38BDF8 (sky), #10B981 (ngọc bảo), #C9A227 (vàng đồng).
   - Corporate:  #C9A227 (vàng đồng), #10B981 (ngọc bảo), #3A86FF (xanh), #B08D2E (đồng).
   - Creative:   #EC4899 (hồng), #F59E0B (cam), #06B6D4 (cyan), #8B5CF6 (tím).
   Thẻ đầu tiên (điểm nhấn) dùng màu accent chủ đạo; các thẻ sau đổi màu xen kẽ.
4. **NGÔN NGỮ**: toàn bộ nội dung theo ngôn ngữ yêu cầu ("vi" → tiếng Việt tự nhiên,
   "en" → English). Không dịch từng chữ.
5. **SỐ LƯỢNG SLIDE**: trả ĐÚNG số slide người dùng yêu cầu (không hơn, không kém).
6. **ĐỊNH DẠNG**: trả DUY NHẤT một JSON object hợp lệ, không code fence, không giải thích.

══════════════════════════════════════════════════════════════════════
[VÍ DỤ MINH HOẠ CẤU TRÚC — NỘI DUNG LÀ PLACEHOLDER, KHÔNG ĐƯỢC SAO CHÉP]
══════════════════════════════════════════════════════════════════════

VÍ DỤ 1 — 2 slide, 3 thẻ/slide, morph_id giữ nguyên giữa 2 slide.
(Thay [CHỮ TRONG NGOẶC VUÔNG] bằng nội dung THẬT về USER TOPIC):

__EXAMPLE_1__

---
VÍ DỤ 2 — 1 slide dạng lộ trình 4 bước (4 thẻ), minh hoạ số thẻ linh hoạt:

__EXAMPLE_2__

══════════════════════════════════════════════════════════════════════
HÃY BẮT ĐẦU
══════════════════════════════════════════════════════════════════════
Đọc kỹ "=== USER TOPIC TO GENERATE ===", viết nội dung 100% bám sát chủ đề đó,
theo đúng mạch kể chuyện và cấu trúc JSON đã minh hoạ.
"""

# Gắn abstract examples vào SYSTEM_PROMPT (không dùng f-string cho examples
# để tránh xung đột nếu example có chứa { } — dù đã json.dumps an toàn, cách
# này rõ ràng và phòng thủ tuyệt đối).
SYSTEM_PROMPT = (
    SYSTEM_PROMPT_TEMPLATE
    .replace("__EXAMPLE_1__", _FEW_SHOT_EXAMPLE_1)
    .replace("__EXAMPLE_2__", _FEW_SHOT_EXAMPLE_2)
)


# ==============================================================================
# HELPERS
# ==============================================================================

def _extract_json_object(text: str) -> dict:
    """Trích JSON object đầu tiên từ phản hồi LLM (chịu lỗi markdown fence)."""
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

    # Quét ngoặc cân bằng
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
    """Phân loại lỗi tạm thời (đáng retry) vs lỗi logic."""
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
# OPENAI CLIENT
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
    """Xây dựng user prompt — CHUẨN HÓA THEO DẠNG DELIMITER RÕ RÀNG.

    ⚠️ CRITICAL: Biến req.prompt được đặt giữa 2 dòng delimiter độc đáo để
    LLM không bị nhầm lẫn đâu là yêu cầu thật, đâu là system instruction.
    Đây là fix then chốt cho lỗi "user prompt bị trôi / bị bỏ qua".
    """
    lang = "Tiếng Việt" if req.language.lower().startswith("vi") else "English"

    # Log audit: in ra để dev kiểm tra prompt có được truyền nguyên vẹn hay không
    logger.info(
        "Building user prompt | prompt=%r | num_slides=%d | style=%s | lang=%s",
        req.prompt[:120], req.num_slides, req.style, lang,
    )

    # Dùng delimiter độc đáo (bằng =, không phải ngoặc nhọn) để không xung đột JSON
    return (
        "================================================================\n"
        "=== USER TOPIC TO GENERATE ===\n"
        "================================================================\n"
        f"{req.prompt}\n"
        "================================================================\n"
        "=== END OF USER TOPIC ===\n"
        "================================================================\n\n"
        "CÁC THAM SỐ BỔ SUNG:\n"
        f"- Số lượng slide cần tạo (BẮT BUỘC đúng): {req.num_slides}\n"
        f"- Phong cách thiết kế: {req.style}\n"
        f"- Tỉ lệ khung hình: {req.aspect_ratio}\n"
        f"- Ngôn ngữ nội dung (toàn bộ title/description phải dùng ngôn ngữ này): {lang}\n"
        f"- Sinh speaker notes: {'Có' if req.include_speaker_notes else 'Không'}\n\n"
        "HÃY NHỚ LẠI QUY TẮT SỐ 1: Mọi nội dung (topic, slide_title, title, description) "
        "phải BÁM SÁT 100% chủ đề trong vùng === USER TOPIC TO GENERATE === ở trên. "
        "KHÔNG sao chép nội dung từ ví dụ, KHÔNG bịa nội dung chung chung. "
        "Trả về đúng JSON schema LLMOutput, không markdown fence, không giải thích."
    )


# ==============================================================================
# PARSER with PYDANTIC VALIDATION RETRY
# ==============================================================================

def _validate_llm_output(data: dict) -> LLMOutput:
    """Validate dữ liệu thô bằng Pydantic LLMOutput strict schema."""
    try:
        return LLMOutput.model_validate(data)
    except Exception as exc:
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


# Kiểm tra nhanh nội dung topic xem có bị nhiễm placeholder hay không
def _content_smell_check(result: LLMOutput, original_prompt: str) -> None:
    """Cảnh báo nếu nội dung có dấu hiệu bị nhiễm few-shot placeholder."""
    suspicious_tokens = [
        "[VÍ DỤ", "[NỘI DUNG VÍ DỤ", "[CHỦ ĐỀ", "[TIÊU ĐỀ", "[NỘI DUNG",
        "VÍ DỤ MINH HOẠ", "KHÔNG SAO CHÉP", "PLACEHOLDER", "[TÊN CHỦ ĐỀ",
    ]
    combined = (result.topic or "").lower()
    for s in result.slides:
        combined += " " + (s.slide_title or "").lower()
        for c in s.cards:
            combined += " " + (c.title or "").lower() + " " + (c.description or "").lower()
    hits = [t for t in suspicious_tokens if t.lower() in combined]
    if hits:
        logger.warning(
            "Nội dung LLM có dấu hiệu nhiễm placeholder tokens=%s — có thể model chưa tuân thủ topic adherence.",
            hits,
        )
    # Kiểm tra topic có khớp với user prompt không (so sánh đơn giản token overlap)
    prompt_tokens = set(w for w in original_prompt.lower().split() if len(w) >= 3)
    topic_tokens = set(w for w in (result.topic or "").lower().split() if len(w) >= 3)
    if prompt_tokens and topic_tokens and not (prompt_tokens & topic_tokens):
        logger.warning(
            "Topic kết quả '%s' không chia sẻ từ khoá nào với user prompt '%s' — có thể lệch chủ đề.",
            result.topic[:60], original_prompt[:60],
        )


async def _parse_with_retry(
    raw_text_getter: Callable[[list], Any],
    build_messages: Callable[[str], list],
    req: GenerateRequest,
    provider: str,
) -> LLMOutput:
    """Pipeline: gọi LLM -> trích JSON -> validate Pydantic -> content smell check."""
    last_validation_error: Optional[str] = None

    for attempt in range(1, MAX_VALIDATION_RETRIES + 2):
        user_prompt_text = _build_user_prompt(req)

        if last_validation_error is not None:
            user_prompt_text = (
                user_prompt_text
                + f"\n\n=== LỖI LẦN TRƯỚC (HÃY SỬA) ===\n{last_validation_error}\n\n"
                + "Hãy trả về JSON ĐÃ SỬA, bám sát USER TOPIC, đúng schema, không giải thích."
            )

        messages = build_messages(user_prompt_text)

        try:
            raw_text = await raw_text_getter(messages)
        except Exception:
            raise

        # Parse JSON
        try:
            data = _extract_json_object(raw_text or "")
        except ValueError as exc:
            last_validation_error = f"Lỗi parse JSON: {exc}"
            logger.warning("%s parse JSON lỗi (lần %d): %s", provider, attempt, last_validation_error)
            if attempt > MAX_VALIDATION_RETRIES:
                raise
            await asyncio.sleep(LLM_RETRY_BASE_DELAY_S * attempt)
            continue

        # Validate Pydantic
        try:
            result = _validate_llm_output(data)
            # Smell check (chỉ warning, không fail)
            _content_smell_check(result, req.prompt)
            logger.info(
                "%s đã sinh thành công %d slide (topic=%r, lần %d)",
                provider, len(result.slides), result.topic[:60], attempt,
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

    raise RuntimeError("Unreachable: retry loop exhausted")


# ==============================================================================
# PROVIDER IMPLEMENTATIONS
# ==============================================================================

async def _generate_with_openai(req: GenerateRequest) -> LLMOutput:
    """Gọi OpenAI với Structured Output + temperature=0.4."""
    logger.info("Gọi OpenAI %s (Structured Output, temp=%.1f)...", settings.OPENAI_MODEL, LLM_TEMPERATURE)

    client = _get_openai_client()
    json_schema = LLMOutput.model_json_schema()
    json_schema.pop("title", None)

    def _messages(user_content: str) -> list:
        return [
            {"role": "system", "content": SYSTEM_PROMPT},
            {"role": "user", "content": user_content},
        ]

    async def _raw_getter(messages: list) -> str:
        async def _call():
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
                    temperature=LLM_TEMPERATURE,
                )
            except Exception:  # noqa: BLE001
                return await client.chat.completions.create(
                    model=settings.OPENAI_MODEL,
                    messages=messages,
                    response_format={"type": "json_object"},
                    temperature=LLM_TEMPERATURE,
                )
        resp = await _call_with_retry("OpenAI", _call)
        return resp.choices[0].message.content if resp.choices else None

    return await _parse_with_retry(_raw_getter, _messages, req, "OpenAI")


async def _generate_with_gemini(req: GenerateRequest) -> LLMOutput:
    """Gọi Google Gemini với response_schema + temperature=0.4."""
    logger.info("Gọi Gemini %s (Structured Output, temp=%.1f)...", settings.GEMINI_MODEL, LLM_TEMPERATURE)

    import google.generativeai as genai
    genai.configure(api_key=settings.GEMINI_API_KEY)

    generation_config = {
        "response_mime_type": "application/json",
        "response_schema": LLMOutput,
        "temperature": LLM_TEMPERATURE,
    }

    model = genai.GenerativeModel(
        model_name=settings.GEMINI_MODEL,
        generation_config=generation_config,
        system_instruction=SYSTEM_PROMPT,
    )

    def _messages(user_content: str) -> list:
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


# =============================================================================
# FALLBACK GENERATOR (Heuristic — KHÔNG BAO GIỜ fail)
# =============================================================================
# ContentCard bắt buộc:
#   title       : 2-10 từ, 3-120 ký tự (MỘT THÔNG ĐIỆP CỤ THỂ, không nhãn chung chung)
#   description : 20-60 từ, 120-520 ký tự (2-4 câu diễn giải có dữ kiện thực tế)
# Bản cũ ghép nguyên prompt vào title (vd. "Bối cảnh tạo bài thuyết trình về
# solar system") → Pydantic ValueError → HTTP 502. Helper bên dưới luôn kẹp
# đúng số từ/ký tự trước khi tạo card.

_TITLE_WORD_MIN, _TITLE_WORD_MAX = 2, 10
_DESC_WORD_MIN, _DESC_WORD_MAX = 20, 60
_TITLE_CHAR_MAX = 120
_DESC_CHAR_MIN, _DESC_CHAR_MAX = 120, 520

# Cụm mở đầu kiểu "tạo bài thuyết trình về X" — bỏ đi để lấy đúng chủ đề X.
_PROMPT_NOISE = re.compile(
    r"^(?:(?:hãy|hay|vui lòng|please)\s+)?"
    r"(?:(?:tạo|tao|viết|viet|làm|lam|sinh|generate|create|make|write|build)\s+)?"
    r"(?:(?:một|mot|an?|the)\s+)?"
    r"(?:(?:bài|bai)\s+)?"
    r"(?:thuyết\s*trình|thuyet\s*trinh|presentation|pptx|slides?|deck)\s+"
    r"(?:(?:về|ve|about|on|for|of|với\s+chủ\s+đề|chu\s+de)\s+)?",
    re.IGNORECASE,
)

_SAFE_TITLE = "Chủ đề then chốt"
# 38 từ / ~220 ký tự — nằm giữa 20-60 từ và 120-520 ký tự.
_SAFE_DESCRIPTION = (
    "Phần này phân tích bối cảnh cơ chế vận hành và dữ kiện cụ thể của chủ đề "
    "để người xem nắm vấn đề cốt lõi. Nội dung nêu phạm vi áp dụng mối liên hệ "
    "nhân quả cùng ý nghĩa thực tiễn khi triển khai ngay bây giờ."
)
_DESC_FILLER = (
    "Phần phân tích nêu rõ cơ chế dữ kiện và mối liên hệ nhân quả để người xem "
    "nắm bản chất vấn đề phạm vi áp dụng cùng ý nghĩa thực tiễn khi triển khai "
    "trong bối cảnh hiện tại của chủ đề này."
)


def _split_words(text: str) -> list:
    return [w for w in (text or "").replace("\n", " ").split() if w]


def _extract_topic_core(prompt: str) -> str:
    """Lấy chủ đề thật từ prompt, bỏ cụm 'tạo bài thuyết trình về ...'."""
    first_line = re.sub(r"\s+", " ", (prompt or "").split("\n")[0]).strip()
    cleaned = _PROMPT_NOISE.sub("", first_line).strip(" .,:;!-–—")
    core = cleaned or first_line or "chủ đề chính"
    if len(core) > 120:
        core = core[:117].rstrip() + "..."
    return core


_TOPIC_STOPWORDS = {"gọi", "về", "cho", "của", "với", "of", "for", "about", "on", "the", "a", "an"}


def _topic_phrase(prompt: str, max_words: int = 4) -> str:
    """Cụm 1-4 từ dùng trong title card.

    Dừng sớm khi gặp token bắt đầu bằng chữ số (con số/%) để giữ cụm danh từ
    tự nhiên (vd "Báo cáo doanh thu" thay vì "Báo cáo doanh thu quý 3"), rồi
    bỏ các từ nối đuôi (gọi/về/cho...).
    """
    words = _split_words(_extract_topic_core(prompt))
    out: list = []
    for word in words[:max_words]:
        if word[0].isdigit():
            break
        out.append(word)
    while out and out[-1].lower() in _TOPIC_STOPWORDS:
        out.pop()
    return " ".join(out) if out else "chủ đề chính"


def _fit_title(text: str) -> str:
    """Kẹp title đúng 2-10 từ và ≤ 120 ký tự."""
    pads = ["then", "chốt", "cốt", "lõi"]
    words = _split_words(text)
    i = 0
    while len(words) < _TITLE_WORD_MIN:
        words.append(pads[i % len(pads)])
        i += 1
    words = words[:_TITLE_WORD_MAX]
    result = " ".join(words)
    while len(result) > _TITLE_CHAR_MAX and len(words) > _TITLE_WORD_MIN:
        words.pop()
        result = " ".join(words)
    if not (_TITLE_WORD_MIN <= len(_split_words(result)) <= _TITLE_WORD_MAX) or not (
        3 <= len(result) <= _TITLE_CHAR_MAX
    ):
        return _SAFE_TITLE
    return result


def _fit_description(text: str) -> str:
    """Kẹp description đúng 20-60 từ và 120-520 ký tự."""
    filler = _split_words(_DESC_FILLER)
    words = _split_words(text)
    i = 0
    while True:
        candidate = " ".join(words)
        need_words = len(words) < _DESC_WORD_MIN
        need_chars = len(candidate) < _DESC_CHAR_MIN
        if not need_words and not need_chars:
            break
        if len(words) >= _DESC_WORD_MAX:
            break
        words.append(filler[i % len(filler)])
        i += 1
    words = words[:_DESC_WORD_MAX]
    result = " ".join(words)
    while len(result) > _DESC_CHAR_MAX and len(words) > _DESC_WORD_MIN:
        words.pop()
        result = " ".join(words)
    word_n = len(_split_words(result))
    if not (
        _DESC_WORD_MIN <= word_n <= _DESC_WORD_MAX
        and _DESC_CHAR_MIN <= len(result) <= _DESC_CHAR_MAX
    ):
        return _SAFE_DESCRIPTION
    return result


# ==============================================================================
# TRÍCH XUẤT DỮ KIỆN TỪ PROMPT (cho Fallback Heuristic)
# ==============================================================================
# Fallback không có LLM nên không thể "biết" số liệu ngành. Nhưng nếu chính
# prompt của người dùng CHỨA dữ kiện (vd "$50B", "12.5 triệu USD", "35%",
# "2025", "99.999%"), ta tái sử dụng chúng để tiêu đề/đoạn mô tả trở nên CỤ THỂ
# thay vì chung chung — đúng tinh thần "mọi tiêu đề là một thông điệp".

_MONEY_RE = re.compile(
    r"\$\s?\d[\d.,]*\s?(?:B|M|K|billion|million|trillion|tỷ|triệu)?"
    r"|\d[\d.,]*\s?(?:triệu|tỷ|nghìn|ngàn)\s?(?:USD|VND|đô|đồng)?",
    re.IGNORECASE,
)
_PERCENT_RE = re.compile(r"\d+(?:[.,]\d+)?\s?%")
_YEAR_RE = re.compile(r"(?:19|20)\d{2}")


def _extract_prompt_facts(prompt: str) -> "dict[str, str]":
    """Trích dữ kiện định lượng đầu tiên tìm thấy trong prompt.

    Trả dict gồm 'money', 'percent', 'year' (chuỗi rỗng nếu không có).
    """
    text = prompt or ""
    facts = {"money": "", "percent": "", "year": ""}
    m = _MONEY_RE.search(text)
    if m:
        facts["money"] = m.group(0).strip()
    m = _PERCENT_RE.search(text)
    if m:
        facts["percent"] = m.group(0).strip()
    m = _YEAR_RE.search(text)
    if m:
        facts["year"] = m.group(0)
    return facts


def _make_card(
    *,
    morph_id: str,
    title: str,
    description: str,
    color_theme: str,
    order: int,
):
    """Tạo ContentCard luôn vượt qua Pydantic (title 2-10 từ, desc 20-60 từ)."""
    from app.schemas.slide_schema import ContentCard

    safe_id = re.sub(r"[^a-zA-Z0-9_]+", "_", (morph_id or "card")).strip("_") or "card"
    theme = color_theme if re.fullmatch(r"#?[0-9A-Fa-f]{6}", color_theme or "") else "#8B5CF6"
    try:
        return ContentCard(
            morph_id=safe_id[:80],
            title=_fit_title(title),
            description=_fit_description(description),
            color_theme=theme,
            order=max(0, min(int(order), 20)),
        )
    except Exception as exc:  # noqa: BLE001
        logger.warning("ContentCard fallback an toàn vì: %s", exc)
        return ContentCard(
            morph_id=safe_id[:80],
            title=_SAFE_TITLE,
            description=_SAFE_DESCRIPTION,
            color_theme=theme,
            order=max(0, min(int(order), 20)),
        )


def _clip_slide_title(text: str) -> str:
    title = re.sub(r"\s+", " ", (text or "").strip()) or "Bài Trình Chiếu ExoticMorph"
    return title[:200]


def generate_fallback_presentation(req: GenerateRequest) -> PresentationResponse:
    """Sinh LLMOutput dự phòng rồi chạy qua Layout Engine.

    Không được raise — đây là lưới an toàn cuối khi LLM/API key không sẵn sàng.
    """
    logger.info("Dùng Heuristic Fallback Generator cho prompt: %s", req.prompt[:80])
    try:
        return _build_fallback_presentation(req)
    except Exception as exc:  # noqa: BLE001
        logger.exception(
            "Fallback generator lỗi không mong muốn: %s — dùng template an toàn.", exc
        )
        return _emergency_presentation(req)


def _build_fallback_presentation(req: GenerateRequest) -> PresentationResponse:
    """Sinh bài trình chiếu dự phòng theo MẠCH KỂ CHUYỆN chuẩn diễn giả:

        Vấn đề → Nguyên nhân gốc rễ → Giải pháp thực thi → Kết quả kỳ vọng → Hành động.

    Không có LLM nên fallback không thể "biết" số liệu ngành, nhưng:
      - Tái sử dụng dữ kiện có SẴN trong prompt (số tiền, %, năm) để tiêu đề
        trở thành thông điệp cụ thể (không bịa thêm số).
      - Tiêu đề là thông điệp hành động, không dùng nhãn sáo rỗng.
      - Mỗi thẻ gồm tiêu đề cụ thể + đoạn diễn giải 2-3 câu có quan hệ nhân quả.
    """
    from app.schemas.slide_schema import RawSlideContent

    num_slides = max(1, min(req.num_slides, 20))
    vi = (req.language or "vi").lower().startswith("vi")
    accents = CARD_ACCENTS.get(req.style, CARD_ACCENTS["Futuristic"])

    topic_core = _extract_topic_core(req.prompt)
    topic_short = _topic_phrase(req.prompt, 3)
    topic_title = _clip_slide_title(topic_core)
    facts = _extract_prompt_facts(req.prompt)
    money, pct, year = facts["money"], facts["percent"], facts["year"]

    # ---- Cụm mô tả dùng chung (vi / en) ----
    if money:
        scale_vi = f"Quy mô {money} cho thấy dư địa còn rất lớn. "
        scale_en = f"A scale of {money} signals plenty of headroom. "
    else:
        scale_vi = "Các tổ chức chậm thích ứng đang tụt lại phía sau. "
        scale_en = "Organisations that adapt slowly are falling behind. "

    def _card(morph_id: str, title: str, desc: str, accent_idx: int, order: int):
        return _make_card(
            morph_id=morph_id,
            title=title,
            description=desc,
            color_theme=accents[accent_idx % len(accents)],
            order=order,
        )

    raw_slides: list = []

    if vi:
        # --------------------------------------------------------------
        # 1) VẤN ĐỀ — đặt vấn đề bằng một thông điệp cụ thể
        # --------------------------------------------------------------
        if money:
            s1_title = f"Cơ hội {money} từ {topic_short} đang mở ra"
        elif pct:
            s1_title = f"Tăng trưởng {pct} đang đặt {topic_short} lên tuyến đầu"
        else:
            s1_title = f"Vì sao {topic_short} trở thành ưu tiên chiến lược số một"
        raw_slides.append(RawSlideContent(
            slide_number=1,
            section="",
            slide_title=_clip_slide_title(s1_title),
            cards=[
                _card("card_1", f"Nhu cầu {topic_short} đang tăng tốc",
                      f"Nhu cầu xoay quanh {topic_core} đang gia tăng ở mọi khâu vận hành. "
                      f"{scale_vi}Chỉ những đơn vị chuyển động sớm mới giữ được lợi thế dẫn đầu.",
                      0, 0),
                _card("card_2", "Điểm nghẽn đang kìm hãm tiến độ",
                      f"Ba điểm nghẽn phổ biến là thiếu dữ liệu tin cậy, quy trình rời rạc và năng lực "
                      f"chuyên môn phân tán. Chúng đẩy chi phí lên cao trong khi tốc độ ra quyết định "
                      f"chậm lại. Gỡ sớm thì mọi kế hoạch mới kịp tiến độ.",
                      1, 1),
                _card("card_3", "Cái giá của việc chần chừ",
                      f"Mỗi quý trì hoãn đồng nghĩa chi phí cơ hội và doanh thu bỏ lỡ ngày càng lớn. "
                      f"Đối thủ đã bắt đầu thử nghiệm và thu hút khách hàng mục tiêu. Thời điểm hành "
                      f"động tốt nhất chính là hiện tại.",
                      2, 2),
            ],
        ))

        # --------------------------------------------------------------
        # 2) NGUYÊN NHÂN GỐC RỄ
        # --------------------------------------------------------------
        if num_slides >= 2:
            raw_slides.append(RawSlideContent(
                slide_number=2,
                section="",
                slide_title=_clip_slide_title(f"Ba nguyên nhân gốc rễ khiến {topic_short} chững lại"),
                cards=[
                    _card("card_1", "Nguyên nhân trực tiếp phía sau",
                          f"Vấn đề lớn nhất của {topic_core} thường bắt nguồn từ dữ liệu phân mảnh, "
                          f"khiến các quyết định dựa trên cảm tính thay vì bằng chứng. Khi không đo "
                          f"được hiện trạng, tổ chức khó biết nên ưu tiên gỡ nút thắt nào trước.",
                          0, 0),
                    _card("card_2", "Rào cản hệ thống khó gỡ",
                          f"Năng lực và nguồn lực cho {topic_short} bị chia nhỏ giữa nhiều bộ phận, "
                          f"thiếu một đầu mối chịu trách nhiệm cuối. Quy trình phê duyệt nhiều tầng "
                          f"kéo dài chu kỳ triển khai và triệt tiêu động lực của nhóm thực thi.",
                          1, 1),
                    _card("card_3", "Ngộ nhận phổ biến cần tránh",
                          f"Nhiều tổ chức nhầm tưởng chỉ cần thêm ngân sách là đủ, trong khi gốc rễ "
                          f"lại nằm ở cách vận hành. Đầu tư công nghệ mà không thay đổi quy trình "
                          f"chỉ khuếch đại sự lãng phí hiện có.",
                          2, 2),
                ],
            ))

        # --------------------------------------------------------------
        # 3) GIẢI PHÁP THỰC THI
        # --------------------------------------------------------------
        if num_slides >= 3:
            raw_slides.append(RawSlideContent(
                slide_number=3,
                section="",
                slide_title=_clip_slide_title(f"Giải pháp khả thi cho {topic_short} trong 90 ngày"),
                cards=[
                    _card("card_1", "Trụ cột một: nền tảng dữ liệu",
                          f"Hợp nhất dữ liệu về {topic_core} vào một nguồn duy nhất, chuẩn hoá định "
                          f"nghĩa và chỉ số. Bảng điều hành theo thời gian thực giúp mọi bên nhìn "
                          f"chung một bức tranh và phát hiện bất thường sớm.",
                          0, 0),
                    _card("card_2", "Trụ cột hai: quy trình chuẩn hoá",
                          f"Thiết kế lại quy trình theo chuẩn tinh gọn, giao rõ đầu mối chịu trách "
                          f"nhiệm ở từng khâu. Cắt bớt tầng phê duyệt trung gian để rút ngắn thời "
                          f"gian từ ý tưởng đến triển khai.",
                          1, 1),
                    _card("card_3", "Trụ cột ba: đo lường liên tục",
                          f"Đặt bộ chỉ số dẫn dắt cho {topic_short} và họp định kỳ để đối chiếu tiến "
                          f"độ. Mọi điều chỉnh dựa trên dữ liệu thực tế, không theo cảm tính, giúp "
                          f"tổ chức học nhanh và xoay trục kịp thời.",
                          2, 2),
                ],
            ))

        # --------------------------------------------------------------
        # 4) KẾT QUẢ KỲ VỌNG
        # --------------------------------------------------------------
        if num_slides >= 4:
            target = f"trong {year}" if year else "trong 4 quý tới"
            raw_slides.append(RawSlideContent(
                slide_number=4,
                section="",
                slide_title=_clip_slide_title(f"Những kết quả đo được {target} sau khi triển khai {topic_short}"),
                cards=[
                    _card("card_1", f"Mục tiêu định lượng {target}",
                          f"Đặt mục tiêu cụ thể cho {topic_core} {('(bám sát mốc ' + pct + ')') if pct else ''} "
                          f"và theo dõi theo tuần. Mục tiêu phải đo được, gắn trách nhiệm cá nhân và có "
                          f"ngưỡng cảnh báo khi chệch hướng để kịp thời can thiệp.",
                          0, 0),
                    _card("card_2", "Lợi ích lan tỏa sang các mảng",
                          f"Thành công ở {topic_short} kéo theo hiệu quả dây chuyền: giảm chi phí vận "
                          f"hành, tăng tốc độ quyết định và củng cố vị thế cạnh tranh. Bài học thu được "
                          f"có thể nhân bản sang các bộ phận khác.",
                          1, 1),
                    _card("card_3", "Rủi ro và cách kiểm soát",
                          f"Rủi ro lớn nhất là triển khai nửa vời rồi dừng giữa chừng. Cần cơ chế giám "
                          f"sát độc lập, quỹ dự phòng cho tình huống phát sinh và cam kết của lãnh đạo "
                          f"để giữ nhịp triển khai đến cùng.",
                          2, 2),
                ],
            ))

        # --------------------------------------------------------------
        # 5) HÀNH ĐỘNG TIẾP THEO — 4 bước lộ trình (roadmap)
        # --------------------------------------------------------------
        if num_slides >= 5:
            raw_slides.append(RawSlideContent(
                slide_number=5,
                section="",
                slide_title=_clip_slide_title(f"Bốn bước hành động cho {topic_short} trong 30 ngày tới"),
                cards=[
                    _card("card_1", "Chốt mục tiêu và người chịu trách nhiệm",
                          f"Ghi rõ kết quả kỳ vọng của {topic_core} trong 30 ngày và phân công một đầu "
                          f"mối duy nhất. Mục tiêu phải cụ thể, có mốc thời gian và được cả nhóm cam kết.",
                          0, 0),
                    _card("card_2", "Phân bổ ngân sách và nguồn lực",
                          f"Dành nguồn lực nhân sự và ngân sách tối thiểu cho giai đoạn đầu. Ưu tiên "
                          f"tuyển đúng người có năng lực chuyên môn để tránh lãng phí chi phí học lại.",
                          1, 1),
                    _card("card_3", "Chạy thí điểm trong phạm vi hẹp",
                          f"Triển khai thí điểm cho {topic_short} trên một phân khúc hoặc quy trình nhỏ "
                          f"trong 2-4 tuần. Thu thập dữ liệu và phản hồi để kiểm chứng giả định trước "
                          f"khi mở rộng quy mô.",
                          2, 2),
                    _card("card_4", "Đo lường, học và nhân rộng",
                          f"Đánh giá kết quả thí điểm bằng chỉ số đã đặt ra, giữ lại điều hiệu quả và "
                          f"cắt bỏ phần thừa. Nhân rộng mô hình thành công ra toàn tổ chức theo lộ trình "
                          f"đã duyệt.",
                          3, 3),
                ],
            ))

        if num_slides > 5:
            for s_idx in range(6, num_slides + 1):
                extra_n = s_idx - 5
                raw_slides.append(RawSlideContent(
                    slide_number=s_idx,
                    section="",
                    slide_title=_clip_slide_title(f"Góc nhìn mở rộng {extra_n} cho {topic_short}"),
                    cards=[
                        _card(f"extra_{s_idx}_1", f"Kịch bản {extra_n}: yếu tố ảnh hưởng",
                              f"Phân tích kịch bản và yếu tố ảnh hưởng đặc thù của {topic_core} chưa "
                              f"được đề cập ở các phần trước. Xét cả biến số nội tại lẫn ngoại cảnh để "
                              f"có góc nhìn toàn diện hơn.",
                              0, 0),
                        _card(f"extra_{s_idx}_2", f"Đề xuất {extra_n}: hướng xử lý",
                              f"Đề xuất cách xử lý cụ thể cho kịch bản trên, kèm ưu nhược điểm và điều "
                              f"kiện áp dụng. Chuyển từ phân tích sang hành động bằng bước thực hiện rõ "
                              f"ràng cho {topic_short}.",
                              1, 1),
                    ],
                ))
    else:
        # --------------------------------------------------------------
        # ENGLISH narrative arc
        # --------------------------------------------------------------
        if money:
            s1_title = f"A {money} opportunity in {topic_short} is opening up"
        elif pct:
            s1_title = f"{pct} growth puts {topic_short} on the front line"
        else:
            s1_title = f"Why {topic_short} is now the number-one strategic priority"
        raw_slides.append(RawSlideContent(
            slide_number=1,
            section="",
            slide_title=_clip_slide_title(s1_title),
            cards=[
                _card("card_1", f"Demand for {topic_short} is accelerating",
                      f"Demand around {topic_core} is rising across every part of operations. "
                      f"{scale_en}Only early movers will hold the lead.",
                      0, 0),
                _card("card_2", "The bottleneck holding back progress",
                      f"Three recurring bottlenecks are unreliable data, fragmented processes and "
                      f"scattered expertise. They raise cost while slowing decision speed. Removing "
                      f"them early keeps every plan on schedule.",
                      1, 1),
                _card("card_3", "The cost of waiting",
                      f"Every quarter of delay means larger opportunity cost and lost revenue. "
                      f"Competitors are already testing and winning target customers. The best time "
                      f"to act is now.",
                      2, 2),
            ],
        ))

        if num_slides >= 2:
            raw_slides.append(RawSlideContent(
                slide_number=2,
                section="",
                slide_title=_clip_slide_title(f"Three root causes behind the slowdown in {topic_short}"),
                cards=[
                    _card("card_1", "The direct root cause",
                          f"The biggest issue for {topic_core} is fragmented data, which forces "
                          f"decisions to be made on intuition instead of evidence. Without a clear "
                          f"baseline it is hard to know which constraint to fix first.",
                          0, 0),
                    _card("card_2", "Systemic barriers",
                          f"Capability and resources for {topic_short} are split across many teams "
                          f"with no single owner. Multi-layer approvals stretch delivery cycles and "
                          f"drain the team's momentum.",
                          1, 1),
                    _card("card_3", "The myth to avoid",
                          f"Many organisations assume more budget is enough, when the real issue is "
                          f"how the work runs. Buying technology without changing process only "
                          f"amplifies existing waste.",
                          2, 2),
                ],
            ))

        if num_slides >= 3:
            raw_slides.append(RawSlideContent(
                slide_number=3,
                section="",
                slide_title=_clip_slide_title(f"A 90-day solution for {topic_short}"),
                cards=[
                    _card("card_1", "Pillar one: a data foundation",
                          f"Consolidate data on {topic_core} into a single source with standardised "
                          f"definitions and metrics. A real-time dashboard lets everyone read the same "
                          f"picture and spot anomalies early.",
                          0, 0),
                    _card("card_2", "Pillar two: standardised process",
                          f"Redesign the workflow to lean standards and assign a clear owner to each "
                          f"step. Remove middle layers of approval to shorten the path from idea to "
                          f"execution.",
                          1, 1),
                    _card("card_3", "Pillar three: continuous measurement",
                          f"Define leading indicators for {topic_short} and review progress on a fixed "
                          f"cadence. Every adjustment is based on real data, helping the organisation "
                          f"learn fast and pivot in time.",
                          2, 2),
                ],
            ))

        if num_slides >= 4:
            target = f"in {year}" if year else "within four quarters"
            raw_slides.append(RawSlideContent(
                slide_number=4,
                section="",
                slide_title=_clip_slide_title(f"Measurable results {target} after rolling out {topic_short}"),
                cards=[
                    _card("card_1", f"Quantified targets {target}",
                          f"Set concrete goals for {topic_core} {('(tracking ' + pct + ')') if pct else ''} "
                          f"and review them weekly. Targets must be measurable, tied to a named owner and "
                          f"carry an alert threshold when they drift.",
                          0, 0),
                    _card("card_2", "Ripple benefits",
                          f"Success in {topic_short} creates knock-on gains: lower operating cost, faster "
                          f"decisions and a stronger competitive position. The lessons can be replicated "
                          f"across other teams.",
                          1, 1),
                    _card("card_3", "Risks and how to control them",
                          f"The biggest risk is a half-finished rollout. Keep independent oversight, a "
                          f"contingency fund and visible leadership commitment to sustain momentum to "
                          f"the end.",
                          2, 2),
                ],
            ))

        if num_slides >= 5:
            raw_slides.append(RawSlideContent(
                slide_number=5,
                section="",
                slide_title=_clip_slide_title(f"Four actions for {topic_short} in the next 30 days"),
                cards=[
                    _card("card_1", "Lock targets and a single owner",
                          f"Write down the expected outcome for {topic_core} in 30 days and name one "
                          f"accountable owner. The goal must be specific, time-boxed and committed by "
                          f"the whole team.",
                          0, 0),
                    _card("card_2", "Allocate budget and people",
                          f"Ring-fence the minimum people and budget for the first phase. Prioritise "
                          f"hiring the right expertise to avoid paying twice for relearning.",
                          1, 1),
                    _card("card_3", "Run a small pilot",
                          f"Pilot {topic_short} in one narrow segment or workflow for two to four weeks. "
                          f"Gather data and feedback to validate assumptions before scaling.",
                          2, 2),
                    _card("card_4", "Measure, learn and scale",
                          f"Review the pilot against the agreed metrics, keep what works and cut what "
                          f"does not. Replicate the winning model across the organisation on an approved "
                          f"plan.",
                          3, 3),
                ],
            ))

        if num_slides > 5:
            for s_idx in range(6, num_slides + 1):
                extra_n = s_idx - 5
                raw_slides.append(RawSlideContent(
                    slide_number=s_idx,
                    section="",
                    slide_title=_clip_slide_title(f"Extended angle {extra_n} for {topic_short}"),
                    cards=[
                        _card(f"extra_{s_idx}_1", f"Scenario {extra_n}: key factors",
                              f"Examine scenarios and factors specific to {topic_core} not covered "
                              f"earlier, weighing both internal variables and external forces for a "
                              f"fuller view.",
                              0, 0),
                        _card(f"extra_{s_idx}_2", f"Proposal {extra_n}: how to respond",
                              f"Propose a concrete response to that scenario with trade-offs and "
                              f"conditions. Turn analysis into action with clear next steps for "
                              f"{topic_short}.",
                              1, 1),
                    ],
                ))

    llm_output = LLMOutput(topic=topic_title, slides=raw_slides[:num_slides])
    return compute_layout(llm_output, req)


def _emergency_presentation(req: GenerateRequest) -> PresentationResponse:
    """Template cứng, luôn hợp lệ — chỉ dùng khi fallback heuristic cũng vỡ."""
    from app.schemas.slide_schema import ContentCard, RawSlideContent

    card = ContentCard(
        morph_id="hero_card",
        title=_SAFE_TITLE,
        description=_SAFE_DESCRIPTION,
        color_theme="#8B5CF6",
        order=0,
    )
    llm_output = LLMOutput(
        topic=_clip_slide_title(_extract_topic_core(req.prompt)),
        slides=[
            RawSlideContent(
                slide_number=1,
                section="",
                slide_title=_clip_slide_title(f"Bài toán {_topic_phrase(req.prompt, 3)} và bước đi đầu tiên"),
                cards=[card],
            )
        ],
    )
    return compute_layout(llm_output, req)


# =============================================================================
# ENTRY POINT CHÍNH
# =============================================================================

async def generate_presentation_with_llm(req: GenerateRequest) -> PresentationResponse:
    """Gọi LLM -> LLMOutput -> Layout Engine -> PresentationResponse.

    ⚠️ AUDIT LOG: Ghi log prompt đầy đủ (dưới dạng tiền tố) để kiểm tra biến
    req.prompt có bị mất/trôi trên luồng từ Frontend vào LLM hay không.
    """
    provider = settings.LLM_PROVIDER.lower()

    # Audit log: in ngay đầu pipeline để verify flow
    logger.info(
        "[AUDIT] generate_presentation_with_llm called with prompt=%r num_slides=%d style=%s lang=%s",
        req.prompt[:200], req.num_slides, req.style, req.language,
    )

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
            raw_output: LLMOutput = await _PROVIDER_FUNCS[name](req)
            presentation = compute_layout(raw_output, req)
            logger.info(
                "[AUDIT] LLM returned topic=%r (user prompt=%r) — match=%s",
                raw_output.topic[:80],
                req.prompt[:80],
                bool(set(req.prompt.lower().split()) & set(raw_output.topic.lower().split())),
            )
            return presentation

        except Exception as exc:  # noqa: BLE001
            is_last = idx == len(provider_chain) - 1
            logger.warning(
                "Provider '%s' thất bại: %s.%s",
                name, exc,
                "" if is_last else " Chuyển sang provider dự phòng...",
            )

    if provider_chain:
        logger.warning("Tất cả LLM provider đều thất bại — dùng Heuristic Fallback.")
    return generate_fallback_presentation(req)
