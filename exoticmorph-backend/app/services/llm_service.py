"""
LLM Service Module for ExoticMorph (v7 — Narrative Arc + Creative Layouts)
~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~
Thay đổi cốt lõi:

1. **NARRATIVE ARC 3 PHẦN (MỞ BÀI → THÂN BÀI → KẾT BÀI)**:
   LLM bị ÉP sinh nội dung theo mạch kể chuyện chuẩn thuyết trình:
   - Slide 1 (MỞ BÀI)        : `COVER_HERO` — câu hỏi dẫn dắt / đặt vấn đề ấn tượng.
   - Slide 2..N-1 (THÂN BÀI) : `BIG_STAT_CALLOUT` / `ASYMMETRIC_GRID` /
                               `TIMELINE_STEPS` / `CARDS_ROW` dùng XEN KẼ.
   - Slide N (KẾT BÀI)       : `CONCLUSION_SUMMARY` — 3 điểm cốt lõi + call to action.
   - **ĐIỀU KIỆN BẮT BUỘC**: KHÔNG ĐƯỢC để 2 slide liên tiếp có cùng `layout_type`;
     `layout_engine.compute_layout()` cũng tự thực thi lại quy tắc này nên kể cả
     khi LLM làm sai, file PPTX vẫn đúng mạch kể.

2. **BỐ CỤC PHÁ CÁCH CHUẨN DESIGNER** (mỗi layout quy định rõ số thẻ & vai trò
   từng thẻ để JSON luôn khớp Pydantic Schema):
   * `COVER_HERO`        : tiêu đề siêu lớn 44-52pt + subtitle nổi bật + hàng badge.
   * `BIG_STAT_CALLOUT`  : số khổng lồ 72pt+ bên trái, văn bản giải thích bên phải.
   * `ASYMMETRIC_GRID`   : lưới bất đối xứng 60% - 40% (Hero + 2 thẻ phụ dọc).
   * `TIMELINE_STEPS`    : quy trình 3-4 bước ngang.
   * `CARDS_ROW`         : 2-3 thẻ ngang hàng.
   * `CONCLUSION_SUMMARY`: 3 dòng card mỏng bo góc + thanh Call To Action.
   Các layout đời cũ `SPLIT_HERO`/`STAT_GRID`/`GRID_2X2` vẫn parse được (tương
   thích ngược) và được tự nâng cấp lên bố cục mới tương đương.

3. **DYNAMIC PERSONA SYSTEM PROMPT**:
   - LLM tự nhận diện lĩnh vực của chủ đề (Thiên văn, Lịch sử, Y học, Nông nghiệp,
     Công nghệ...) rồi NHẬP VAI chuyên gia hàng đầu lĩnh vực đó, dùng đúng từ vựng
     chuyên ngành. Mỗi slide bắt buộc chứa ít nhất 3 thuật ngữ/số liệu/sự thật
     chuyên ngành (Domain Vocabulary Rule) và cấm tuyệt đối văn mẫu B2B sáo rỗng.

4. **JSON PARSE RETRY với THANG NHIỆT ĐỘ**:
   - Mỗi lần retry sau khi parse/validation thất bại dùng một temperature khác
     nhau (0.4 → 0.2 → 0.7) kèm feedback lỗi cụ thể.
"""

import asyncio
import json
import logging
import re
from typing import Any, Callable, Optional, Tuple

from app.config import settings
from app.schemas.slide_schema import (
    GenerateRequest,
    LLMOutput,
    PresentationResponse,
    LayoutType,
    SlideData,
    RawSlideContent,
)
from app.services.layout_engine import compute_layout

logger = logging.getLogger("exoticmorph.llm")

# =============================================================================
# CẤU HÌNH
# =============================================================================
LLM_MAX_ATTEMPTS = 3              # Retry lỗi tạm thời (mạng/rate-limit/5xx)
LLM_RETRY_BASE_DELAY_S = 1.5
LLM_REQUEST_TIMEOUT_S = 90.0
MAX_VALIDATION_RETRIES = 2        # Số lần thử lại khi Parse JSON / Pydantic fail (tổng 3 lần gọi)

# THANG NHIỆT ĐỘ CHO CÁC LẦN RETRY KHI JSON/SCHEMA SAI:
#   - Lần 1 = 0.4 : cân bằng giữa sáng tạo và bám chủ đề (chế độ mặc định).
#   - Lần 2 = 0.2 : hạ nhiệt → model "nghe lời" hơn, tuân thủ schema chặt hơn.
#   - Lần 3 = 0.7 : tăng nhiệt → phá vỡ vòng lặp output lỗi lặp lại y hệt.
TEMPERATURE_LADDER: Tuple[float, ...] = (0.4, 0.2, 0.7)
LLM_TEMPERATURE = TEMPERATURE_LADDER[0]


# =============================================================================
# NGOẠI LỆ — FAIL LOUD, KHÔNG SILENT FALLBACK
# =============================================================================

class LLMGenerationError(Exception):
    """Mọi LLM provider đều thất bại khi sinh nội dung.

    Message của exception này được thiết kế AN TOÀN để hiển thị thẳng cho
    người dùng cuối (không chứa API key, không chứa traceback nội bộ).
    """


class LLMConfigurationError(LLMGenerationError):
    """Backend chưa được cấu hình LLM hợp lệ (thiếu API key / provider mock)."""


# =============================================================================
# MASK BÍ MẬT TRƯỚC KHI LOG / TRẢ VỀ CLIENT
# =============================================================================
_KEY_PARAM_RE = re.compile(r"([?&]key=)[A-Za-z0-9_\-]{4,}", re.IGNORECASE)


def _mask_sensitive(text: str) -> str:
    """Che API key / token khỏi chuỗi lỗi trước khi log hoặc trả về client."""
    if not text:
        return text
    masked = _KEY_PARAM_RE.sub(r"\1****", str(text))
    for key in (settings.GEMINI_API_KEY, settings.OPENAI_API_KEY):
        if key and len(key) >= 6 and key in masked:
            masked = masked.replace(key, f"{key[:4]}...****")
    return masked


def _summarize_exc(exc: Exception, limit: int = 220) -> str:
    """Tóm tắt lỗi gốc (đã mask) để nhúng vào message trả về client."""
    raw = f"{type(exc).__name__}: {exc}"
    masked = _mask_sensitive(raw).replace("\n", " ").strip()
    return masked[:limit]


# Lý do thất bại được chuẩn hóa để hiển thị cho người dùng
REASON_API_KEY_INVALID = "API key không hợp lệ hoặc đã bị thu hồi"
REASON_PERMISSION_DENIED = "API key không có quyền truy cập model này"
REASON_QUOTA_EXCEEDED = "Đã vượt hạn mức / rate limit (quota) của provider"
REASON_NETWORK_TIMEOUT = "Không kết nối được máy chủ LLM (mất mạng / timeout)"
REASON_OUTPUT_INVALID = "LLM trả về dữ liệu sai định dạng sau khi đã thử lại nhiều lần"
REASON_UNKNOWN = "Lỗi không xác định từ provider"

_HINTS_BY_REASON = {
    REASON_API_KEY_INVALID: (
        "Hãy kiểm tra lại giá trị {key_env} trong biến môi trường của Backend "
        "(lấy key mới tại Google AI Studio / OpenAI Platform)."
    ),
    REASON_PERMISSION_DENIED: (
        "API key có thể chưa bật API tương ứng hoặc khu vực không được hỗ trợ — "
        "kiểm tra quyền truy cập của key và model {model}."
    ),
    REASON_QUOTA_EXCEEDED: (
        "Tài khoản đã hết hạn mức miễn phí hoặc bị giới hạn tần suất — "
        "chờ ít phút rồi thử lại, hoặc nâng gói/bật billing cho API key."
    ),
    REASON_NETWORK_TIMEOUT: (
        "Kiểm tra kết nối mạng của server Backend (hoặc máy chủ LLM đang quá tải) "
        "rồi thử lại sau ít giây."
    ),
    REASON_OUTPUT_INVALID: (
        "Model đang sinh JSON sai schema — hãy thử lại, hoặc đổi sang model mới hơn "
        "trong cấu hình Backend."
    ),
    REASON_UNKNOWN: "Hãy xem log Backend để biết chi tiết kỹ thuật.",
}


def _diagnose_exception(exc: Exception, provider_name: str) -> Tuple[str, str]:
    """Phân loại exception LLM → (lý do chuẩn hóa, gợi ý khắc phục)."""
    cls_name = type(exc).__name__
    combined = f"{cls_name} {exc}".lower()

    status = getattr(exc, "status_code", None)
    if not isinstance(status, int):
        status = getattr(exc, "code", None)
    try:
        status = int(status)
    except (TypeError, ValueError):
        status = None

    if (
        status == 401
        or "api_key_invalid" in combined
        or "invalid api key" in combined
        or "api key not valid" in combined
        or "incorrect api key" in combined
        or "authenticationerror" in combined
        or "unauthenticated" in combined
    ):
        reason = REASON_API_KEY_INVALID
    elif (
        status == 403
        or "permissiondenied" in combined
        or "permission denied" in combined
        or "forbidden" in combined
    ):
        reason = REASON_PERMISSION_DENIED
    elif (
        status == 429
        or "resourceexhausted" in combined
        or "rate limit" in combined
        or "quota" in combined
        or "too many requests" in combined
    ):
        reason = REASON_QUOTA_EXCEEDED
    elif _is_transient_error(exc) or "timeout" in combined or "connection" in combined:
        reason = REASON_NETWORK_TIMEOUT
    elif isinstance(exc, (ValueError, json.JSONDecodeError)):
        reason = REASON_OUTPUT_INVALID
    else:
        reason = REASON_UNKNOWN

    model = getattr(settings, f"{provider_name.upper()}_MODEL", "")
    hint = _HINTS_BY_REASON[reason].format(
        key_env=f"{provider_name.upper()}_API_KEY",
        model=model,
    )
    return reason, hint


def _build_failure_message(failures: list) -> str:
    """Sinh message HTTP 502 rõ ràng, an toàn, hướng dẫn người dùng hành động."""
    lines = [
        "Không thể sinh nội dung bằng AI — tất cả LLM provider đều thất bại.",
    ]
    for provider, reason, hint, raw in failures:
        lines.append(f"• {provider.capitalize()}: {reason}. {hint}")
        if raw:
            lines.append(f"  ↳ Lỗi gốc: {raw}")
    lines.append(
        "Lưu ý: chế độ văn mẫu tự động (fallback) đã bị vô hiệu hóa để đảm bảo 100% "
        "nội dung do AI sáng tạo, nên hệ thống không trả về bản slide kém chất lượng."
    )
    lines.append("Vui lòng kiểm tra API key / hạn mức (quota) rồi nhấn Tạo lại.")
    return "\n".join(lines)


# =============================================================================
# FEW-SHOT EXAMPLES — DẠNG ABSTRACT (CÓ LAYOUT_TYPE ĐA DẠNG)
# =============================================================================

_FEW_SHOT_EXAMPLE_1 = json.dumps({
    "topic": "[CHỦ ĐỀ CỦA NGƯỜI DÙNG — viết lại ngắn gọn]",
    "style": "Futuristic",
    "slides": [
        {
            "slide_number": 1,
            "section": "[CÂU HỎI MỞ ĐẦU]",
            "slide_title": "[CÂU HỎI DẪN DẮT 6-12 từ chứa số liệu/thuật ngữ chuyên ngành?]",
            "layout_type": "COVER_HERO",
            "cards": [
                {
                    "morph_id": "cover_hook",
                    "title": "[CÂU HOOK 8-15 từ nêu vấn đề sẽ được giải đáp trong bài]",
                    "description": "[1-2 câu bối cảnh mở màn: thuật ngữ chuyên ngành + số liệu/mốc thời gian thật để tạo sức nặng cho câu hỏi.]",
                    "color_theme": "#8B5CF6",
                    "order": 0,
                },
                {
                    "morph_id": "cover_badge_1",
                    "title": "[NHÃN 1-3 TỪ]",
                    "description": "[1 câu chú thích ngắn cho nhãn badge này.]",
                    "color_theme": "#10B981",
                    "order": 1,
                },
                {
                    "morph_id": "cover_badge_2",
                    "title": "[NHÃN 1-3 TỪ]",
                    "description": "[1 câu chú thích ngắn cho nhãn badge này.]",
                    "color_theme": "#06B6D4",
                    "order": 2,
                },
            ],
        },
        {
            "slide_number": 2,
            "section": "[SỐ LIỆU ĐỊNH LƯỢNG]",
            "slide_title": "[LUẬN ĐIỂM ĐỊNH LƯỢNG chính của phần thân bài]",
            "layout_type": "BIG_STAT_CALLOUT",
            "cards": [
                {
                    "morph_id": "stat_hero",
                    "title": "[465 °C]",
                    "description": "[2-3 câu giải thích con số khổng lồ bên trái: nó đo cái gì, so với chuẩn nào, vì sao đáng kinh ngạc.]",
                    "color_theme": "#8B5CF6",
                    "order": 0,
                },
                {
                    "morph_id": "stat_context",
                    "title": "[BỐI CẢNH GIẢI THÍCH CHO CON SỐ]",
                    "description": "[2-3 câu: cơ chế tạo ra con số, thuật ngữ chuyên ngành, hệ quả thực tế.]",
                    "color_theme": "#10B981",
                    "order": 1,
                },
            ],
        },
        {
            "slide_number": 3,
            "section": "[KẾT LUẬN]",
            "slide_title": "[THÔNG ĐIỆP CHỐT — khẳng định, không phải câu hỏi]",
            "layout_type": "CONCLUSION_SUMMARY",
            "cards": [
                {
                    "morph_id": "takeaway_1",
                    "title": "[BÀI HỌC RÚT RA 4-10 từ]",
                    "description": "[1-2 câu tóm gọn bằng chứng quan trọng nhất cho điểm cốt lõi này.]",
                    "color_theme": "#8B5CF6",
                    "order": 0,
                },
                {
                    "morph_id": "takeaway_2",
                    "title": "[BÀI HỌC RÚT RA 4-10 từ]",
                    "description": "[1-2 câu tóm gọn bằng chứng cho điểm cốt lõi thứ hai.]",
                    "color_theme": "#10B981",
                    "order": 1,
                },
                {
                    "morph_id": "takeaway_3",
                    "title": "[BÀI HỌC RÚT RA 4-10 từ]",
                    "description": "[1-2 câu tóm gọn bằng chứng cho điểm cốt lõi thứ ba.]",
                    "color_theme": "#06B6D4",
                    "order": 2,
                },
                {
                    "morph_id": "call_to_action",
                    "title": "[ĐỘNG TỪ + hành động cụ thể người nghe làm ngay]",
                    "description": "[1-2 câu nêu bước thực hiện đầu tiên, mốc thời gian hoặc công cụ cụ thể.]",
                    "color_theme": "#EC4899",
                    "order": 3,
                },
            ],
        },
    ],
}, ensure_ascii=False, indent=2)

_FEW_SHOT_EXAMPLE_2 = json.dumps({
    "topic": "[CHỦ ĐỀ KHÁC CỦA NGƯỜI DÙNG]",
    "style": "Academic",
    "slides": [
        {
            "slide_number": 3,
            "section": "[LỘ TRÌNH THỰC THI]",
            "slide_title": "[CHU TRÌNH 4 BƯỚC TIẾN TRÌNH THEO THỨ TỰ THỜI GIAN]",
            "layout_type": "TIMELINE_STEPS",
            "cards": [
                {
                    "morph_id": "step_1",
                    "title": "[GIAI ĐOẠN 1 — khẳng định cụ thể + mốc thời gian thật]",
                    "description": "[2-4 câu: bản chất giai đoạn, thuật ngữ chuyên ngành, sự kiện/số liệu minh chứng.]",
                    "color_theme": "#8B5CF6",
                    "order": 0,
                },
                {
                    "morph_id": "step_2",
                    "title": "[GIAI ĐOẠN 2 — khẳng định cụ thể + mốc thời gian thật]",
                    "description": "[2-4 câu: bản chất giai đoạn, thuật ngữ chuyên ngành, sự kiện/số liệu minh chứng.]",
                    "color_theme": "#10B981",
                    "order": 1,
                },
                {
                    "morph_id": "step_3",
                    "title": "[GIAI ĐOẠN 3 — khẳng định cụ thể + mốc thời gian thật]",
                    "description": "[2-4 câu: bản chất giai đoạn, thuật ngữ chuyên ngành, sự kiện/số liệu minh chứng.]",
                    "color_theme": "#06B6D4",
                    "order": 2,
                },
                {
                    "morph_id": "step_4",
                    "title": "[GIAI ĐOẠN 4 — khẳng định cụ thể + mốc thời gian thật]",
                    "description": "[2-4 câu: bản chất giai đoạn, thuật ngữ chuyên ngành, sự kiện/số liệu minh chứng.]",
                    "color_theme": "#EC4899",
                    "order": 3,
                },
            ],
        },
    ],
}, ensure_ascii=False, indent=2)


# =============================================================================
# SYSTEM PROMPT (v6 — DYNAMIC PERSONA + DYNAMIC LAYOUT DIVERSITY)
# =============================================================================

SYSTEM_PROMPT_TEMPLATE = """Bạn là UNIVERSAL DOMAIN EXPERT — hệ thống AI chuyên sinh nội dung trình chiếu đạt chuẩn TED/Keynote. Trước khi viết BẤT KỲ CHỮ NÀO, bạn phải làm 3 việc: (1) chọn style nếu tham số là AUTO, (2) nhận diện lĩnh vực của chủ đề, (3) NHẬP VAI chuyên gia hàng đầu lĩnh vực đó.

══════════════════════════════════════════════════════════════════════
BƯỚC 0 — AUTO STYLE SELECTION (CHỌN STYLE TỰ ĐỘNG) — BẮT BUỘC
══════════════════════════════════════════════════════════════════════

Payload frontend mới gửi `style = "AUTO"`. Khi thấy AUTO, bạn KHÔNG được trả
"AUTO". Hãy đọc ngữ cảnh chủ đề và trả về top-level field `style` là MỘT trong
các giá trị canonical sau:
- `Futuristic`: vũ trụ/thiên văn, AI, CNTT, phần mềm, cloud, cybersecurity,
  robotics, fintech kỹ thuật, kiến trúc hệ thống, dữ liệu thời gian thực.
- `CorporateMinimalist`: y học/sức khỏe, kinh tế/tài chính, báo cáo KPI, pitch
  deck cần độ tin cậy cao, chủ đề doanh nghiệp trang trọng.
- `Corporate`: điều hành, chiến lược công ty, quản trị, báo cáo kinh doanh cần
  cảm giác executive/luxury.
- `Minimalist`: chủ đề phổ thông cần tinh gọn, hiện đại, nhiều khoảng trắng.
- `Creative`: marketing, thương hiệu, nghệ thuật, du lịch, ẩm thực, giáo dục
  đại chúng cần màu sắc giàu năng lượng.
- `Academic`: nghiên cứu, đại học, khoa học giáo dục, lịch sử/văn hóa, bài giảng
  có tính học thuật, cần cấu trúc tri thức rõ ràng.

Nếu tham số style KHÁC AUTO, hãy giữ đúng style người dùng truyền vào. Dù ở chế
độ nào, JSON cuối cùng BẮT BUỘC có field `style` cấp cao nhất cùng cấp `topic`
và `slides`.

══════════════════════════════════════════════════════════════════════
BƯỚC 1 — NHẬP VAI CHUYÊN GIA (DYNAMIC ROLEPLAY) — BẮT BUỘC
══════════════════════════════════════════════════════════════════════

Đọc chủ đề trong vùng "=== USER TOPIC TO GENERATE ===" và tự đóng vai tương ứng:
- Thiên văn / vũ trụ (vd "solar system") → NHÀ THIÊN VĂN HỌC: viết về Mặt Trời (1.989×10³⁰ kg, nhiệt độ lõi ~15 triệu °C), Thủy Tinh (Mercury, năm 88 ngày), Kim Tinh (Venus, hiệu ứng nhà kính mất kiểm soát), Trái Đất (1 AU ≈ 150 triệu km), quỹ đạo elip Kepler, vành đai tiểu hành tinh giữa Hỏa và Mộc Tinh, vệ tinh, sao chổi, bức xạ mặt trời...
- Cà phê / nông sản / ẩm thực (vd "cà phê Việt Nam") → CHUYÊN GIA NÔNG NGHIỆP & THƯỞNG THỨC: Robusta (caffeine ~2.2-2.7%) vs Arabica (hương thơm phức, caffeine ~1.2-1.5%), thủ phủ Buôn Ma Thuột — Tây Nguyên, sơ chế ướt/khô/honey, rang medium/dark, crema, cupping, xuất khẩu top 2 thế giới...
- Y học / sức khỏe → BÁC SĨ / NHÀ NGHIÊN CỨU Y SINH: cơ chế bệnh sinh, triệu chứng lâm sàng, phác đồ điều trị, nghiên cứu RCT, tỷ lệ mắc/tử vong...
- Lịch sử / văn hóa → NHÀ SỬ HỌC: niên đại, triều đại, nhân vật, nhân-quả lịch sử, tư liệu...
- Công nghệ / AI / phần mềm → KỸ SƯ TRƯỞNG / ARCHITECT: kiến trúc hệ thống, thuật toán, thông số kỹ thuật, benchmark, độ trễ, throughput...
- Kinh tế / kinh doanh / khởi nghiệp → CHIẾN LƯỢC GIA CẤP CAO: doanh thu, tăng trưởng, thị phần, unit economics (CAC, LTV), dòng tiền...
- Lĩnh vực KHÁC bất kỳ → chuyên gia tương đương của CHÍNH lĩnh vực đó.

Sau khi nhập vai: toàn bộ ngôn ngữ, ví dụ, số liệu, thuật ngữ phải đậm chất GIỌNG CHUYÊN GIA của ngành đó, khâu nào cũng đúng kỷ cương chuyên môn — như thể người xem đang nghe chính chuyên gia thuyết trình. Nội dung phải LINH HOẠT theo chủ đề, TUYỆT ĐỐI KHÔNG kéo theo văn mẫu doanh nghiệp/B2B cho những chủ đề không phải kinh doanh.

══════════════════════════════════════════════════════════════════════
BƯỚC 2 — TOPIC ADHERENCE (BÁM SÁT CHỦ ĐỀ 100%)
══════════════════════════════════════════════════════════════════════

1. Nội dung nằm giữa hai dòng "=== USER TOPIC TO GENERATE ===" và
   "=== END OF USER TOPIC ===" là CHỦ ĐỀ DUY NHẤT được phép viết.
2. KHÔNG copy nội dung/số liệu từ phần VÍ DỤ trong prompt này. Mọi chữ trong
   ngoặc vuông [NHƯ THẾ NÀY] phải được thay thế bằng nội dung THẬT về chủ đề.
3. Trường `topic` phải phản ánh đúng chủ đề người dùng nhập.

══════════════════════════════════════════════════════════════════════
🚫 STRICT BAN — CẤM TUYỆT ĐỐI (title, slide_title, section, description)
══════════════════════════════════════════════════════════════════════

CÁC MẪU CÂU "GHÉP TỪ VÔ NGHĨA" — chỉ chèn tên chủ đề vào khuôn trống, không
chứa thông tin gì (kèm mọi biến thể viết hoa/viết lại tương đương):
- "Vì sao [chủ đề] là ưu tiên số 1", "...trở thành ưu tiên chiến lược"
- "Nhu cầu [chủ đề] đang tăng tốc", "Nhu cầu [chủ đề] đang gia tăng"
- "Điểm nghẽn [chủ đề]", "Điểm nghẽn đang kìm hãm tiến độ"
- "Cái giá của việc chần chừ"
- "Các tổ chức chậm thích ứng đang tụt lại phía sau"
CÁC NHÃN SÁO RỖNG: "Giới thiệu chủ đề", "Điểm nổi bật", "Cấu trúc bài",
"Yếu tố cốt lõi", "Tổng quan", "Phân tích chuyên sâu", "Dữ liệu & Bằng chứng",
"Giải pháp/Công nghệ", "Tác động chính", "Chỉ số đo lường", "Đặc điểm",
"Thành phần", "Lộ trình triển khai", "Kết luận".
→ Về bản chất: CẤM mọi câu chỉ cần thay tên chủ đề là chạy được ở mọi lĩnh
vực. Mỗi câu viết phải GẮN CHẶT với chủ đề qua thuật ngữ/số liệu/sự thật riêng.

══════════════════════════════════════════════════════════════════════
BƯỚC 3 — DOMAIN VOCABULARY RULE (TỪ VỰNG CHUYÊN NGÀNH — BẮT BUỘC)
══════════════════════════════════════════════════════════════════════

MỖI SLIDE phải chứa ÍT NHẤT 3 yếu tố chuyên ngành sau trong cụm title +
description của các thẻ:
(i)   THUẬT NGỮ KỸ THUẬT đúng ngành (vd "quỹ đạo elip", "sơ chế honey"),
(ii)  SỐ LIỆU / ĐẠI LƯỢNG kèm đơn vị (vd "4,6 tỷ năm", "~225 triệu km"),
(iii) SỰ THẬT / TÊN RIÊNG kiểm chứng được (vd "Buôn Ma Thuột", "định luật Kepler").
KHÔNG bịa số liệu giả. Nếu không chắc, dùng kiến thức nền đã được kiểm chứng
phổ biến của ngành, hoặc nêu phạm vi/ước lượng thận trọng ("ước tính", "khoảng").

══════════════════════════════════════════════════════════════════════
BƯỚC 4 — CẤU TRÚC 3 PHẦN BẮT BUỘC (NARRATIVE ARC)
══════════════════════════════════════════════════════════════════════

Mọi bài thuyết trình đều PHẢI có đủ 3 phần theo đúng thứ tự:

┌─ PHẦN 1 · MỞ BÀI = SLIDE ĐẦU TIÊN (slide_number 1) ────────────────┐
│ layout_type BẮT BUỘC = "COVER_HERO".                              │
│ Nhiệm vụ: ĐẶT VẤN ĐỀ bằng một câu hỏi dẫn dắt hoặc một tuyên bố   │
│ gây tò mò, khiến người xem muốn nghe tiếp.                        │
└────────────────────────────────────────────────────────────────────┘
┌─ PHẦN 2 · THÂN BÀI = SLIDE 2 → SLIDE N-1 ─────────────────────────┐
│ Phân tích, chứng minh bằng DỮ LIỆU / CƠ CHẾ / QUY TRÌNH.          │
│ Mỗi slide một luận điểm; dùng XEN KẼ các bố cục ở BƯỚC 5.          │
└────────────────────────────────────────────────────────────────────┘
┌─ PHẦN 3 · KẾT BÀI = SLIDE CUỐI CÙNG (slide_number N) ─────────────┐
│ layout_type BẮT BUỘC = "CONCLUSION_SUMMARY".                      │
│ Nhiệm vụ: TÓM TẮT thông điệp cốt lõi (3 điểm) + BÀI HỌC RÚT RA    │
│ + lời kêu gọi hành động cụ thể.                                   │
└────────────────────────────────────────────────────────────────────┘

Trường hợp đặc biệt:
- num_slides = 1 → chỉ có slide MỞ BÀI (COVER_HERO), vẫn phải nêu được vấn đề.
- num_slides = 2 → slide 1 = COVER_HERO, slide 2 = CONCLUSION_SUMMARY.
- num_slides >= 3 → đầy đủ 3 phần như sơ đồ trên.

`section` của từng slide phải phản ánh đúng vị trí trong mạch kể (viết HOA, ngắn):
mở bài dùng nhãn dạng "CÂU HỎI MỞ ĐẦU"/"VẤN ĐỀ"/"BỐI CẢNH"; thân bài dùng nhãn
chuyên môn ("CẤU TẠO", "CƠ CHẾ", "SỐ LIỆU", "SƠ CHẾ", "DI SẢN"...); kết bài dùng
"KẾT LUẬN"/"BÀI HỌC RÚT RA"/"HÀNH ĐỘNG". KHÔNG dùng nhãn sáo rỗng trong STRICT BAN.

══════════════════════════════════════════════════════════════════════
BƯỚC 5 — PHÂN BỔ BỐ CỤC PHÁ CÁCH (CREATIVE LAYOUT ALLOCATION)
══════════════════════════════════════════════════════════════════════

Trường `layout_type` quyết định hình học slide. Python sẽ tự vẽ; bạn phải chọn
ĐÚNG bố cục và cung cấp ĐÚNG số thẻ với đúng vai trò của từng thẻ.

▸ SLIDE 1 (MỞ BÀI) — `layout_type = "COVER_HERO"` — ĐÚNG 3 thẻ
  Thiết kế: tiêu đề SIÊU LỚN lệch trái + subtitle nổi bật + hàng badge.
  • `slide_title` : tiêu đề 6-12 từ, là CÂU HỎI DẪN DẮT hoặc tuyên bố gây sốc,
                    chứa số liệu/thuật ngữ chuyên ngành.
  • `cards[0]`    : CÂU HOOK (subtitle) — `title` là câu dẫn 8-15 từ nêu vấn đề;
                    `description` là 1-2 câu bối cảnh kèm số liệu thật.
  • `cards[1..2]` : BADGE — `title` là nhãn CỰC NGẮN 1-3 từ (VIẾT HOA hoặc một
                    đại lượng, vd "KHÍ QUYỂN", "465 °C", "RUNAWAY GHG");
                    `description` là 1 câu chú thích ngắn cho nhãn đó.

▸ SLIDE 2 → SLIDE N-1 (THÂN BÀI) — DÙNG XEN KẼ 4 bố cục sau:

  1. `BIG_STAT_CALLOUT` — ĐÚNG 2-3 thẻ
     Số liệu khổng lồ bên trái, văn bản giải thích bên phải.
     • `cards[0]` : CON SỐ / TỪ KHÓA KHỔNG LỒ — `title` càng ngắn càng tốt
       ("92 bar", "465 °C", "+35%", "1.989×10³⁰ kg"); `description` giải thích
       ý nghĩa của con số đó (2-3 câu, có so sánh để dễ hình dung).
     • `cards[1..]` : văn bản giải thích bổ trợ, mỗi thẻ 2-3 câu.

  2. `ASYMMETRIC_GRID` — ĐÚNG 3 thẻ
     Lưới bất đối xứng: thẻ Hero chiếm 60% chiều rộng, 2 thẻ phụ xếp dọc 40%.
     • `cards[0]` : HERO — luận điểm chính của slide, `title` 6-12 từ,
       `description` là đoạn sâu nhất slide (3-5 câu).
     • `cards[1]`, `cards[2]` : thẻ phụ bổ trợ, `title` 3-6 từ, `description` 2-3 câu.

  3. `TIMELINE_STEPS` — ĐÚNG 3-4 thẻ
     Quy trình/tiến trình theo thứ tự thời gian, mỗi thẻ là MỘT BƯỚC.
     `title` nêu tên bước + mốc thời gian; `description` mô tả điều xảy ra ở bước đó.

  4. `CARDS_ROW` — ĐÚNG 2-3 thẻ
     Các yếu tố ngang hàng: so sánh, nguyên nhân - hệ quả, các trụ cột.

▸ SLIDE N (KẾT BÀI) — `layout_type = "CONCLUSION_SUMMARY"` — ĐÚNG 4 thẻ
  Thiết kế: 3 dòng card mỏng bo góc chứa 3 điểm cốt lõi + thanh CTA nổi bật bên dưới.
  • `cards[0..2]` : 3 ĐIỂM CỐT LÕI — `title` là bài học rút ra (4-10 từ, khẳng định);
                    `description` 1-2 câu tóm gọn bằng chứng.
  • `cards[3]`    : CALL TO ACTION — `title` là lời kêu gọi hành động BẮT ĐẦU BẰNG
                    ĐỘNG TỪ ("Theo dõi...", "Áp dụng...", "Đầu tư...");
                    `description` nêu bước thực hiện đầu tiên, cụ thể.

⚠️ QUY TẮC CỨNG (CRITICAL RULES):
1. TUYỆT ĐỐI KHÔNG dùng cùng một `layout_type` cho 2 slide LIÊN TIẾP.
2. KHÔNG dùng `COVER_HERO` hoặc `CONCLUSION_SUMMARY` ở giữa bài.
3. KHÔNG dùng `COVER_HERO` cho slide cuối, và KHÔNG dùng `CONCLUSION_SUMMARY`
   cho slide đầu.
4. Với num_slides = 5, một chuỗi bố cục hợp lệ là:
   COVER_HERO → BIG_STAT_CALLOUT → ASYMMETRIC_GRID → TIMELINE_STEPS → CONCLUSION_SUMMARY.
5. Các bố cục đời cũ `SPLIT_HERO`, `STAT_GRID`, `GRID_2X2` KHÔNG được dùng nữa
   (hệ thống sẽ tự nâng cấp chúng sang bố cục mới tương đương).

══════════════════════════════════════════════════════════════════════
BƯỚC 6 — NỘI DUNG SÂU & MẠCH KỂ THEO LĨNH VỰC
══════════════════════════════════════════════════════════════════════

A. **MỖI TIÊU ĐỀ LÀ MỘT KHẲNG ĐỊNH CỤ THỂ**, không phải nhãn danh mục.
   - ĐÚNG: "Kim Tinh nóng 465 °C dù ở xa Mặt Trời hơn Thủy Tinh".
   - ĐÚNG: "Robusta chiếm ~90% diện tích cà phê Việt Nam".
   - SAI:  "Tổng quan hệ mặt trời". / "Nhu cầu cà phê đang tăng tốc".
   - `title` dài 1-10 từ; chứa thực thể/thuật ngữ hoặc con số của chính chủ đề.
     (Riêng slide COVER_HERO và CONCLUSION_SUMMARY được phép dài tới 12-15 từ.)

B. **THẺ GỒM 2 PHẦN**: `title` = khẳng định ngắn hoặc con số; `description` = đoạn
   diễn giải hoặc label súc tích giải thích cơ chế, kèm thuật ngữ/số liệu/quan hệ
   nhân quả như đã nêu ở BƯỚC 3.

C. **CHỌN MẠCH THÂN BÀI TỰ NHIÊN NHẤT THEO LĨNH VỰC** (nằm giữa MỞ BÀI và KẾT BÀI):
   - KHOA HỌC / KHÁM PHÁ: Cấu tạo/Thành phần → Cơ chế vận hành → Điểm kỳ thú /
     Khám phá mới → Ý nghĩa.
   - LỊCH SỬ / VĂN HÓA: Bối cảnh → Diễn biến chính → Bước ngoặt → Hệ quả.
   - Y KHOA / SỨC KHỎE: Căn nguyên → Cơ chế → Biểu hiện → Phòng ngừa/Điều trị.
   - CÔNG NGHỆ: Kiến trúc → Nguyên lý hoạt động → Ứng dụng → Tác động.
   - ẨM THỰC / NÔNG SẢN: Giống & vùng trồng → Canh tác/Thu hoạch → Sơ chế/Chế biến →
     Phẩm vị/Vị thế thị trường.
   - KINH DOANH (chỉ khi chủ đề thật sự là kinh doanh): Vấn đề → Nguyên nhân →
     Giải pháp → Kết quả.
   - Slide sau nối tiếp slide trước, không rời rạc, không lặp lại.

══════════════════════════════════════════════════════════════════════
BƯỚC 7 — CÁC QUY TẮC CẤU TRÚC JSON (STRUCTURAL RULES)
══════════════════════════════════════════════════════════════════════

1. **STYLE + NỘI DUNG & LAYOUT_TYPE, KHÔNG HÌNH HỌC**: JSON top-level phải có
   `topic`, `style`, `slides`. KHÔNG trả `x/y/width/height` — Python tự tính tọa
   độ. Bạn chỉ quyết định: `style`, `section`, `slide_title`, `layout_type`, và
   mỗi card có `morph_id`, `title`, `description`, `color_theme`, `order`.
2. **MORPH_ID**: ngắn, chữ thường gạch dưới, không dấu/khoảng trắng (vd
   "hero_card", "orbit_card", "card_1"). GIỮ NGUYÊN morph_id giữa slide N và
   N+1 cho cùng một đối tượng nội dung (để PowerPoint Morph nội suy mượt);
   thẻ mới dùng id mới.
3. **MÀU color_theme** = màu ACCENT tươi, bão hòa (hex 6 ký tự, kèm #):
   - Futuristic: #8B5CF6 (tím), #06B6D4 (cyan), #EC4899 (hồng), #10B981 (ngọc).
   - Minimalist: #6366F1 (indigo), #38BDF8 (sky), #10B981 (ngọc), #C9A227 (vàng đồng).
   - Corporate:  #C9A227 (vàng đồng), #10B981 (ngọc), #3A86FF (xanh), #B08D2E (đồng).
   - CorporateMinimalist: #38BDF8 (sky), #10B981 (ngọc), #94A3B8 (slate), #5EEAD4 (teal).
   - Creative:   #EC4899 (hồng), #F59E0B (cam), #06B6D4 (cyan), #8B5CF6 (tím).
   - Academic:   #38BDF8 (sky), #A78BFA (lavender), #60A5FA (blue), #10B981 (ngọc).
   Thẻ đầu tiên (điểm nhấn) dùng màu accent chính; các thẻ sau đổi màu xen kẽ.
4. **NGÔN NGỮ**: toàn bộ nội dung theo ngôn ngữ yêu cầu ("vi" → Tiếng Việt tự
   nhiên, "en" → English), thuật ngữ quốc tế dùng đúng chuẩn ngành.
5. **SỐ LƯỢNG SLIDE**: trả ĐÚNG số slide người dùng yêu cầu.
6. **ĐỊNH DẠNG**: trả DUY NHẤT một JSON object hợp lệ — không code fence,
   không giải thích, không chữ thừa trước/sau JSON.

══════════════════════════════════════════════════════════════════════
[VÍ DỤ MINH HOẠ CẤU TRÚC — TOÀN BỘ NỘI DUNG LÀ PLACEHOLDER, TUYỆT ĐỐI
KHÔNG SAO CHÉP; PHẢI THAY BẰNG NỘI DUNG THẬT VỀ USER TOPIC]
══════════════════════════════════════════════════════════════════════

VÍ DỤ 1 — 3 slide theo đúng MẠCH KỂ 3 PHẦN: COVER_HERO (mở bài) →
BIG_STAT_CALLOUT (thân bài) → CONCLUSION_SUMMARY (kết bài). morph_id giữ nguyên
cho đối tượng lặp lại giữa các slide:

__EXAMPLE_1__

---
VÍ DỤ 2 — 1 slide THÂN BÀI dạng tiến trình TIMELINE_STEPS (4 thẻ, số thứ tự
do Python tự vẽ):

__EXAMPLE_2__

══════════════════════════════════════════════════════════════════════
HÃY BẮT ĐẦU
══════════════════════════════════════════════════════════════════════
Đọc kỹ "=== USER TOPIC TO GENERATE ===" rồi làm đúng 4 việc:
1. CHỌN top-level `style`: nếu tham số là AUTO, tự phân tích ngữ cảnh và chọn
   Futuristic / Minimalist / Corporate / CorporateMinimalist / Creative / Academic.
2. NHẬP VAI chuyên gia đúng lĩnh vực của chủ đề.
3. DÀN Ý theo MẠCH KỂ 3 PHẦN: slide 1 = COVER_HERO (câu hỏi dẫn dắt), các slide
   giữa = BIG_STAT_CALLOUT / ASYMMETRIC_GRID / TIMELINE_STEPS / CARDS_ROW dùng
   XEN KẼ (không lặp 2 slide liên tiếp), slide cuối = CONCLUSION_SUMMARY
   (3 điểm cốt lõi + call to action).
4. VIẾT nội dung 100% bám sát chủ đề bằng từ vựng chuyên ngành thật, đúng số
   thẻ và đúng vai trò từng thẻ của bố cục đã chọn, theo cấu trúc JSON đã minh hoạ.
"""

SYSTEM_PROMPT = (
    SYSTEM_PROMPT_TEMPLATE
    .replace("__EXAMPLE_1__", _FEW_SHOT_EXAMPLE_1)
    .replace("__EXAMPLE_2__", _FEW_SHOT_EXAMPLE_2)
)


# =============================================================================
# HELPERS — Trích JSON, phân loại lỗi tạm thời, retry backoff
# =============================================================================

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

    # Quét ngoặc cân bằng để lấy object lồng đầu tiên hợp lệ
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
    """Phân loại lỗi tạm thời (đáng retry) vs lỗi logic (retry cũng vô ích)."""
    status = getattr(exc, "status_code", None)
    if isinstance(status, int) and status in (408, 429, 500, 502, 503, 504):
        return True
    name = type(exc).__name__.lower()
    return name in {
        "apiconnectionerror", "apitimeouterror", "apiconnectiontimeouterror",
        "timeouterror", "connecterror", "readtimeout", "remoteprotocolerror",
        "serviceunavailable", "internalservererror",
        "resourceexhausted",  # Gemini 429 — vẫn đáng 1 lần retry backoff dài
    }


async def _call_with_retry(
    provider_name: str,
    operation: Callable[[], Any],
) -> Any:
    """Gọi LLM với retry + exponential backoff CHỈ cho lỗi tạm thời (mạng/5xx/429)."""
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


def _temperature_for_attempt(attempt: int) -> float:
    """Temperature theo thang TEMPERATURE_LADDER cho lần thử thứ ``attempt`` (1-based)."""
    return TEMPERATURE_LADDER[min(max(attempt - 1, 0), len(TEMPERATURE_LADDER) - 1)]


# =============================================================================
# OPENAI CLIENT
# =============================================================================
_openai_client: Optional[Any] = None


def _get_openai_client() -> Any:
    global _openai_client
    if _openai_client is None:
        from openai import AsyncOpenAI
        _openai_client = AsyncOpenAI(
            api_key=settings.OPENAI_API_KEY,
            timeout=LLM_REQUEST_TIMEOUT_S,
            max_retries=0,  # retry do _call_with_retry kiểm soát
        )
    return _openai_client


def _build_user_prompt(req: GenerateRequest) -> str:
    """Xây dựng user prompt — đặt chủ đề giữa 2 DELIMITER độc đáo."""
    lang = "Tiếng Việt" if (req.language or "vi").lower().startswith("vi") else "English"

    logger.info(
        "Building user prompt | prompt=%r | num_slides=%d | style=%s | lang=%s",
        req.prompt[:120], req.num_slides, req.style, lang,
    )

    n = req.num_slides
    if n <= 1:
        arc_line = (
            "- MẠCH KỂ: chỉ 1 slide → BẮT BUỘC layout_type='COVER_HERO' "
            "(slide mở bài nêu vấn đề/câu hỏi dẫn dắt)."
        )
    elif n == 2:
        arc_line = (
            "- MẠCH KỂ 3 PHẦN (rút gọn): slide 1 BẮT BUỘC 'COVER_HERO' (câu hỏi dẫn dắt) "
            "→ slide 2 BẮT BUỘC 'CONCLUSION_SUMMARY' (3 điểm cốt lõi + call to action)."
        )
    else:
        arc_line = (
            f"- MẠCH KỂ 3 PHẦN (BẮT BUỘC): slide 1 = 'COVER_HERO' (câu hỏi dẫn dắt, 3 thẻ: "
            f"1 hook + 2 badge) → slide 2..{n - 1} = thân bài dùng XEN KẼ 'BIG_STAT_CALLOUT' "
            f"(2-3 thẻ), 'ASYMMETRIC_GRID' (đúng 3 thẻ), 'TIMELINE_STEPS' (3-4 thẻ), "
            f"'CARDS_ROW' (2-3 thẻ) → slide {n} = 'CONCLUSION_SUMMARY' "
            f"(đúng 4 thẻ: 3 điểm cốt lõi + 1 call to action)."
        )

    if req.style == "AUTO":
        style_line = (
            "- Phong cách thiết kế: AUTO — BẮT BUỘC tự phân tích prompt và trả về "
            "top-level `style` đã chọn (không được trả AUTO).\n"
        )
    else:
        style_line = f"- Phong cách thiết kế: {req.style} (giữ đúng style này trong top-level `style`).\n"

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
        + style_line +
        f"- Tỉ lệ khung hình: {req.aspect_ratio}\n"
        f"- Ngôn ngữ nội dung (toàn bộ title/description dùng ngôn ngữ này): {lang}\n"
        f"- Sinh speaker notes: {'Có' if req.include_speaker_notes else 'Không'}\n"
        f"{arc_line}\n"
        "- ĐIỀU KIỆN BẮT BUỘC: KHÔNG ĐƯỢC để 2 slide liên tiếp có cùng một layout_type; "
        "KHÔNG dùng COVER_HERO/CONCLUSION_SUMMARY ở giữa bài; KHÔNG dùng các layout cũ "
        "SPLIT_HERO/STAT_GRID/GRID_2X2.\n\n"
        "NHẮC LẠI TRỰC TIẾP: Trước hết chọn top-level `style` hợp lệ (không trả AUTO), "
        "sau đó NHẬP VAI chuyên gia đúng lĩnh vực của chủ đề trên; mọi nội dung "
        "(topic, slide_title, title, description) phải "
        "BÁM SÁT 100% chủ đề đó với từ vựng chuyên ngành thật; tuyệt đối không "
        "dùng các mẫu câu trong STRICT BAN (\"Nhu cầu ... tăng tốc\", "
        "\"Điểm nghẽn ...\", \"ưu tiên số 1\"...), không copy nội dung ví dụ. "
        "Trả về đúng JSON schema LLMOutput, không markdown fence, không giải thích."
    )


# =============================================================================
# VALIDATION & CONTENT SMELL CHECK
# =============================================================================

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
        if not errors:
            errors = [str(exc)[:300]]
        raise ValueError("Pydantic Validation Error:\n" + "\n".join(errors[:5])) from exc


# Các cụm văn mẫu B2B rác/phần placeholder bị cấm
_BANNED_TEMPLATE_TOKENS = [
    "nhu cầu", "đang tăng tốc", "đang gia tăng", "điểm nghẽn", "kìm hãm",
    "cái giá của việc chần chừ", "cái giá chần chừ", "ưu tiên số 1",
    "ưu tiên chiến lược", "ưu tiên chiến lược số một", "tụt lại phía sau",
]

_PLACEHOLDER_TOKENS = [
    "[VÍ DỤ", "[CHỦ ĐỀ", "[TIÊU ĐỀ", "[NỘI DUNG", "[KHẲNG ĐỊNH",
    "VÍ DỤ MINH HOẠ", "KHÔNG SAO CHÉP", "PLACEHOLDER",
]


def _content_smell_check(result: LLMOutput, original_prompt: str) -> list:
    """Quét nhanh dấu hiệu nội dung rác; trả về danh sách vi phạm (rỗng = sạch)."""
    combined = (result.topic or "").lower()
    for s in result.slides:
        combined += " " + (s.section or "").lower() + " " + (s.slide_title or "").lower()
        for c in s.cards:
            combined += " " + (c.title or "").lower() + " " + (c.description or "").lower()

    hits = [t for t in _PLACEHOLDER_TOKENS if t.lower() in combined]
    if hits:
        logger.warning("Nội dung LLM nhiễm placeholder tokens=%s", hits)

    banned_hits = [t for t in _BANNED_TEMPLATE_TOKENS if t in combined]
    if banned_hits:
        logger.warning(
            "Nội dung LLM dính văn mẫu B2B bị cấm tokens=%s — sẽ yêu cầu LLM viết lại.",
            banned_hits,
        )
    else:
        prompt_tokens = {w for w in original_prompt.lower().split() if len(w) >= 3}
        topic_tokens = {w for w in (result.topic or "").lower().split() if len(w) >= 3}
        if prompt_tokens and topic_tokens and not (prompt_tokens & topic_tokens):
            logger.warning(
                "Topic kết quả %r không chia sẻ từ khóa nào với user prompt %r — có thể lệch chủ đề.",
                result.topic[:60], original_prompt[:60],
            )
    return hits + banned_hits


# =============================================================================
# PIPELINE: GỌI LLM → PARSE → VALIDATE → SMELL CHECK (retry với thang nhiệt độ)
# =============================================================================

async def _parse_with_retry(
    raw_text_getter: Callable[[list, float], Any],
    build_messages: Callable[[str], list],
    req: GenerateRequest,
    provider: str,
) -> LLMOutput:
    """Gọi LLM → trích JSON → validate Pydantic → reject nội dung vi phạm."""
    last_error: Optional[str] = None

    for attempt in range(1, MAX_VALIDATION_RETRIES + 2):
        temperature = _temperature_for_attempt(attempt)
        user_prompt_text = _build_user_prompt(req)

        if last_error is not None:
            user_prompt_text = (
                user_prompt_text
                + f"\n\n=== LỖI LẦN TRƯỚC (HÃY SỬA) ===\n{last_error}\n\n"
                + "Hãy trả về JSON ĐÃ SỬA: có top-level `style` hợp lệ (nếu AUTO thì "
                + "tự chọn style theo ngữ cảnh, không trả AUTO), nhập vai chuyên gia đúng lĩnh vực, dùng "
                + "từ vựng chuyên ngành thật, tuân thủ MẠCH KỂ 3 PHẦN "
                + "(slide 1 = COVER_HERO, slide cuối = CONCLUSION_SUMMARY, thân bài "
                + "dùng XEN KẼ BIG_STAT_CALLOUT / ASYMMETRIC_GRID / TIMELINE_STEPS / "
                + "CARDS_ROW — không để 2 slide liên tiếp cùng layout_type), đúng số "
                + "thẻ của từng bố cục, không dùng văn mẫu bị cấm, đúng schema, "
                + "không giải thích."
            )

        messages = build_messages(user_prompt_text)

        raw_text = await raw_text_getter(messages, temperature)

        # --- Parse JSON ---
        try:
            data = _extract_json_object(raw_text or "")
        except ValueError as exc:
            last_error = f"Lỗi parse JSON: {exc}"
            logger.warning(
                "%s parse JSON lỗi (lần %d, temp=%.1f): %s — raw 200 ký tự đầu: %r",
                provider, attempt, temperature, last_error,
                _mask_sensitive((raw_text or "")[:200]),
            )
            if attempt > MAX_VALIDATION_RETRIES:
                logger.exception(
                    "%s parse JSON thất bại sau %d lần thử — FULL TRACEBACK:",
                    provider, attempt,
                )
                raise
            await asyncio.sleep(LLM_RETRY_BASE_DELAY_S * attempt)
            continue

        # --- Validate Pydantic ---
        try:
            result = _validate_llm_output(data)
        except ValueError as exc:
            last_error = str(exc)
            logger.warning(
                "%s Pydantic validation lỗi (lần %d, temp=%.1f): %s",
                provider, attempt, temperature, last_error[:200],
            )
            if attempt > MAX_VALIDATION_RETRIES:
                logger.exception(
                    "%s Pydantic validation thất bại sau %d lần thử — FULL TRACEBACK:",
                    provider, attempt,
                )
                raise
            await asyncio.sleep(LLM_RETRY_BASE_DELAY_S * attempt)
            continue

        # --- STRICT BAN smell check ---
        violations = _content_smell_check(result, req.prompt)
        if violations and attempt <= MAX_VALIDATION_RETRIES:
            last_error = (
                "Nội dung VI PHẠM STRICT BAN / còn placeholder: "
                + ", ".join(sorted(set(violations))[:8])
                + ". TUYỆT ĐỐI không dùng các cụm trên — hãy viết lại bằng "
                + "khẳng định cụ thể với thuật ngữ/số liệu chuyên ngành của chủ đề."
            )
            logger.info(
                "%s yêu cầu viết lại do vi phạm STRICT BAN (lần %d, temp=%.1f): %s",
                provider, attempt, temperature, violations,
            )
            await asyncio.sleep(LLM_RETRY_BASE_DELAY_S * attempt)
            continue

        logger.info(
            "%s đã sinh thành công %d slide (topic=%r, style=%s, lần %d, temp=%.1f)",
            provider, len(result.slides), result.topic[:60], result.style, attempt, temperature,
        )
        return result

    raise RuntimeError("Unreachable: retry loop exhausted")


# =============================================================================
# PROVIDER IMPLEMENTATIONS
# =============================================================================

def _make_schema_strict_for_openai(node: Any) -> None:
    """Đảm bảo mọi object trong JSON Schema đều có 'required' chứa toàn bộ properties (yêu cầu OpenAI strict: True)."""
    if isinstance(node, dict):
        if node.get("type") == "object" and "properties" in node:
            node["required"] = list(node["properties"].keys())
        for v in node.values():
            _make_schema_strict_for_openai(v)
    elif isinstance(node, list):
        for item in node:
            _make_schema_strict_for_openai(item)


async def _generate_with_openai(req: GenerateRequest) -> LLMOutput:
    """Gọi OpenAI JSON-schema structured output, temperature theo thang retry."""
    if not settings.OPENAI_API_KEY or not settings.OPENAI_API_KEY.strip():
        raise LLMConfigurationError(
            "OPENAI_API_KEY đang trống hoặc chỉ gồm khoảng trắng — kiểm tra biến "
            "môi trường của Backend (Render Env Vars / file .env)."
        )
    logger.info(
        "Gọi OpenAI model=%r key=%s (đã mask)...",
        settings.OPENAI_MODEL,
        f"{settings.OPENAI_API_KEY[:4]}...****" if settings.OPENAI_API_KEY else "<trống>",
    )

    client = _get_openai_client()
    json_schema = LLMOutput.model_json_schema()
    json_schema.pop("title", None)
    _make_schema_strict_for_openai(json_schema)

    def _messages(user_content: str) -> list:
        return [
            {"role": "system", "content": SYSTEM_PROMPT},
            {"role": "user", "content": user_content},
        ]

    async def _raw_getter(messages: list, temperature: float) -> str:
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
                    temperature=temperature,
                )
            except Exception:  # noqa: BLE001
                return await client.chat.completions.create(
                    model=settings.OPENAI_MODEL,
                    messages=messages,
                    response_format={"type": "json_object"},
                    temperature=temperature,
                )
        resp = await _call_with_retry("OpenAI", _call)
        return resp.choices[0].message.content if resp.choices else None

    return await _parse_with_retry(_raw_getter, _messages, req, "OpenAI")


async def _generate_with_gemini(req: GenerateRequest) -> LLMOutput:
    """Gọi Google Gemini với response_schema, temperature theo thang retry."""
    if not settings.GEMINI_API_KEY or not settings.GEMINI_API_KEY.strip():
        raise LLMConfigurationError(
            "GEMINI_API_KEY đang trống hoặc chỉ gồm khoảng trắng — kiểm tra biến "
            "môi trường của Backend (Render Env Vars / file .env)."
        )
    _check_gemini_model_name()
    logger.info(
        "Gọi Gemini model=%r key=%s (đã mask)...",
        settings.GEMINI_MODEL,
        f"{settings.GEMINI_API_KEY[:4]}...****" if settings.GEMINI_API_KEY else "<trống>",
    )

    import google.generativeai as genai
    genai.configure(api_key=settings.GEMINI_API_KEY)

    gemini_schema = _gemini_response_schema()

    def _build_model(temperature: float, use_schema: bool = True):
        generation_config = {
            "response_mime_type": "application/json",
            "temperature": temperature,
        }
        if use_schema and gemini_schema is not None:
            generation_config["response_schema"] = gemini_schema
        try:
            model = genai.GenerativeModel(
                model_name=settings.GEMINI_MODEL,
                generation_config=generation_config,
                system_instruction=SYSTEM_PROMPT,
            )
            return model, True
        except TypeError:
            logger.warning(
                "google-generativeai quá cũ để dùng system_instruction — "
                "nhồi system prompt vào user message. Hãy nâng: pip install -U google-generativeai"
            )
            return genai.GenerativeModel(
                model_name=settings.GEMINI_MODEL,
                generation_config=generation_config,
            ), False

    def _messages(user_content: str) -> list:
        return [user_content]

    async def _call_generate(model, has_system: bool, user_content: str):
        content = user_content if has_system else f"{SYSTEM_PROMPT}\n\n{user_content}"
        return await model.generate_content_async(content)

    async def _raw_getter(messages: list, temperature: float) -> str:
        model, has_system = _build_model(temperature, use_schema=True)

        async def _call():
            return await _call_generate(model, has_system, messages[0])

        try:
            resp = await _call_with_retry("Gemini", _call)
        except ValueError as exc:
            if "Unknown field for Schema" not in str(exc):
                raise
            logger.warning(
                "Gemini SDK từ chối response_schema (%s) — thử lại chỉ với "
                "response_mime_type=application/json.",
                _summarize_exc(exc),
            )
            model, has_system = _build_model(temperature, use_schema=False)

            async def _call_mime_only():
                return await _call_generate(model, has_system, messages[0])

            resp = await _call_with_retry("Gemini", _call_mime_only)

        try:
            return getattr(resp, "text", None)
        except (ValueError, AttributeError) as exc:
            raise ValueError(
                f"Gemini không trả về text hợp lệ (bị chặn hoặc rỗng): {exc}"
            ) from exc

    return await _parse_with_retry(_raw_getter, _messages, req, "Gemini")


_PROVIDER_FUNCS = {
    "openai": _generate_with_openai,
    "gemini": _generate_with_gemini,
}


# =============================================================================
# GEMINI SCHEMA SANITIZER
# =============================================================================

_GEMINI_PROTO_SCHEMA_KEYS = {
    "type", "format", "description", "nullable", "enum",
    "items", "properties", "required",
}

_GEMINI_TYPE_NAME_MAP = {
    "object": "OBJECT", "string": "STRING", "integer": "INTEGER",
    "number": "NUMBER", "boolean": "BOOLEAN", "array": "ARRAY",
}


def _resolve_json_refs(node: Any, defs: dict) -> Any:
    """Duỗi phẳng các tham chiếu {"$ref": "#/$defs/X"}."""
    if isinstance(node, dict):
        if "$ref" in node:
            ref_name = str(node["$ref"]).split("/")[-1]
            target = defs.get(ref_name)
            if not isinstance(target, dict):
                return {}
            base = _resolve_json_refs(target, defs)
            for key, value in node.items():
                if key != "$ref":
                    base[key] = _resolve_json_refs(value, defs)
            return base
        return {key: _resolve_json_refs(value, defs) for key, value in node.items()}
    if isinstance(node, list):
        return [_resolve_json_refs(item, defs) for item in node]
    return node


def _sanitize_for_gemini(node: Any) -> Any:
    """Loại bỏ mọi trường JSON-Schema mà Gemini proto Schema không hỗ trợ."""
    if isinstance(node, dict):
        sanitized: dict = {}
        for key, value in node.items():
            if key == "type" and isinstance(value, str):
                sanitized["type"] = _GEMINI_TYPE_NAME_MAP.get(value.lower(), value.upper())
            elif key == "description" and isinstance(value, str):
                sanitized["description"] = value[:1000]
            elif key in ("nullable", "format"):
                sanitized[key] = value
            elif key == "enum" and isinstance(value, list):
                sanitized["enum"] = [str(v) for v in value]
            elif key == "items":
                sanitized["items"] = _sanitize_for_gemini(value)
            elif key == "properties" and isinstance(value, dict):
                sanitized["properties"] = {
                    prop: _sanitize_for_gemini(sub) for prop, sub in value.items()
                }
            elif key == "required" and isinstance(value, list):
                sanitized["required"] = [str(v) for v in value]
        if "properties" in sanitized and "type" not in sanitized:
            sanitized["type"] = "OBJECT"
        if "items" in sanitized and "type" not in sanitized:
            sanitized["type"] = "ARRAY"
        return sanitized
    return node


_gemini_schema_cache: Optional[dict] = None


def _gemini_response_schema() -> Optional[dict]:
    """Schema LLMOutput đã sanitize cho Gemini (cache 1 lần). None nếu không dựng được."""
    global _gemini_schema_cache
    if _gemini_schema_cache is not None:
        return _gemini_schema_cache
    try:
        raw = LLMOutput.model_json_schema()
        defs = raw.get("$defs", {})
        resolved = _resolve_json_refs(raw, defs)
        sanitized = _sanitize_for_gemini(resolved)
        if not isinstance(sanitized, dict) or "properties" not in sanitized:
            logger.warning("Không dựng được response_schema cho Gemini — dùng JSON mime-type only.")
            return None
        _gemini_schema_cache = sanitized
        logger.info("Gemini response_schema đã sanitize (proto-compatible) thành công.")
        return sanitized
    except Exception:  # noqa: BLE001
        logger.exception("Lỗi khi dựng response_schema cho Gemini — FULL TRACEBACK:")
        return None


def _provider_ready(provider: str) -> bool:
    """Key phải tồn tại và có nội dung thực (không phải chuỗi khoảng trắng)."""
    if provider == "openai":
        return bool(settings.OPENAI_API_KEY and settings.OPENAI_API_KEY.strip())
    if provider == "gemini":
        return bool(settings.GEMINI_API_KEY and settings.GEMINI_API_KEY.strip())
    return False


_KNOWN_GEMINI_PREFIXES = ("gemini-", "tunedModels/", "models/gemini-")


def _check_gemini_model_name() -> None:
    model = (settings.GEMINI_MODEL or "").strip()
    if not model:
        logger.warning(
            "GEMINI_MODEL đang RỖNG — hãy đặt vd 'gemini-1.5-flash' hoặc 'gemini-1.5-pro' "
            "(xem danh sách model tại Google AI Studio)."
        )
        return
    if not model.startswith(_KNOWN_GEMINI_PREFIXES):
        logger.warning(
            "GEMINI_MODEL=%r trông KHÔNG giống tên model Gemini hợp lệ — Google sẽ trả "
            "InvalidArgument/NotFound. Giá trị thường dùng: 'gemini-1.5-flash', "
            "'gemini-1.5-pro', 'gemini-2.0-flash'.",
            model,
        )


# =============================================================================
# ENTRY POINT CHÍNH — 100% LLM, KHÔNG CÒN FALLBACK VĂN MẪU
# =============================================================================

async def generate_presentation_with_llm(req: GenerateRequest) -> PresentationResponse:
    """Gọi LLM → LLMOutput → Layout Engine → PresentationResponse."""
    provider = (settings.LLM_PROVIDER or "openai").lower()

    logger.info(
        "[AUDIT] generate_presentation_with_llm | prompt=%r | num_slides=%d | style=%s | lang=%s | provider=%s",
        req.prompt[:200], req.num_slides, req.style, req.language, provider,
    )

    if provider == "mock":
        raise LLMConfigurationError(
            "LLM_PROVIDER='mock' không còn được hỗ trợ: ExoticMorph chỉ sinh nội "
            "dung bằng LLM thật để đảm bảo chất lượng. Hãy đặt LLM_PROVIDER='gemini' "
            "hoặc 'openai' kèm API key hợp lệ trong biến môi trường của Backend."
        )

    provider_chain: list = []
    if _provider_ready(provider):
        provider_chain.append(provider)
    else:
        logger.warning("LLM_PROVIDER='%s' chưa có API key — bỏ qua.", provider)
    for alt in ("openai", "gemini"):
        if alt != provider and _provider_ready(alt):
            provider_chain.append(alt)

    if not provider_chain:
        raise LLMConfigurationError(
            "Backend chưa cấu hình API key cho bất kỳ LLM nào "
            "(GEMINI_API_KEY / OPENAI_API_KEY đều trống). Người vận hành cần bổ "
            "sung key hợp lệ vào biến môi trường của Backend rồi thử lại."
        )

    failures: list = []
    for name in provider_chain:
        try:
            raw_output: LLMOutput = await _PROVIDER_FUNCS[name](req)
        except Exception as exc:  # noqa: BLE001
            logger.exception(
                "Provider '%s' thất bại với exception %s: %s",
                name, type(exc).__name__, _summarize_exc(exc, limit=500),
            )
            reason, hint = _diagnose_exception(exc, name)
            failures.append((name, reason, hint, _summarize_exc(exc)))
            continue

        presentation = compute_layout(raw_output, req)
        logger.info(
            "[AUDIT] Provider '%s' trả topic=%r, llm_style=%s, resolved_style=%s (user prompt=%r)",
            name, raw_output.topic[:80], raw_output.style, presentation.style, req.prompt[:80],
        )
        return presentation

    final_message = _build_failure_message(failures)
    logger.error(
        "TẤT CẢ LLM PROVIDER ĐỀU THẤT BẠI — trả HTTP 502 cho client.\n%s",
        final_message,
    )
    raise LLMGenerationError(final_message)
