"""
LLM Service Module for ExoticMorph (v6 — Dynamic Layout Diversity + Dynamic Persona)
~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~
Thay đổi cốt lõi:

1. **DYNAMIC LAYOUT DIVERSITY (BỐ CỤC ĐA DẠNG THEO NGỮ CẢNH)**:
   - Thay vì 100% slide đều có cùng bố cục nằm ngang cũ, LLM được hướng dẫn
     chọn `layout_type` phù hợp ngữ cảnh từng slide:
     * `SPLIT_HERO`     : Slide định nghĩa / khái niệm / hero highlight.
     * `STAT_GRID`      : Slide nhấn mạnh số liệu / KPI / kết quả định lượng.
     * `TIMELINE_STEPS` : Slide quy trình / tiến trình / lộ trình 3-4 bước ngang.
     * `CARDS_ROW`      : Slide liệt kê 2-3 yếu tố ngang hàng / so sánh.
     * `GRID_2X2`       : Slide phân loại 4 nhóm yếu tố, ma trận 4 góc cân đối.
   - **ĐIỀU KIỆN BẮT BUỘC**: Trong một bài thuyết trình, KHÔNG ĐƯỢC để 2 slide
     liên tiếp có cùng một `layout_type`.

2. **DYNAMIC PERSONA SYSTEM PROMPT**:
   - LLM tự nhận diện lĩnh vực của chủ đề (Thiên văn, Lịch sử, Y học, Nông nghiệp,
     Công nghệ...) rồi NHẬP VAI chuyên gia hàng đầu lĩnh vực đó, dùng đúng từ vựng
     chuyên ngành. Mỗi slide bắt buộc chứa ít nhất 3 thuật ngữ/số liệu/sự thật
     chuyên ngành (Domain Vocabulary Rule) và cấm tuyệt đối văn mẫu B2B sáo rỗng.

3. **JSON PARSE RETRY với THANG NHIỆT ĐỘ**:
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
    "slides": [
        {
            "slide_number": 1,
            "section": "[KHÁI NIỆM — bước 1 trong mạch kể]",
            "slide_title": "[LUẬN ĐIỂM CỐT LÕI chứa thuật ngữ chuyên ngành + số liệu/mốc thời gian]",
            "layout_type": "SPLIT_HERO",
            "cards": [
                {
                    "morph_id": "hero_card",
                    "title": "[KHẲNG ĐỊNH CỐT LÕI HERO: thực thể + đại lượng/sự kiện THẬT]",
                    "description": "[2-4 câu diễn giải bằng GIỌNG CHUYÊN GIA của ngành: 3-4 thuật ngữ chuyên ngành + số liệu/đơn vị/ví dụ thật + quan hệ nhân quả. KHÔNG viết chung chung.]",
                    "color_theme": "#8B5CF6",
                    "order": 0,
                },
                {
                    "morph_id": "sub_card_1",
                    "title": "[CHIỀU CẠNH BỔ TRỢ 1: luận cứ hỗ trợ hero]",
                    "description": "[2-4 câu: thuật ngữ + dẫn chứng + ý nghĩa thực tiễn, đúng chuyên môn ngành.]",
                    "color_theme": "#10B981",
                    "order": 1,
                },
                {
                    "morph_id": "sub_card_2",
                    "title": "[CHIỀU CẠNH BỔ TRỢ 2: luận cứ tiếp theo]",
                    "description": "[2-4 câu: thuật ngữ + con số/mốc thời gian + vì sao nó quan trọng.]",
                    "color_theme": "#06B6D4",
                    "order": 2,
                },
            ],
        },
        {
            "slide_number": 2,
            "section": "[KẾT QUẢ ĐỊNH LƯỢNG — bước 2 trong mạch kể]",
            "slide_title": "[CÁC CHỈ SỐ VÀ ĐẠI LƯỢNG ĐO LƯỜNG NỔI BẬT]",
            "layout_type": "STAT_GRID",
            "cards": [
                {
                    "morph_id": "stat_card_1",
                    "title": "[465 °C]",
                    "description": "[Nhiệt độ bề mặt cực hạn do hiệu ứng nhà kính mất kiểm soát, cao hơn cả Thủy Tinh gần Mặt Trời hơn.]",
                    "color_theme": "#8B5CF6",
                    "order": 0,
                },
                {
                    "morph_id": "stat_card_2",
                    "title": "[1.989×10³⁰ kg]",
                    "description": "[Khối lượng Mặt Trời chiếm tới 99.86% tổng khối lượng toàn bộ hệ thống hành tinh.]",
                    "color_theme": "#10B981",
                    "order": 1,
                },
                {
                    "morph_id": "stat_card_3",
                    "title": "[88 ngày]",
                    "description": "[Chu kỳ quỹ đạo elip siêu tốc của Thủy Tinh quanh Mặt Trời với vận tốc 47 km/s.]",
                    "color_theme": "#06B6D4",
                    "order": 2,
                },
            ],
        },
    ],
}, ensure_ascii=False, indent=2)

_FEW_SHOT_EXAMPLE_2 = json.dumps({
    "topic": "[CHỦ ĐỀ KHÁC CỦA NGƯỜI DÙNG]",
    "slides": [
        {
            "slide_number": 1,
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

SYSTEM_PROMPT_TEMPLATE = """Bạn là UNIVERSAL DOMAIN EXPERT — hệ thống AI chuyên sinh nội dung trình chiếu đạt chuẩn TED/Keynote. Trước khi viết BẤT KỲ CHỮ NÀO, bạn phải làm 2 việc: (1) nhận diện lĩnh vực của chủ đề, (2) NHẬP VAI chuyên gia hàng đầu lĩnh vực đó.

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
BƯỚC 4 — NỘI DUNG SÂU & MẠCH KỂ THEO LĨNH VỰC
══════════════════════════════════════════════════════════════════════

A. **MỖI TIÊU ĐỀ LÀ MỘT KHẲNG ĐỊNH CỤ THỂ**, không phải nhãn danh mục.
   - ĐÚNG: "Kim Tinh nóng 465 °C dù ở xa Mặt Trời hơn Thủy Tinh".
   - ĐÚNG: "Robusta chiếm ~90% diện tích cà phê Việt Nam".
   - SAI:  "Tổng quan hệ mặt trời". / "Nhu cầu cà phê đang tăng tốc".
   - `title` dài 1-10 từ; chứa thực thể/thuật ngữ hoặc con số của chính chủ đề.

B. **THẺ GỒM 2 PHẦN**: `title` = khẳng định ngắn hoặc con số; `description` = đoạn
   diễn giải hoặc label súc tích giải thích cơ chế, kèm thuật ngữ/số liệu/quan hệ
   nhân quả như đã nêu ở BƯỚC 3.

C. **MẠCH KỂ LINH HOẠT THEO LĨNH VỰC** — chọn mạch tự nhiên nhất:
   - KHOA HỌC / KHÁM PHÁ: Khái quát → Cấu tạo/Thành phần → Cơ chế vận hành →
     Điểm kỳ thú / Khám phá mới → Ý nghĩa.
   - LỊCH SỬ / VĂN HÓA: Bối cảnh → Diễn biến chính → Bước ngoặt → Hệ quả → Di sản.
   - Y KHOA / SỨC KHỎE: Căn nguyên → Cơ chế → Biểu hiện → Phòng ngừa → Điều trị.
   - CÔNG NGHỆ: Thành phần/Kiến trúc → Nguyên lý hoạt động → Ứng dụng →
     Tác động → Hướng phát triển.
   - ẨM THỰC / NÔNG SẢN: Nguồn gốc/Giống & vùng trồng → Canh tác/Thu hoạch →
     Sơ chế/Chế biến → Phẩm vị/Trải nghiệm → Vị thế thị trường.
   - KINH DOANH (chỉ khi chủ đề thật sự là kinh doanh): Vấn đề → Nguyên nhân →
     Giải pháp → Kết quả → Hành động.
   - Slide sau nối tiếp slide trước, không rời rạc, không lặp lại.
   - `section` = nhãn mục VIẾT HOA ngắn gọn thể hiện vị trí trong mạch đã chọn
     (vd "CẤU TẠO", "CƠ CHẾ", "SƠ CHẾ", "DI SẢN"...), KHÔNG dùng nhãn sáo rỗng
     đã liệt kê trong STRICT BAN.

══════════════════════════════════════════════════════════════════════
BƯỚC 5 — QUY TẮC CHỌN BỐ CỤC ĐA DẠNG (DYNAMIC LAYOUT DIVERSITY)
══════════════════════════════════════════════════════════════════════

BẮT BUỘC chọn trường `layout_type` phù hợp cho TỪNG SLIDE dựa vào bản chất nội dung:

1. `SPLIT_HERO`:
   - Dành cho: Slide định nghĩa, khái niệm cốt lõi, tuyên bố trọng tâm (hero highlight).
   - Cấu trúc: Cột trái rộng chứa luận điểm chính (Hero point), cột phải xếp 2 thẻ phụ bổ trợ.
   - Số thẻ: Thường gồm 3 thẻ (Card 0 = Hero, Card 1 & 2 = Thẻ phụ).

2. `STAT_GRID`:
   - Dành cho: Slide có số liệu, chỉ số KPI, kết quả đo lường, minh chứng định lượng.
   - Cấu trúc: Nhấn mạnh số liệu (title là con số/đại lượng to nổi bật như '465 °C', '+35%', '1.989×10³⁰ kg', '90%') + description là label ngắn/giải thích ý nghĩa.
   - Số thẻ: 2-4 thẻ số liệu.

3. `TIMELINE_STEPS`:
   - Dành cho: Slide quy trình, tiến trình, lộ trình, chuỗi các bước thực hiện theo thứ tự thời gian.
   - Cấu trúc: Tiến trình 3-4 bước theo chiều ngang có vòng tròn số thứ tự và đường nối.
   - Số thẻ: 3-4 thẻ.

4. `CARDS_ROW`:
   - Dành cho: Slide liệt kê 2-3 yếu tố ngang hàng, so sánh các chiều cạnh.
   - Cấu trúc: 2-3 thẻ nằm ngang cân đối.
   - Số thẻ: 2-3 thẻ.

5. `GRID_2X2`:
   - Dành cho: Slide phân loại 4 nhóm yếu tố, ma trận 4 góc cân đối, 4 trụ cột.
   - Cấu trúc: Đúng 4 thẻ chia đều thành lưới 2 hàng x 2 cột.
   - Số thẻ: 4 thẻ.

⚠️ ĐIỀU KIỆN TIÊN QUYẾT BẮT BUỘC (CRITICAL DIVERSITY RULE):
- Trong cùng một bài thuyết trình, TUYỆT ĐỐI KHÔNG ĐƯỢC để 2 slide liên tiếp có cùng một `layout_type`.
- Phải luân chuyển linh hoạt giữa các layout để tạo trải nghiệm thị giác đa dạng, hấp dẫn người xem (ví dụ: Slide 1: SPLIT_HERO → Slide 2: STAT_GRID → Slide 3: TIMELINE_STEPS → Slide 4: GRID_2X2 → Slide 5: CARDS_ROW).

══════════════════════════════════════════════════════════════════════
BƯỚC 6 — CÁC QUY TẮC CẤU TRÚC JSON (STRUCTURAL RULES)
══════════════════════════════════════════════════════════════════════

1. **CHỈ NỘI DUNG & LAYOUT_TYPE, KHÔNG HÌNH HỌC**: KHÔNG trả `x/y/width/height` — Python tự
   tính tọa độ. Bạn chỉ quyết định: `section`, `slide_title`, `layout_type`, và mỗi card có
   `morph_id`, `title`, `description`, `color_theme`, `order`.
2. **MORPH_ID**: ngắn, chữ thường gạch dưới, không dấu/khoảng trắng (vd
   "hero_card", "orbit_card", "card_1"). GIỮ NGUYÊN morph_id giữa slide N và
   N+1 cho cùng một đối tượng nội dung (để PowerPoint Morph nội suy mượt);
   thẻ mới dùng id mới.
3. **MÀU color_theme** = màu ACCENT tươi, bão hòa (hex 6 ký tự, kèm #):
   - Futuristic: #8B5CF6 (tím), #06B6D4 (cyan), #EC4899 (hồng), #10B981 (ngọc).
   - Minimal:    #6366F1 (indigo), #38BDF8 (sky), #10B981 (ngọc), #C9A227 (vàng đồng).
   - Corporate:  #C9A227 (vàng đồng), #10B981 (ngọc), #3A86FF (xanh), #B08D2E (đồng).
   - Creative:   #EC4899 (hồng), #F59E0B (cam), #06B6D4 (cyan), #8B5CF6 (tím).
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

VÍ DỤ 1 — 2 slide, phối hợp SPLIT_HERO và STAT_GRID, morph_id giữ nguyên:

__EXAMPLE_1__

---
VÍ DỤ 2 — 1 slide dạng tiến trình TIMELINE_STEPS (4 thẻ):

__EXAMPLE_2__

══════════════════════════════════════════════════════════════════════
HÃY BẮT ĐẦU
══════════════════════════════════════════════════════════════════════
Đọc kỹ "=== USER TOPIC TO GENERATE ===", NHẬP VAI chuyên gia đúng lĩnh vực,
chọn layout_type đa dạng giữa các slide theo đúng quy tắc, viết nội dung 100%
bám sát chủ đề bằng từ vựng chuyên ngành thật, theo đúng cấu trúc JSON đã minh hoạ.
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
        f"- Ngôn ngữ nội dung (toàn bộ title/description dùng ngôn ngữ này): {lang}\n"
        f"- Sinh speaker notes: {'Có' if req.include_speaker_notes else 'Không'}\n"
        "- BẮT BUỘC CHỌN layout_type ĐA DẠNG CHO TỪNG SLIDE: SPLIT_HERO (định nghĩa/khái niệm), "
        "STAT_GRID (số liệu/kết quả), TIMELINE_STEPS (quy trình/bước), CARDS_ROW hoặc "
        "GRID_2X2 (liệt kê/ma trận).\n"
        "- ĐIỀU KIỆN BẮT BUỘC: KHÔNG ĐƯỢC để 2 slide liên tiếp có cùng một layout_type.\n\n"
        "NHẮC LẠI TRỰC TIẾP: Trước hết NHẬP VAI chuyên gia đúng lĩnh vực của "
        "chủ đề trên; mọi nội dung (topic, slide_title, title, description) phải "
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
                + "Hãy trả về JSON ĐÃ SỬA: nhập vai chuyên gia đúng lĩnh vực, dùng "
                + "từ vựng chuyên ngành thật, chọn layout_type đa dạng giữa các slide "
                + "(không để 2 slide liên tiếp cùng layout_type), không dùng văn mẫu "
                + "bị cấm, đúng schema, không giải thích."
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
            "%s đã sinh thành công %d slide (topic=%r, lần %d, temp=%.1f)",
            provider, len(result.slides), result.topic[:60], attempt, temperature,
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
            "[AUDIT] Provider '%s' trả topic=%r (user prompt=%r)",
            name, raw_output.topic[:80], req.prompt[:80],
        )
        return presentation

    final_message = _build_failure_message(failures)
    logger.error(
        "TẤT CẢ LLM PROVIDER ĐỀU THẤT BẠI — trả HTTP 502 cho client.\n%s",
        final_message,
    )
    raise LLMGenerationError(final_message)
