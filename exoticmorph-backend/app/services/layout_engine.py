"""
Layout Engine — Narrative Arc Layouts & Adaptive Geometry Calculator
~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~
NHIỆM VỤ: Nhận dữ liệu thô `SlideData` (từ LLM) và tính toán TỰ ĐỘNG toạ độ
(x, y), kích thước (w, h) cho từng thẻ card, badge, kicker, tiêu đề, bước lộ
trình, khung tổng kết và footer — theo các bố cục chuẩn Designer, tổ chức thành
MẠCH KỂ 3 PHẦN (Narrative Arc):

  MỞ BÀI  1. COVER_HERO        : Tiêu đề SIÊU LỚN (44-52pt) lệch trái, lề thoáng,
                                 thanh accent, subtitle nổi bật + hàng badge.
  THÂN    2. BIG_STAT_CALLOUT  : Số liệu/từ khóa KHỔNG LỒ (72pt+) chiếm ~46% bên trái,
                                 văn bản giải thích xếp dọc bên phải.
           3. ASYMMETRIC_GRID  : Lưới bất đối xứng 60% - 40% (thẻ Hero + 2 thẻ phụ dọc).
           4. TIMELINE_STEPS   : Tiến trình 3-4 bước ngang (số thứ tự + đường nối).
           5. CARDS_ROW        : 2-3 thẻ nằm ngang cân đối.
  KẾT     6. CONCLUSION_SUMMARY: 3 dòng card mỏng bo góc (3 điểm cốt lõi)
                                 + thanh Call To Action bên dưới.

QUY TẮC BẮT BUỘC (được Layout Engine TỰ ĐỘNG thực thi, kể cả khi LLM làm sai):
  1. Slide ĐẦU TIÊN luôn là COVER_HERO.
  2. Slide CUỐI CÙNG luôn là CONCLUSION_SUMMARY (khi bài có >= 2 slide).
  3. KHÔNG ĐƯỢC để 2 slide liên tiếp có cùng một `layout_type`.
  4. Bố cục đời cũ (SPLIT_HERO/STAT_GRID/GRID_2X2) tự nâng cấp lên bố cục mới
     tương đương để mạch kể chuyện nhất quán.
"""

import logging
import re
from typing import Any, Dict, List, Tuple, Optional

from app.schemas.slide_schema import (
    BODY_LAYOUTS,
    CLOSING_LAYOUTS,
    ContentCard,
    GenerateRequest,
    LEGACY_LAYOUT_UPGRADE,
    LLMOutput,
    OPENING_LAYOUTS,
    PresentationResponse,
    RawSlideContent,
    Slide,
    SlideData,
    SlideElement,
    StyleType,
    LayoutType,
    _coerce_style_type,
)
from app.services.visual_themes import (
    VisualTheme,
    card_icon_for,
    closing_gradient_css,
    cover_gradient_css,
    kicker_icon_for,
    pattern_decorations,
    resolve_visual_theme,
)

logger = logging.getLogger("exoticmorph.layout")


# ==============================================================================
# HẰNG SỐ CANVAS 16:9 (đơn vị INCHES)
# ==============================================================================
SLIDE_W_IN = 13.333   # Chiều rộng slide 16:9 widescreen
SLIDE_H_IN = 7.5      # Chiều cao slide 16:9

# Lề (margins) — inches
MX_IN = 0.8           # Lề trái / phải (left & right margin)

# --- Vùng tiêu đề (badge + kicker + title) ---
BADGE_TOP_IN = 0.40
BADGE_H_IN   = 0.40
BADGE_W_IN   = 2.30

KICKER_TOP_IN = 0.92
KICKER_H_IN   = 0.28

TITLE_TOP_IN  = 1.26
TITLE_H_IN    = 0.74

# --- Vùng nội dung thẻ chính (cards) ---
CARDS_TOP_IN = 2.48
CARDS_H_IN   = 3.70

# --- Vùng footer (bộ nhận diện cố định) ---
FOOTER_TOP_IN = 6.84
FOOTER_H_IN   = 0.28

# --- Tiến trình / Lộ trình (TIMELINE_STEPS): vòng tròn số thứ tự phía trên thẻ ---
STEP_TOP_IN           = 2.04
STEP_D_IN             = 0.46
TIMELINE_CARDS_TOP_IN = 2.56
TIMELINE_CARDS_H_IN   = 3.25

# Khoảng cách giữa các thẻ (gap) — inches
GAP_IN   = 0.40
GAP_Y_IN = 0.35

# --- Tỉ lệ chia cột bất đối xứng (Asymmetric Grid / Big Stat Callout) ---
HERO_COL_RATIO = 0.60    # ASYMMETRIC_GRID: thẻ Hero chiếm 60% bề ngang
STAT_COL_RATIO = 0.46    # BIG_STAT_CALLOUT: khối số khổng lồ chiếm 46% bề ngang

# ==============================================================================
# HẰNG SỐ BỐ CỤC MỞ BÀI — COVER_HERO (lề thoáng, tiêu đề siêu lớn lệch trái)
# ==============================================================================
COVER_MX_IN        = 1.00   # Lề trái/phải riêng cho slide cover (thoáng hơn thân bài)
COVER_TITLE_W_IN   = 9.80   # Bề ngang khung tiêu đề → chừa khoảng trắng bên phải
COVER_TITLE_TOP_IN = 1.90
COVER_RULE_GAP_IN  = 0.22   # Khe giữa tiêu đề và thanh accent
COVER_RULE_W_IN    = 1.70
COVER_RULE_H_IN    = 0.075
COVER_SUB_GAP_IN   = 0.30   # Khe giữa thanh accent và subtitle
COVER_SUB_W_IN     = 9.20
COVER_SUB_MAX_H_IN = 1.05   # tối đa ~3 dòng subtitle 20pt
COVER_NOTE_GAP_IN  = 0.14   # Khe giữa subtitle và dòng diễn giải phụ
COVER_BADGE_H_IN   = 0.48
COVER_BADGE_GAP_IN = 0.26
COVER_BADGE_GAP_Y_IN = 0.18
COVER_MIN_GAP_IN   = 0.30   # Khoảng trắng tối thiểu giữa khối chữ và hàng badge
COVER_TITLE_MIN_PT = 44
COVER_TITLE_MAX_PT = 52
COVER_SUB_PT       = 20
COVER_NOTE_PT      = 13
COVER_BADGE_PT     = 11
COVER_MAX_TITLE_LINES = 3   # Không để tiêu đề cover tràn quá 3 dòng

# ==============================================================================
# HẰNG SỐ BỐ CỤC KẾT BÀI — CONCLUSION_SUMMARY (3 card mỏng + CTA)
# ==============================================================================
SUM_FRAME_TOP_IN   = 2.42
SUM_FRAME_BOT_IN   = 5.10
SUM_FRAME_PAD_X_IN = 0.42
SUM_FRAME_PAD_Y_IN = 0.00
SUM_ROW_GAP_IN     = 0.16
SUM_ROW_MAX_H_IN   = 0.58  # ↓ từ 0.72: khung cũ luôn kịch trần dù chữ chỉ chiếm ~0.4in,
                           # để lại khoảng trống lớn phía dưới (xem log lỗi "khung to chữ bé").
                           # 0.58in vẫn đủ cho tiêu đề 1 dòng + mô tả 2 dòng ở cỡ chữ hiện tại.
SUM_CTA_TOP_IN     = 5.56
SUM_CTA_H_IN       = 0.80
SUM_ROW_TITLE_PT   = 14
SUM_CTA_PT         = 17


# ==============================================================================
# QUY ĐỔI INCHES → PERCENT (ppt_builder & frontend preview dùng %)
# ==============================================================================
def _inch_to_pct_w(inch: float) -> float:
    """Quy đổi inches → % chiều rộng slide."""
    return (inch / SLIDE_W_IN) * 100.0


def _inch_to_pct_h(inch: float) -> float:
    """Quy đổi inches → % chiều cao slide."""
    return (inch / SLIDE_H_IN) * 100.0


def _pct_w(inch: float) -> float:
    return round(_inch_to_pct_w(inch), 2)


def _pct_h(inch: float) -> float:
    return round(_inch_to_pct_h(inch), 2)


# ==============================================================================
# STYLE PALETTES
# ==============================================================================
STYLE_PALETTES = {
    "Futuristic": {
        "bg":            "#0A0C12",
        "card_fallback": "#141827",
        "card_hero":     "#1A2033",
        "card_border":   "#262C40",
        "text":          "#F6F8FB",
        "sub_text":      "#9AA3B5",
        "badge":         "#7C3AED",
        "badge_text":    "#FFFFFF",
        "accent":        "#10B981",   # ngọc bảo
        "accent2":       "#06B6D4",   # cyan
        "kicker":        "#8B5CF6",   # tím thẫm
        "footer":        "#5B6472",
    },
    "Minimalist": {
        "bg":            "#0E1319",
        "card_fallback": "#182028",
        "card_hero":     "#1E2A33",
        "card_border":   "#2A3542",
        "text":          "#F2F5F7",
        "sub_text":      "#A8B3BE",
        "badge":         "#C9A227",
        "badge_text":    "#14181D",
        "accent":        "#10B981",   # ngọc bảo
        "accent2":       "#C9A227",   # vàng đồng
        "kicker":        "#D4A82E",
        "footer":        "#5E6A76",
    },
    "Corporate": {
        "bg":            "#0A1120",
        "card_fallback": "#121C33",
        "card_hero":     "#16233F",
        "card_border":   "#24325A",
        "text":          "#FFFFFF",
        "sub_text":      "#9FB0C9",
        "badge":         "#B08D2E",
        "badge_text":    "#FFFFFF",
        "accent":        "#10B981",   # ngọc bảo
        "accent2":       "#C9A227",   # vàng đồng
        "kicker":        "#C9A227",
        "footer":        "#5B6A85",
    },
    "CorporateMinimalist": {
        "bg":            "#0B1220",
        "card_fallback": "#111827",
        "card_hero":     "#172033",
        "card_border":   "#2B3548",
        "text":          "#F8FAFC",
        "sub_text":      "#AAB6C8",
        "badge":         "#0F766E",
        "badge_text":    "#FFFFFF",
        "accent":        "#38BDF8",
        "accent2":       "#10B981",
        "kicker":        "#5EEAD4",
        "footer":        "#64748B",
    },
    "Academic": {
        "bg":            "#0D1117",
        "card_fallback": "#151B23",
        "card_hero":     "#1B2430",
        "card_border":   "#303A46",
        "text":          "#F4F7FA",
        "sub_text":      "#A7B3C2",
        "badge":         "#2563EB",
        "badge_text":    "#FFFFFF",
        "accent":        "#38BDF8",
        "accent2":       "#A78BFA",
        "kicker":        "#93C5FD",
        "footer":        "#657386",
    },
    "Creative": {
        "bg":            "#120A1A",
        "card_fallback": "#1F1430",
        "card_hero":     "#281A3C",
        "card_border":   "#3B2159",
        "text":          "#FFFFFF",
        "sub_text":      "#D3C7E2",
        "badge":         "#DB2777",
        "badge_text":    "#FFFFFF",
        "accent":        "#F59E0B",   # hổ phách
        "accent2":       "#06B6D4",   # cyan
        "kicker":        "#EC4899",
        "footer":        "#6A5A82",
    },
}

CARD_ACCENTS = {
    "Futuristic": ["#8B5CF6", "#10B981", "#06B6D4", "#EC4899"],
    "Minimalist": ["#10B981", "#38BDF8", "#C9A227", "#6366F1"],
    "Corporate":  ["#C9A227", "#10B981", "#3A86FF", "#B08D2E"],
    "CorporateMinimalist": ["#38BDF8", "#10B981", "#94A3B8", "#5EEAD4"],
    "Creative":   ["#EC4899", "#F59E0B", "#06B6D4", "#8B5CF6"],
    "Academic":   ["#38BDF8", "#A78BFA", "#60A5FA", "#10B981"],
}


# Alias palette để các payload cũ dùng "Minimal" vẫn render đúng style mới.
STYLE_PALETTES["Minimal"] = STYLE_PALETTES["Minimalist"]
CARD_ACCENTS["Minimal"] = CARD_ACCENTS["Minimalist"]


def _infer_style_from_prompt(prompt: str) -> StyleType:
    """Heuristic an toàn khi request ``AUTO`` nhưng LLM/provider cũ chưa trả style.

    LLM vẫn là nguồn quyết định chính. Hàm này chỉ đảm bảo backend không bao giờ
    trả ``AUTO`` về frontend/PPTX, đồng thời unit test không phụ thuộc provider.
    """
    text = (prompt or "").lower()
    futuristic = (
        "ai", "trí tuệ nhân tạo", "công nghệ", "software", "phần mềm",
        "cloud", "microservice", "kubernetes", "fintech", "vũ trụ",
        "thiên văn", "hệ mặt trời", "mặt trời", "hành tinh", "space", "cosmos",
        "robot", "blockchain", "cyber",
    )
    corporate_min = (
        "y học", "sức khỏe", "bệnh", "lâm sàng", "clinical", "medical",
        "healthcare", "kinh tế", "tài chính", "finance", "báo cáo",
        "doanh thu", "thị trường", "kpi", "roi", "startup", "pitch",
    )
    academic = (
        "nghiên cứu", "học thuật", "đại học", "giáo dục", "đào tạo",
        "luận văn", "thí nghiệm", "research", "academic", "education",
        "history", "lịch sử", "văn hóa",
    )
    creative = (
        "sáng tạo", "marketing", "thương hiệu", "brand", "campaign",
        "nghệ thuật", "art", "design", "âm nhạc", "du lịch", "ẩm thực",
    )

    def has_any(keywords: Tuple[str, ...]) -> bool:
        for kw in keywords:
            if len(kw) <= 2 and kw.isascii():
                if re.search(rf"(?<![\w]){re.escape(kw)}(?![\w])", text):
                    return True
            elif kw in text:
                return True
        return False

    if has_any(futuristic):
        return "Futuristic"
    if has_any(corporate_min):
        return "CorporateMinimalist"
    if has_any(academic):
        return "Academic"
    if has_any(creative):
        return "Creative"
    return "Minimalist"


def _resolve_effective_style(raw: LLMOutput, req: GenerateRequest) -> StyleType:
    """Quyết định style cuối cùng cho layout/PPTX.

    - Nếu client gửi style cụ thể (không phải AUTO), giữ style đó để tương thích API cũ.
    - Nếu client gửi AUTO, ưu tiên top-level ``raw.style`` do LLM trả.
    - Nếu output cũ không có ``style``, fallback heuristic theo prompt để không rò ``AUTO``.
    """
    requested = getattr(req, "style", "AUTO")
    if requested != "AUTO":
        return _coerce_style_type(requested, allow_auto=False)  # type: ignore[return-value]

    fields_set = getattr(raw, "model_fields_set", set())
    if "style" in fields_set and getattr(raw, "style", None):
        return _coerce_style_type(raw.style, allow_auto=False)  # type: ignore[return-value]

    return _infer_style_from_prompt(f"{getattr(req, 'prompt', '')} {getattr(raw, 'topic', '')}")


def _get_palette(style: StyleType) -> dict:
    canonical = _coerce_style_type(style, allow_auto=False)
    return STYLE_PALETTES.get(canonical, STYLE_PALETTES["Futuristic"])


def _get_card_accents(style: StyleType) -> List[str]:
    canonical = _coerce_style_type(style, allow_auto=False)
    return CARD_ACCENTS.get(canonical, CARD_ACCENTS["Futuristic"])


# ==============================================================================
# MẠCH KỂ CHUYỆN (narrative arc)
# ==============================================================================
_ARC_VI = [
    "VẤN ĐỀ", "NGUYÊN NHÂN GỐC RỄ", "GIẢI PHÁP THỰC THI",
    "KẾT QUẢ KỲ VỌNG", "HÀNH ĐỘNG TIẾP THEO",
]
_ARC_EN = [
    "THE PROBLEM", "ROOT CAUSES", "THE SOLUTION",
    "EXPECTED RESULTS", "NEXT STEPS",
]


def _section_for(raw_section: str, index: int, language: str) -> str:
    cleaned = (raw_section or "").strip()
    if cleaned:
        return cleaned[:60]
    vi = (language or "vi").lower().startswith("vi")
    arc = _ARC_VI if vi else _ARC_EN
    if index < len(arc):
        return arc[index]
    n = index - len(arc) + 1
    return f"PHÂN TÍCH CHUYÊN SÂU {n}" if vi else f"DEEP DIVE {n}"


def _title_font_size(title: str) -> int:
    n = len(title or "")
    if n > 110:
        return 16
    if n > 70:
        return 19
    if n > 45:
        return 22
    return 26


# ==============================================================================
# ĐO LƯỜNG CHỮ (TEXT METRICS) — dùng cho COVER_HERO & BIG_STAT_CALLOUT
# ==============================================================================
# Hệ số bề ngang trung bình của 1 ký tự Segoe UI so với cỡ chữ (em ≈ 0.52-0.55).
_AVG_CHAR_EM       = 0.53
_AVG_CHAR_EM_BOLD  = 0.55
_LINE_SPACING      = 1.22


def _estimate_text_lines(text: str, font_pt: float, width_in: float) -> int:
    """Ước lượng số dòng của đoạn chữ khi wrap trong khung rộng ``width_in``.

    Không có engine đo chữ thật trong backend, nên dùng xấp xỉ: bề ngang ký tự
    trung bình ≈ 0.53 × cỡ chữ. Kết quả chỉ dùng để canh chiều cao hộp chữ.
    Từ dài hơn một dòng (URL, mã kỹ thuật, chuỗi số) được tính đủ số dòng nó chiếm.
    """
    text = (text or "").strip()
    if not text or width_in <= 0 or font_pt <= 0:
        return 1
    char_w_in = font_pt * _AVG_CHAR_EM / 72.0
    per_line = max(1, int(width_in / char_w_in))

    lines, current = 1, 0
    for word in text.split():
        # Từ dài hơn cả một dòng → chiếm nhiều dòng liên tiếp.
        if len(word) > per_line:
            if current:
                lines += 1
            word_lines = -(-len(word) // per_line)  # ceil
            lines += word_lines - 1
            current = len(word) % per_line
            continue
        add = len(word) + (1 if current else 0)
        if current + add > per_line and current > 0:
            lines += 1
            current = len(word)
        else:
            current += add
    return max(1, lines)


def _cover_title_font_size(title: str) -> int:
    """Cỡ chữ tiêu đề slide MỞ BÀI — luôn nằm trong khoảng 44-52pt."""
    n = len((title or "").strip())
    if n <= 34:
        return COVER_TITLE_MAX_PT          # 52pt — tiêu đề ngắn, cực kỳ ấn tượng
    if n <= 52:
        return 50
    if n <= 72:
        return 48
    if n <= 96:
        return 46
    return COVER_TITLE_MIN_PT              # 44pt — sàn, không bao giờ nhỏ hơn


def _stat_number_font_size(value: str, box_w_in: float = 0.0) -> int:
    """Cỡ chữ con số/từ khóa chính của BIG_STAT_CALLOUT.

    Thiết kế mới ưu tiên một dòng ổn định (vd ``99.86%`` KHÔNG rớt dòng) thay vì
    phóng số quá lớn. Cỡ chữ trần 64pt, tự hạ dần theo độ dài chuỗi và bề ngang
    hộp; PPTX builder đặt ``word_wrap=False`` + auto-fit cho phần số chính.
    """
    text = (value or "").strip()
    n = len(text)
    if n == 0:
        return 64

    if n <= 7:
        target = 64
    elif n <= 12:
        target = 60
    elif n <= 18:
        target = 56
    else:
        target = 48

    inner_w = max(0.5, (box_w_in if box_w_in > 0 else 5.2) - 0.44)
    max_by_width = int(inner_w * 72.0 / max(1.0, n * _AVG_CHAR_EM_BOLD))
    return max(40, min(target, max_by_width if box_w_in > 0 else target))


def _chip_width_in(label: str) -> float:
    """Bề ngang viên badge (pill) ôm sát chữ, có padding trái/phải."""
    label = (label or "").strip()
    text_w = len(label) * COVER_BADGE_PT * _AVG_CHAR_EM_BOLD / 72.0
    return round(max(1.35, min(3.10, text_w + 0.52)), 3)


def _normalize_hex(hex_str: Optional[str], fallback: str) -> str:
    value = (hex_str or "").strip()
    if not value:
        return fallback
    if not value.startswith("#"):
        value = f"#{value}"
    if len(value) != 7:
        return fallback
    return value


# ==============================================================================
# TOÁN HỌC HÌNH HỌC CHO 5 KIỂU BỐ CỤC (GEOMETRY CALCULATOR)
# ==============================================================================

def _calculate_cards_geometry_inches(
    layout: LayoutType, n: int
) -> List[Tuple[float, float, float, float]]:
    """Tính danh sách (x_in, y_in, w_in, h_in) cho n thẻ theo layout_type.

    Toàn bộ tọa độ được tính bằng Inches trên canvas 16:9 (13.333 x 7.5 inches),
    đảm bảo padding và margin hài hòa, không chồng lấn nội dung hay footer.

    Các nhánh SPLIT_HERO / STAT_GRID / GRID_2X2 ở cuối hàm là BỐ CỤC ĐỜI CŨ,
    được giữ lại để tương thích ngược (bài cũ hoặc lời gọi trực tiếp); luồng
    `compute_layout()` không bao giờ đi vào đó vì `_resolve_slide_layouts()` đã
    nâng cấp chúng lên bố cục mới tương đương.
    """
    usable_w = SLIDE_W_IN - 2 * MX_IN

    # --------------------------------------------------------------------------
    # 0a. COVER_HERO (MỞ BÀI): hàng badge nằm dưới khối tiêu đề — lề thoáng 1.0"
    # --------------------------------------------------------------------------
    if layout == LayoutType.COVER_HERO:
        return _cover_badges_geometry(max(n, 0))

    # --------------------------------------------------------------------------
    # 0b. BIG_STAT_CALLOUT: khối số khổng lồ bên trái, văn bản giải thích bên phải
    # --------------------------------------------------------------------------
    if layout == LayoutType.BIG_STAT_CALLOUT:
        if n <= 1:
            w_in = round(usable_w * 0.62, 3)
            x_in = round(MX_IN + (usable_w - w_in) / 2, 3)
            return [(x_in, CARDS_TOP_IN, w_in, CARDS_H_IN)]
        w_stat = round((usable_w - GAP_IN) * STAT_COL_RATIO, 3)
        w_text = round((usable_w - GAP_IN) - w_stat, 3)
        k = n - 1
        gap_y = GAP_Y_IN if k <= 3 else 0.20
        h_row = round((CARDS_H_IN - (k - 1) * gap_y) / k, 3)
        res = [(MX_IN, CARDS_TOP_IN, w_stat, CARDS_H_IN)]
        for j in range(k):
            y_j = round(CARDS_TOP_IN + j * (h_row + gap_y), 3)
            res.append((round(MX_IN + w_stat + GAP_IN, 3), y_j, w_text, h_row))
        return res

    # --------------------------------------------------------------------------
    # 0c. ASYMMETRIC_GRID: lưới bất đối xứng 60% (Hero) - 40% (thẻ phụ xếp dọc)
    # --------------------------------------------------------------------------
    if layout == LayoutType.ASYMMETRIC_GRID:
        w_hero = round((usable_w - GAP_IN) * HERO_COL_RATIO, 3)
        w_side = round((usable_w - GAP_IN) - w_hero, 3)
        x_side = round(MX_IN + w_hero + GAP_IN, 3)
        if n <= 1:
            return [(MX_IN, CARDS_TOP_IN, w_hero, CARDS_H_IN)]
        if n == 2:
            return [
                (MX_IN, CARDS_TOP_IN, w_hero, CARDS_H_IN),
                (x_side, CARDS_TOP_IN, w_side, CARDS_H_IN),
            ]
        k = n - 1
        gap_y = GAP_Y_IN if k <= 3 else 0.20
        h_row = round((CARDS_H_IN - (k - 1) * gap_y) / k, 3)
        res = [(MX_IN, CARDS_TOP_IN, w_hero, CARDS_H_IN)]
        for j in range(k):
            y_j = round(CARDS_TOP_IN + j * (h_row + gap_y), 3)
            res.append((x_side, y_j, w_side, h_row))
        return res

    # --------------------------------------------------------------------------
    # 0d. CONCLUSION_SUMMARY (KẾT BÀI): 3 dòng card mỏng, không frame lồng
    # --------------------------------------------------------------------------
    if layout == LayoutType.CONCLUSION_SUMMARY:
        return _conclusion_rows_geometry(max(n, 0))

    if n <= 1:
        w_in = min(usable_w, 9.6)
        x_in = MX_IN + (usable_w - w_in) / 2
        return [(x_in, CARDS_TOP_IN, w_in, CARDS_H_IN)]

    # --------------------------------------------------------------------------
    # 1. SPLIT_HERO: Cột trái rộng (Hero Card), cột phải xếp 2 thẻ phụ
    # --------------------------------------------------------------------------
    if layout == LayoutType.SPLIT_HERO:
        if n == 2:
            w_left = round((usable_w - GAP_IN) * 0.60, 3)
            w_right = round((usable_w - GAP_IN) - w_left, 3)
            return [
                (MX_IN, CARDS_TOP_IN, w_left, CARDS_H_IN),
                (round(MX_IN + w_left + GAP_IN, 3), CARDS_TOP_IN, w_right, CARDS_H_IN),
            ]
        # n >= 3: Cột trái Hero chiếm ~58% bề ngang; cột phải xếp k thẻ phụ theo chiều dọc
        w_left = round((usable_w - GAP_IN) * 0.58, 3)
        w_right = round((usable_w - GAP_IN) - w_left, 3)
        k = n - 1
        h_right = round((CARDS_H_IN - (k - 1) * GAP_Y_IN) / k, 3)
        res = [(MX_IN, CARDS_TOP_IN, w_left, CARDS_H_IN)]
        for j in range(k):
            y_j = round(CARDS_TOP_IN + j * (h_right + GAP_Y_IN), 3)
            res.append((round(MX_IN + w_left + GAP_IN, 3), y_j, w_right, h_right))
        return res

    # --------------------------------------------------------------------------
    # 2. GRID_2X2: Lưới 4 thẻ chia đều 2 hàng x 2 cột
    # --------------------------------------------------------------------------
    if layout == LayoutType.GRID_2X2:
        w_col = round((usable_w - GAP_IN) / 2, 3)
        h_row = round((CARDS_H_IN - GAP_Y_IN) / 2, 3)
        if n == 2:
            return [
                (MX_IN, CARDS_TOP_IN, w_col, CARDS_H_IN),
                (round(MX_IN + w_col + GAP_IN, 3), CARDS_TOP_IN, w_col, CARDS_H_IN),
            ]
        if n == 3:
            # Hàng trên 2 thẻ, hàng dưới 1 thẻ căn giữa
            x_bot = round(MX_IN + (usable_w - w_col) / 2, 3)
            return [
                (MX_IN, CARDS_TOP_IN, w_col, h_row),
                (round(MX_IN + w_col + GAP_IN, 3), CARDS_TOP_IN, w_col, h_row),
                (x_bot, round(CARDS_TOP_IN + h_row + GAP_Y_IN, 3), w_col, h_row),
            ]
        if n == 4:
            return [
                (MX_IN, CARDS_TOP_IN, w_col, h_row),
                (round(MX_IN + w_col + GAP_IN, 3), CARDS_TOP_IN, w_col, h_row),
                (MX_IN, round(CARDS_TOP_IN + h_row + GAP_Y_IN, 3), w_col, h_row),
                (round(MX_IN + w_col + GAP_IN, 3), round(CARDS_TOP_IN + h_row + GAP_Y_IN, 3), w_col, h_row),
            ]
        # n > 4: tổng quát 2 hàng cân đối
        top_n = (n + 1) // 2
        bot_n = n - top_n
        w_top = round((usable_w - (top_n - 1) * GAP_IN) / top_n, 3)
        w_bot = round((usable_w - (bot_n - 1) * GAP_IN) / bot_n, 3)
        res = []
        for i in range(top_n):
            res.append((round(MX_IN + i * (w_top + GAP_IN), 3), CARDS_TOP_IN, w_top, h_row))
        for j in range(bot_n):
            res.append((round(MX_IN + j * (w_bot + GAP_IN), 3), round(CARDS_TOP_IN + h_row + GAP_Y_IN, 3), w_bot, h_row))
        return res

    # --------------------------------------------------------------------------
    # 3. TIMELINE_STEPS: Tiến trình 3-4 bước theo chiều ngang
    # --------------------------------------------------------------------------
    if layout == LayoutType.TIMELINE_STEPS:
        w_in = round((usable_w - (n - 1) * GAP_IN) / n, 3)
        return [
            (round(MX_IN + i * (w_in + GAP_IN), 3), TIMELINE_CARDS_TOP_IN, w_in, TIMELINE_CARDS_H_IN)
            for i in range(n)
        ]

    # --------------------------------------------------------------------------
    # 4. STAT_GRID: Slide nhấn mạnh số liệu (con số to nổi bật + label ngắn)
    # --------------------------------------------------------------------------
    if layout == LayoutType.STAT_GRID:
        if n <= 4:
            w_in = round((usable_w - (n - 1) * GAP_IN) / n, 3)
            return [
                (round(MX_IN + i * (w_in + GAP_IN), 3), CARDS_TOP_IN, w_in, CARDS_H_IN)
                for i in range(n)
            ]
        # n > 4: lưới 2 hàng cho nhiều số liệu
        h_row = round((CARDS_H_IN - GAP_Y_IN) / 2, 3)
        top_n = (n + 1) // 2
        bot_n = n - top_n
        w_top = round((usable_w - (top_n - 1) * GAP_IN) / top_n, 3)
        w_bot = round((usable_w - (bot_n - 1) * GAP_IN) / bot_n, 3)
        res = []
        for i in range(top_n):
            res.append((round(MX_IN + i * (w_top + GAP_IN), 3), CARDS_TOP_IN, w_top, h_row))
        for j in range(bot_n):
            res.append((round(MX_IN + j * (w_bot + GAP_IN), 3), round(CARDS_TOP_IN + h_row + GAP_Y_IN, 3), w_bot, h_row))
        return res

    # --------------------------------------------------------------------------
    # 5. CARDS_ROW (Mặc định): 2-3 thẻ nằm ngang cân đối
    # --------------------------------------------------------------------------
    w_in = round((usable_w - (n - 1) * GAP_IN) / n, 3)
    return [
        (round(MX_IN + i * (w_in + GAP_IN), 3), CARDS_TOP_IN, w_in, CARDS_H_IN)
        for i in range(n)
    ]


# ==============================================================================
# HÌNH HỌC RIÊNG CHO MẠCH KỂ: COVER_HERO (mở bài) & CONCLUSION_SUMMARY (kết bài)
# ==============================================================================

# Vị trí hàng badge mặc định khi không có ngữ cảnh tiêu đề (dùng cho fallback/test).
COVER_DEFAULT_BADGES_TOP_IN = 5.30


def _cover_badges_geometry(
    num_badges: int,
    labels: Optional[List[str]] = None,
    top_in: Optional[float] = None,
) -> List[Tuple[float, float, float, float]]:
    """Xếp các viên badge (pill) của slide cover thành 1-2 hàng, ôm sát chữ.

    Trả về danh sách (x, y, w, h) theo inches, tự xuống dòng khi tràn bề ngang.
    """
    if num_badges <= 0:
        return []

    usable_w = SLIDE_W_IN - 2 * COVER_MX_IN
    top = COVER_DEFAULT_BADGES_TOP_IN if top_in is None else top_in

    widths: List[float] = []
    for i in range(min(num_badges, 4)):
        label = labels[i] if labels and i < len(labels) else None
        widths.append(_chip_width_in(label) if label else 2.20)

    coords: List[Tuple[float, float, float, float]] = []
    x = COVER_MX_IN
    y = top
    for w in widths:
        if coords and (x - COVER_MX_IN) + w > usable_w + 1e-6:
            x = COVER_MX_IN
            y = round(y + COVER_BADGE_H_IN + COVER_BADGE_GAP_Y_IN, 3)
        coords.append((round(x, 3), round(y, 3), w, COVER_BADGE_H_IN))
        x = round(x + w + COVER_BADGE_GAP_IN, 3)
    return coords


def _cover_geometry(
    title: str,
    subtitle: str = "",
    note: str = "",
    badge_labels: Optional[List[str]] = None,
) -> Dict[str, Any]:
    """Toán học tọa độ slide MỞ BÀI (COVER_HERO).

    Khối chữ xếp từ trên xuống, lề trái/phải thoáng 1.0":
        tiêu đề siêu lớn (44-52pt, tối đa 3 dòng)
        → thanh accent ngắn
        → subtitle nổi bật (20pt, tối đa 3 dòng)
        → hàng badge  ·  hoặc  ·  dòng diễn giải phụ (khi slide chỉ có 1 thẻ)

    Mọi phần tử đều được kiểm tra để KHÔNG tràn xuống vùng footer.
    """
    usable_w = SLIDE_W_IN - 2 * COVER_MX_IN
    bottom_limit = FOOTER_TOP_IN - 0.15

    # 1) Tiêu đề siêu lớn, lệch trái, tối đa 3 dòng
    title_font = _cover_title_font_size(title)
    title_w = round(min(COVER_TITLE_W_IN, usable_w), 3)
    title_lines = min(_estimate_text_lines(title, title_font, title_w), COVER_MAX_TITLE_LINES)
    title_h = round(title_lines * title_font * _LINE_SPACING / 72.0, 3)
    title_box = (COVER_MX_IN, COVER_TITLE_TOP_IN, title_w, title_h)

    # 2) Thanh accent ngắn dưới tiêu đề (điểm nhấn thị giác)
    rule_y = round(COVER_TITLE_TOP_IN + title_h + COVER_RULE_GAP_IN, 3)
    rule_box = (COVER_MX_IN, rule_y, COVER_RULE_W_IN, COVER_RULE_H_IN)

    # 3) Subtitle nổi bật (câu hook / vấn đề dẫn dắt)
    cursor = round(rule_y + COVER_RULE_H_IN + COVER_SUB_GAP_IN, 3)
    subtitle_box: Optional[Tuple[float, float, float, float]] = None
    if (subtitle or "").strip():
        sub_lines = min(_estimate_text_lines(subtitle, COVER_SUB_PT, COVER_SUB_W_IN), 3)
        sub_h = round(
            min(max(sub_lines * COVER_SUB_PT * _LINE_SPACING / 72.0, 0.34), COVER_SUB_MAX_H_IN),
            3,
        )
        subtitle_box = (COVER_MX_IN, cursor, round(min(COVER_SUB_W_IN, usable_w), 3), sub_h)
        cursor = round(cursor + sub_h + COVER_NOTE_GAP_IN, 3)

    # 4) Badge (khi có >= 2 thẻ) HOẶC dòng diễn giải phụ (khi chỉ có 1 thẻ)
    labels = [b for b in (badge_labels or []) if (b or "").strip()][:4]
    badges: List[Tuple[float, float, float, float]] = []
    note_box: Optional[Tuple[float, float, float, float]] = None

    if labels:
        # Xếp badge vừa khít khoảng trống còn lại: thử đủ 4 nhãn → 2 nhãn → 1 nhãn
        # → bỏ hẳn, để KHÔNG BAO GIỜ tràn xuống vùng footer.
        badges_top = round(cursor + COVER_MIN_GAP_IN, 3)
        for candidate in (labels, labels[:2], labels[:1], []):
            if not candidate:
                break
            rows = len({round(c[1], 3) for c in _cover_badges_geometry(len(candidate), candidate, top_in=0.0)})
            block_h = round(rows * COVER_BADGE_H_IN + (rows - 1) * COVER_BADGE_GAP_Y_IN, 3)
            if badges_top + block_h <= bottom_limit:
                badges = _cover_badges_geometry(len(candidate), candidate, top_in=badges_top)
                break

    # Không còn chỗ cho badge (hoặc slide chỉ có 1 thẻ) → dùng dòng diễn giải phụ.
    if not badges and (note or "").strip():
        note_w = round(min(COVER_SUB_W_IN, usable_w), 3)
        note_lines = min(_estimate_text_lines(note, COVER_NOTE_PT, note_w), 2)
        note_h = round(note_lines * COVER_NOTE_PT * _LINE_SPACING / 72.0, 3)
        if cursor + note_h <= bottom_limit:
            note_box = (COVER_MX_IN, cursor, note_w, note_h)
            cursor = round(cursor + note_h, 3)

    badges_top = badges[0][1] if badges else cursor
    return {
        "title_font": title_font,
        "title": title_box,
        "rule": rule_box,
        "subtitle": subtitle_box,
        "note": note_box,
        "badges": badges,
        "badges_top": badges_top,
    }


def _conclusion_frame_geometry() -> Tuple[float, float, float, float]:
    """Vùng logic chứa 3 dòng tổng kết (KHÔNG còn vẽ frame lồng bên ngoài)."""
    usable_w = SLIDE_W_IN - 2 * MX_IN
    return (MX_IN, SUM_FRAME_TOP_IN, round(usable_w, 3), round(SUM_FRAME_BOT_IN - SUM_FRAME_TOP_IN, 3))


def _conclusion_rows_geometry(n: int) -> List[Tuple[float, float, float, float]]:
    """3 dòng card mỏng xếp dọc, không bọc trong khung viền kép."""
    rows = min(max(n, 0), 3)
    if rows <= 0:
        return []

    frame_x, frame_y, frame_w, frame_h = _conclusion_frame_geometry()
    row_w = round(min(frame_w - 2 * SUM_FRAME_PAD_X_IN, 10.90), 3)
    x0 = round(frame_x + (frame_w - row_w) / 2, 3)
    h = min(SUM_ROW_MAX_H_IN, (frame_h - (rows - 1) * SUM_ROW_GAP_IN) / rows)
    stack_h = rows * h + (rows - 1) * SUM_ROW_GAP_IN
    y0 = round(frame_y + (frame_h - stack_h) / 2, 3)

    return [
        (x0, round(y0 + i * (h + SUM_ROW_GAP_IN), 3), row_w, round(h, 3))
        for i in range(rows)
    ]


def _conclusion_cta_geometry() -> Tuple[float, float, float, float]:
    """Thanh Call To Action nổi bật, thấp gọn (~0.8 inch) và căn giữa."""
    usable_w = SLIDE_W_IN - 2 * MX_IN
    cta_w = round(min(usable_w, 10.40), 3)
    x = round(MX_IN + (usable_w - cta_w) / 2, 3)
    return (x, SUM_CTA_TOP_IN, cta_w, SUM_CTA_H_IN)


def _card_title_font_size(
    num_cards: int,
    layout: LayoutType,
    card_index: int = 0,
    content: str = "",
    box_w_in: float = 0.0,
) -> int:
    """Cỡ chữ tiêu đề thẻ điều chỉnh tối ưu cho từng kiểu bố cục."""
    if layout == LayoutType.BIG_STAT_CALLOUT:
        # Thẻ 0 = con số/từ khóa khổng lồ; các thẻ còn lại = văn bản giải thích.
        if card_index == 0:
            return _stat_number_font_size(content, box_w_in)
        return 16
    if layout == LayoutType.ASYMMETRIC_GRID:
        return 26 if card_index == 0 else 14
    if layout == LayoutType.CONCLUSION_SUMMARY:
        return SUM_ROW_TITLE_PT
    if layout == LayoutType.COVER_HERO:
        return COVER_BADGE_PT
    if layout == LayoutType.STAT_GRID:
        if num_cards <= 2:
            return 36
        if num_cards == 3:
            return 32
        if num_cards == 4:
            return 28
        return 24
    if layout == LayoutType.SPLIT_HERO:
        if card_index == 0:
            return 22  # Thẻ Hero chính bên trái: lớn, nổi bật
        return 14      # Thẻ phụ xếp bên phải
    if layout == LayoutType.GRID_2X2:
        return 15
    if layout == LayoutType.TIMELINE_STEPS:
        return 14 if num_cards >= 4 else 16
    # CARDS_ROW
    if num_cards <= 1:
        return 24
    if num_cards == 2:
        return 18
    if num_cards == 3:
        return 15
    return 13


# ==============================================================================
# BUILD ELEMENTS: BADGE, KICKER, TITLE, CARDS, STEPS, FOOTER
# ==============================================================================

def _build_badge_element(slide_idx: int, palette: dict) -> SlideElement:
    """Badge (pill tag) ở góc trên-trái — morph_id cố định xuyên suốt để Morph."""
    return SlideElement(
        id=f"badge_slide_{slide_idx}",
        type="badge",
        content=f"SLIDE {slide_idx:02d}",
        x=_pct_w(MX_IN),
        y=_pct_h(BADGE_TOP_IN),
        width=_pct_w(BADGE_W_IN),
        height=_pct_h(BADGE_H_IN),
        bg_color=palette["badge"],
        text_color=palette["badge_text"],
        morph_id="badge_header",
        font_size=11,
        shape_type="rounded_rectangle",
    )


def _build_kicker_element(
    slide_idx: int,
    section: str,
    palette: dict,
    theme: Optional[VisualTheme] = None,
) -> SlideElement:
    """Nhãn mục (kicker) in hoa ngay trên tiêu đề — thể hiện vị trí trong mạch kể chuyện.

    Khi có visual theme, kicker được mở đầu bằng 1 icon/motif thuộc ngữ cảnh chủ
    đề (🪐 📈 ⚕ ...) xoay vòng theo slide — điểm nhấn thị giác thay vì text thuần.
    """
    icon = f"{kicker_icon_for(theme, slide_idx)}  " if theme else ""
    return SlideElement(
        id=f"kicker_slide_{slide_idx}",
        type="kicker",
        content=f"{icon}{(section or '').upper()}",
        x=_pct_w(MX_IN),
        y=_pct_h(KICKER_TOP_IN),
        width=_pct_w(SLIDE_W_IN - 2 * MX_IN),
        height=_pct_h(KICKER_H_IN),
        bg_color=None,
        text_color=palette["kicker"],
        morph_id="section_kicker",
        font_size=12,
    )


def _build_title_element(
    slide_idx: int,
    slide_title: str,
    palette: dict,
    box_in: Optional[Tuple[float, float, float, float]] = None,
    font_size: Optional[int] = None,
    align: Optional[str] = None,
) -> SlideElement:
    """Tiêu đề chính của slide — một thông điệp cụ thể, in đậm, cỡ lớn.

    ``box_in``/``font_size`` cho phép ghi đè hình học (dùng bởi COVER_HERO với
    tiêu đề siêu lớn 44-52pt), mặc định vẫn là vùng header chuẩn của thân bài.
    """
    x, y, w, h = box_in or (MX_IN, TITLE_TOP_IN, SLIDE_W_IN - 2 * MX_IN, TITLE_H_IN)
    return SlideElement(
        id=f"title_slide_{slide_idx}",
        type="heading",
        content=slide_title,
        x=_pct_w(x),
        y=_pct_h(y),
        width=_pct_w(w),
        height=_pct_h(h),
        bg_color=None,
        text_color=palette["text"],
        morph_id="title_slide",
        font_size=font_size or _title_font_size(slide_title),
        align=align,
    )


def _build_text_element(
    elem_id: str,
    morph_id: str,
    content: str,
    box_in: Tuple[float, float, float, float],
    palette: dict,
    font_size: int,
    text_color: Optional[str] = None,
) -> SlideElement:
    """Khối chữ trơn (không nền, không viền) — dùng cho subtitle/diễn giải của cover."""
    x, y, w, h = box_in
    return SlideElement(
        id=elem_id,
        type="heading",
        content=content,
        x=_pct_w(x),
        y=_pct_h(y),
        width=_pct_w(w),
        height=_pct_h(h),
        bg_color=None,
        text_color=text_color or palette["text"],
        morph_id=morph_id,
        font_size=font_size,
    )


def _build_cover_elements(
    slide_idx: int,
    slide_title: str,
    section: str,
    geo: Dict[str, Any],
    subtitle_text: str,
    note_text: str,
    badge_cards: List[ContentCard],
    palette: dict,
    accents: List[str],
    theme: Optional[VisualTheme] = None,
) -> List[SlideElement]:
    """Dựng toàn bộ phần tử slide MỞ BÀI (COVER_HERO).

    Gồm: badge slide, kicker (eyebrow) kèm icon motif chủ đề, tiêu đề siêu lớn,
    thanh accent, subtitle nổi bật (hoặc dòng diễn giải phụ) và hàng badge ôm
    sát chữ.
    """
    elements: List[SlideElement] = []

    # Badge slide — canh theo lề thoáng riêng của cover để thẳng hàng khối chữ.
    elements.append(SlideElement(
        id=f"badge_slide_{slide_idx}",
        type="badge",
        content=f"SLIDE {slide_idx:02d}",
        x=_pct_w(COVER_MX_IN),
        y=_pct_h(BADGE_TOP_IN),
        width=_pct_w(BADGE_W_IN),
        height=_pct_h(BADGE_H_IN),
        bg_color=palette["badge"],
        text_color=palette["badge_text"],
        morph_id="badge_header",
        font_size=11,
        shape_type="rounded_rectangle",
    ))

    # Kicker (eyebrow) đặt sát ngay trên tiêu đề siêu lớn — mở đầu bằng icon motif.
    cover_icon = f"{kicker_icon_for(theme, slide_idx)}  " if theme else ""
    elements.append(SlideElement(
        id=f"kicker_slide_{slide_idx}",
        type="kicker",
        content=f"{cover_icon}{(section or '').upper()}",
        x=_pct_w(COVER_MX_IN),
        y=_pct_h(COVER_TITLE_TOP_IN - 0.52),
        width=_pct_w(SLIDE_W_IN - 2 * COVER_MX_IN),
        height=_pct_h(KICKER_H_IN),
        bg_color=None,
        text_color=palette["kicker"],
        morph_id="section_kicker",
        font_size=13,
    ))

    # Tiêu đề siêu lớn (44-52pt) + thanh accent.
    elements.append(_build_title_element(
        slide_idx, slide_title, palette,
        box_in=geo["title"], font_size=geo["title_font"],
    ))
    rx, ry, rw, rh = geo["rule"]
    elements.append(SlideElement(
        id=f"title_rule_{slide_idx}",
        type="accent",
        content="",
        x=_pct_w(rx),
        y=_pct_h(ry),
        width=_pct_w(rw),
        height=_pct_h(rh),
        bg_color=accents[0],
        text_color=None,
        morph_id="title_rule",
        shape_type="rectangle",
    ))

    # Subtitle nổi bật (câu hook) — hoặc dòng diễn giải phụ khi không có badge.
    if geo["subtitle"]:
        elements.append(_build_text_element(
            f"cover_subtitle_{slide_idx}", "cover_subtitle",
            subtitle_text, geo["subtitle"], palette, COVER_SUB_PT,
            text_color=palette["accent"],
        ))
    if geo["note"]:
        elements.append(_build_text_element(
            f"cover_note_{slide_idx}", "cover_note",
            note_text, geo["note"], palette, COVER_NOTE_PT,
            text_color=palette["sub_text"],
        ))

    # Hàng badge (pill) — mỗi badge là một thẻ ngắn do LLM sinh ra.
    for i, (card, box) in enumerate(zip(badge_cards, geo["badges"])):
        bx, by, bw, bh = box
        elements.append(SlideElement(
            id=f"slide{slide_idx}_cover_badge{i}_{card.morph_id}",
            type="badge",
            content=card.title.strip(),
            x=_pct_w(bx),
            y=_pct_h(by),
            width=_pct_w(bw),
            height=_pct_h(bh),
            bg_color=_normalize_hex(card.color_theme, accents[i % len(accents)]),
            text_color="#FFFFFF",
            morph_id=card.morph_id,
            font_size=COVER_BADGE_PT,
            shape_type="rounded_rectangle",
        ))

    return elements


def _build_conclusion_elements(
    slide_idx: int,
    num_rows: int,
    row_cards: List[ContentCard],
    cta_text: str,
    cta_card: Optional[ContentCard],
    palette: dict,
    accents: List[str],
) -> List[SlideElement]:
    """Dựng phần tử slide KẾT BÀI (CONCLUSION_SUMMARY).

    Gồm: 3 dòng card mỏng độc lập (không còn frame lồng viền kép) và thanh
    Call To Action nổi bật ngay bên dưới.
    """
    elements: List[SlideElement] = []

    # 1) Các dòng điểm cốt lõi — card mỏng dạng list-rows với VIỀN TRÁI DÀY
    #    (biến thể accent_left) thay vì thanh màu trên đỉnh, tạo nhịp dọc riêng
    #    cho slide kết bài.
    row_coords = _conclusion_rows_geometry(num_rows)
    for i, (card, box) in enumerate(zip(row_cards, row_coords)):
        x, y, w, h = box
        elements.append(SlideElement(
            id=f"slide{slide_idx}_takeaway{i}_{card.morph_id}",
            type="card",
            content=card.title,
            label="",
            sub_text=card.description,
            x=_pct_w(x),
            y=_pct_h(y),
            width=_pct_w(w),
            height=_pct_h(h),
            bg_color=palette["card_fallback"],
            text_color=palette["text"],
            accent_color=_normalize_hex(card.color_theme, accents[i % len(accents)]),
            morph_id=card.morph_id,
            font_size=SUM_ROW_TITLE_PT,
            shape_type="rounded_rectangle",
            border_color=palette["card_border"],
            step=i + 1,
            variant="accent_left",
        ))

    # 2) Thanh Call To Action.
    if cta_text:
        cx, cy, cw, ch = _conclusion_cta_geometry()
        cta_accent = _normalize_hex(
            cta_card.color_theme if cta_card else None, accents[-1]
        )
        elements.append(SlideElement(
            id=f"slide{slide_idx}_cta",
            type="card",
            content=cta_text,
            label="",
            sub_text=None,
            x=_pct_w(cx),
            y=_pct_h(cy),
            width=_pct_w(cw),
            height=_pct_h(ch),
            bg_color=cta_accent,
            text_color="#0B0E14",
            accent_color=cta_accent,
            morph_id="call_to_action",
            font_size=SUM_CTA_PT,
            shape_type="rounded_rectangle",
            align="center",
            variant="cta",
        ))

    return elements


def _card_variant_for(layout: LayoutType, card_index: int, num_cards: int) -> Tuple[str, bool]:
    """Chọn biến thể thị giác + có icon cho card theo vai trò trong bố cục.

    Phá khuôn "mọi card đều thanh màu mỏng phía trên":
      - thẻ Hero/chính giữ ``accent_top`` (thanh màu đỉnh — điểm neo thị giác),
      - thẻ phụ dạng dòng/cột dùng ``accent_left`` (viền trái dày),
      - thẻ phụ "nhẹ" (timeline, cột bên asymmetric) dùng ``outline`` (không nền,
        viền mỏng + icon) → phân cấp chính/phụ rõ ràng thay vì đồng trọng lượng.
    Trả về (variant, use_icon).
    """
    if layout == LayoutType.BIG_STAT_CALLOUT:
        if card_index == 0:
            return "accent_top", True   # số khổng lồ: icon xu hướng ở góc
        return "accent_left", True
    if layout in (LayoutType.ASYMMETRIC_GRID, LayoutType.SPLIT_HERO):
        if card_index == 0:
            return "accent_top", False
        return "outline", True
    if layout == LayoutType.TIMELINE_STEPS:
        return "outline", True          # bước quy trình: card rỗng + icon, số thứ tự ở vòng tròn phía trên
    if layout == LayoutType.CONCLUSION_SUMMARY:
        return "accent_left", False     # list-rows: viền trái dày tạo nhịp dọc
    # CARDS_ROW và các layout khác
    if card_index == 0 or num_cards <= 1:
        return "accent_top", False
    return "accent_left", True


def _build_card_element(
    card: ContentCard,
    card_index: int,
    num_cards: int,
    slide_idx: int,
    layout: LayoutType,
    palette: dict,
    accents: List[str],
    coords_pct: Tuple[float, float, float, float],
    theme: Optional[VisualTheme] = None,
) -> SlideElement:
    """Một thẻ card với hình học theo layout_type, kèm màu accent riêng.

    Biến thể thị giác (``variant``) và icon motif (``icon``) tạo nhịp khác nhau
    cho từng vai trò card — xem `_card_variant_for`.
    """
    x, y, w, h = coords_pct
    accent = _normalize_hex(card.color_theme, accents[card_index % len(accents)])

    is_hero = card_index == 0 and layout in (
        LayoutType.SPLIT_HERO,
        LayoutType.ASYMMETRIC_GRID,
        LayoutType.BIG_STAT_CALLOUT,
    )
    bg = palette["card_hero"] if (is_hero or (layout == LayoutType.CARDS_ROW and card_index == 0)) else palette["card_fallback"]

    fs_title = _card_title_font_size(
        num_cards, layout, card_index, card.title,
        box_w_in=(w / 100.0) * SLIDE_W_IN,
    )

    variant, use_icon = _card_variant_for(layout, card_index, num_cards)
    icon: Optional[str] = None
    if use_icon and theme:
        if layout == LayoutType.BIG_STAT_CALLOUT and card_index == 0:
            icon = theme.stat_icon      # icon xu hướng/đơn vị cho con số khổng lồ
        elif layout == LayoutType.BIG_STAT_CALLOUT:
            # lệch +1 để thẻ giải thích không trùng icon với con số khổng lồ
            icon = card_icon_for(theme, card_index + 1)
        else:
            icon = card_icon_for(theme, card_index)

    return SlideElement(
        id=f"slide{slide_idx}_card{card_index}_{card.morph_id}",
        type="card",
        content=card.title,
        label="",
        sub_text=card.description,
        x=x,
        y=y,
        width=w,
        height=h,
        bg_color=bg,
        text_color=palette["text"],
        accent_color=accent,
        morph_id=card.morph_id,
        font_size=fs_title,
        shape_type="rounded_rectangle",
        border_color=palette["card_border"],
        step=(card_index + 1 if layout == LayoutType.TIMELINE_STEPS else None),
        variant=variant,
        icon=icon,
    )


def _build_decoration_elements(
    theme: VisualTheme,
    slide_number: int,
    palette: dict,
    accents: List[str],
    slide_w_in: float = SLIDE_W_IN,
    slide_h_in: float = SLIDE_H_IN,
) -> List[SlideElement]:
    """Hoạ tiết nền RẤT MỜ (opacity 3-6%) cho slide thân bài.

    Hoạ tiết thuộc ngữ cảnh chủ đề (chấm sao / lưới toạ độ / lattice chấm) nằm
    DƯỚI mọi phần tử khác (đứng đầu danh sách elements → z-order thấp nhất ở
    cả PPTX lẫn preview). KHÔNG mang morph_id để không tạo nhiễu Morph engine.
    """
    elements: List[SlideElement] = []
    for i, deco in enumerate(pattern_decorations(
        theme, slide_number, slide_w_in, slide_h_in
    )):
        color = accents[i % len(accents)] if deco["shape"] == "oval" else palette["card_border"]
        elements.append(SlideElement(
            id=f"slide{slide_number}_deco{i}",
            type="decoration",
            content="",
            x=_pct_w(float(deco["x"])),
            y=_pct_h(float(deco["y"])),
            width=_pct_w(float(deco["w"])),
            height=_pct_h(float(deco["h"])),
            bg_color=color,
            text_color=None,
            morph_id="",
            shape_type="oval" if deco["shape"] == "oval" else "rectangle",
            opacity=float(deco["opacity"]),
        ))
    return elements


def _build_step_elements(
    num_cards: int,
    card_coords_in: List[Tuple[float, float, float, float]],
    slide_idx: int,
    palette: dict,
    accents: List[str],
) -> List[SlideElement]:
    """Vòng tròn số thứ tự + đường nối cho bố cục tiến trình (TIMELINE_STEPS)."""
    elements: List[SlideElement] = []
    step_d_pct_w = _pct_w(STEP_D_IN)
    step_d_pct_h = _pct_h(STEP_D_IN)
    step_top_pct = _pct_h(STEP_TOP_IN)
    center_y_in = STEP_TOP_IN + STEP_D_IN / 2

    for i in range(num_cards):
        x_in, _, w_in, _ = card_coords_in[i]
        cx_in = x_in + (w_in - STEP_D_IN) / 2

        elements.append(SlideElement(
            id=f"slide{slide_idx}_step_{i + 1}",
            type="badge",
            content=f"{i + 1}",
            x=_pct_w(cx_in),
            y=step_top_pct,
            width=step_d_pct_w,
            height=step_d_pct_h,
            bg_color=accents[i % len(accents)],
            text_color="#FFFFFF",
            morph_id=f"step_{i + 1}",
            font_size=13,
            shape_type="oval",
        ))

        # Đường nối ngang giữa hai vòng tròn liền kề
        if i < num_cards - 1:
            next_x_in, _, next_w_in, _ = card_coords_in[i + 1]
            next_cx_in = next_x_in + (next_w_in - STEP_D_IN) / 2
            line_x_in = cx_in + STEP_D_IN + 0.06
            line_w_in = max(0.1, next_cx_in - 0.06 - line_x_in)
            bar_h_in = 0.04

            elements.append(SlideElement(
                id=f"slide{slide_idx}_conn_{i + 1}",
                type="accent",
                content="",
                x=_pct_w(line_x_in),
                y=_pct_h(center_y_in - bar_h_in / 2),
                width=_pct_w(line_w_in),
                height=_pct_h(bar_h_in),
                bg_color=palette["card_border"],
                text_color=None,
                morph_id=f"step_connector_{i + 1}",
                shape_type="rectangle",
            ))

    return elements


def _build_footer_elements(
    slide_idx: int, total: int, topic: str, style: str, palette: dict
) -> List[SlideElement]:
    """Footer cố định: chủ đề bên trái, số trang & phong cách bên phải."""
    left = SlideElement(
        id=f"footer_topic_{slide_idx}",
        type="footer",
        content=(topic or "ExoticMorph").strip(),
        x=_pct_w(MX_IN),
        y=_pct_h(FOOTER_TOP_IN),
        width=_pct_w(7.5),
        height=_pct_h(FOOTER_H_IN),
        bg_color=None,
        text_color=palette["footer"],
        morph_id="footer_topic",
        font_size=9,
        align="left",
    )
    right = SlideElement(
        id=f"footer_page_{slide_idx}",
        type="footer",
        content=f"{style.upper()} · {slide_idx:02d} / {total:02d}",
        x=_pct_w(SLIDE_W_IN - MX_IN - 4.0),
        y=_pct_h(FOOTER_TOP_IN),
        width=_pct_w(4.0),
        height=_pct_h(FOOTER_H_IN),
        bg_color=None,
        text_color=palette["footer"],
        morph_id="footer_page",
        font_size=9,
        align="right",
    )
    return [left, right]


# ==============================================================================
# DYNAMIC LAYOUT RESOLVER & DIVERSITY ENFORCER
# ==============================================================================

def _infer_layout_from_content(slide: SlideData, num_cards: int) -> LayoutType:
    """Suy luận layout THÂN BÀI tối ưu dựa trên nội dung slide và số lượng thẻ.

    Luôn trả về một layout thuộc `BODY_LAYOUTS` (không phải mở bài/kết bài) vì
    hai vị trí đó do mạch kể chuyện quyết định, không do nội dung.
    """
    combined = (
        (slide.slide_title or "") + " " +
        (slide.section or "") + " " +
        " ".join((c.title or "") + " " + (c.description or "") for c in slide.cards)
    ).lower()

    # Nhận diện số liệu / KPI / kết quả
    stat_keywords = ["%", "tỷ", "triệu", "usd", "doanh thu", "kpi", "roi", "tăng trưởng", "°c", "km", "kg", "gam"]
    has_stats = any(kw in combined for kw in stat_keywords) or any(
        any(ch.isdigit() for ch in c.title) for c in slide.cards
    )

    # Nhận diện quy trình / bước thực hiện
    step_keywords = ["quy trình", "tiến trình", "bước", "lộ trình", "roadmap", "timeline", "giai đoạn", "triển khai"]
    is_steps = any(kw in combined for kw in step_keywords)

    # Nhận diện định nghĩa / khái niệm / hero
    hero_keywords = ["định nghĩa", "khái niệm", "tổng quan", "cốt lõi", "bản chất", "nguyên lý", "giới thiệu"]
    is_hero = any(kw in combined for kw in hero_keywords)

    if is_steps and 3 <= num_cards <= 4:
        return LayoutType.TIMELINE_STEPS
    if has_stats and num_cards <= 2:
        return LayoutType.BIG_STAT_CALLOUT
    if is_hero and num_cards >= 3:
        return LayoutType.ASYMMETRIC_GRID
    if has_stats and num_cards == 3:
        return LayoutType.ASYMMETRIC_GRID
    return LayoutType.CARDS_ROW


def _pick_alternate_body_layout(
    slide: SlideData, num_cards: int, prev: LayoutType, idx: int
) -> LayoutType:
    """Chọn layout thân bài KHÁC với slide liền trước, phù hợp số thẻ hiện có."""
    inferred = _infer_layout_from_content(slide, num_cards)
    if inferred != prev:
        return inferred

    candidates = [l for l in BODY_LAYOUTS if l != prev]
    if not candidates:
        return LayoutType.CARDS_ROW
    if num_cards >= 3 and LayoutType.TIMELINE_STEPS in candidates:
        return LayoutType.TIMELINE_STEPS
    if num_cards == 3 and LayoutType.ASYMMETRIC_GRID in candidates:
        return LayoutType.ASYMMETRIC_GRID
    if num_cards <= 2 and LayoutType.BIG_STAT_CALLOUT in candidates:
        return LayoutType.BIG_STAT_CALLOUT
    return candidates[idx % len(candidates)]


def _resolve_slide_layouts(slides: List[SlideData]) -> List[LayoutType]:
    """Thực thi MẠCH KỂ 3 PHẦN và quy tắc không trùng layout liên tiếp.

    Quy tắc (áp đặt kể cả khi LLM làm sai):
      1. Slide ĐẦU TIÊN            → COVER_HERO.
      2. Slide CUỐI CÙNG (bài >= 2 slide) → CONCLUSION_SUMMARY.
      3. Các slide THÂN BÀI        → BIG_STAT_CALLOUT / ASYMMETRIC_GRID /
         TIMELINE_STEPS / CARDS_ROW, KHÔNG lặp layout của slide liền trước.
      4. Layout đời cũ (SPLIT_HERO/STAT_GRID/GRID_2X2) được nâng cấp lên bố cục
         mới tương đương.
    """
    total = len(slides)
    resolved: List[LayoutType] = []

    for idx, slide in enumerate(slides):
        num_cards = len(slide.cards)
        requested = slide.layout_type or _infer_layout_from_content(slide, num_cards)
        is_first = idx == 0
        is_last = total >= 2 and idx == total - 1

        # --- MỞ BÀI: luôn là COVER_HERO ---
        if is_first:
            target = OPENING_LAYOUTS[0]
            if requested != target:
                logger.info(
                    "Slide 1 (Mở bài): layout_type='%s' -> ép về '%s' theo mạch kể 3 phần.",
                    requested.value, target.value,
                )
            resolved.append(target)
            continue

        # --- KẾT BÀI: luôn là CONCLUSION_SUMMARY ---
        if is_last:
            target = CLOSING_LAYOUTS[0]
            if requested != target:
                logger.info(
                    "Slide %d (Kết bài): layout_type='%s' -> ép về '%s' theo mạch kể 3 phần.",
                    slide.slide_number, requested.value, target.value,
                )
            resolved.append(target)
            continue

        # --- THÂN BÀI: nâng cấp layout cũ, đảm bảo không trùng slide trước ---
        current = LEGACY_LAYOUT_UPGRADE.get(requested, requested)
        if current not in BODY_LAYOUTS:
            current = _infer_layout_from_content(slide, num_cards)

        prev = resolved[idx - 1]
        if current == prev:
            chosen = _pick_alternate_body_layout(slide, num_cards, prev, idx)
            logger.info(
                "Slide %d: trùng layout_type='%s' với slide trước -> tự động chuyển "
                "sang '%s' để bảo đảm đa dạng bố cục.",
                slide.slide_number, current.value, chosen.value,
            )
            current = chosen

        resolved.append(current)

    return resolved


def _split_conclusion_cards(
    cards: List[ContentCard],
) -> Tuple[List[ContentCard], Optional[ContentCard]]:
    """Tách slide kết bài thành đúng 3 dòng mỏng + 1 CTA.

    Nếu LLM trả quá nhiều thẻ, chỉ lấy 3 takeaway đầu và dùng thẻ cuối làm CTA để
    giữ hình học gọn, không sinh thêm hộp lồng/tràn footer.
    """
    if len(cards) >= 4:
        return cards[:3], cards[-1]
    return cards[:3], None


def _speaker_notes_for(
    layout: LayoutType,
    section: str,
    slide_title: str,
    cards: List[ContentCard],
    num_cards: int,
) -> str:
    """Lời dẫn người thuyết trình, viết riêng theo vai trò slide trong mạch kể."""
    if layout == LayoutType.COVER_HERO and cards:
        return (
            f"MỞ BÀI — {section}: {slide_title}. "
            f"Mở màn bằng câu dẫn '{cards[0].title}' rồi khai triển: "
            f"{cards[0].description[:240]} "
            f"Dừng 1-2 giây để khán giả đọc tiêu đề, sau đó chuyển cảnh Morph "
            f"vào phần phân tích."
        )

    if layout == LayoutType.CONCLUSION_SUMMARY:
        takeaways, cta_card = _split_conclusion_cards(cards)
        points = " • ".join(c.title for c in takeaways[:3])
        cta = cta_card.title if cta_card else ""
        return (
            f"KẾT BÀI — {section}: {slide_title}. "
            f"Chốt lại 3 điểm cốt lõi: {points}. "
            + (f"Kết thúc bằng lời kêu gọi hành động: '{cta}'. " if cta else "")
            + "Nhấn mạnh thông điệp cuối cùng rồi dừng slide ở khung tổng kết."
        )

    return (
        f"Phần {section} — {slide_title}. "
        f"Trình bày {num_cards} luận điểm theo bố cục {layout.value}. "
        f"Dẫn dắt người nghe từ nhận diện vấn đề đến hành động cụ thể, "
        f"rồi nhường chỗ cho hiệu ứng Morph khi chuyển slide."
    )


# ==============================================================================
# PUBLIC API: LLMOutput → PresentationResponse
# ==============================================================================

def compute_layout(
    raw: LLMOutput,
    req: GenerateRequest,
) -> PresentationResponse:
    """Chuyển `LLMOutput` thành `PresentationResponse` đã có đầy đủ tọa độ (x, y, w, h)
    theo MẠCH KỂ 3 PHẦN: COVER_HERO (mở bài) → thân bài (BIG_STAT_CALLOUT /
    ASYMMETRIC_GRID / TIMELINE_STEPS / CARDS_ROW) → CONCLUSION_SUMMARY (kết bài).

    Quy trình:
      1. Sắp xếp slides theo slide_number, cắt bớt đúng số lượng yêu cầu.
      2. Thực thi mạch kể 3 phần + quy tắc không có 2 slide liên tiếp trùng layout.
      3. Tính toán hình học chuẩn xác theo từng layout_type.
      4. Thêm badge, kicker, tiêu đề, subtitle/badge cover, 3 card kết bài,
         bước lộ trình và footer.
      5. Tạo speaker_notes và morph_description hỗ trợ chuyển cảnh Morph.
    """
    effective_style = _resolve_effective_style(raw, req)
    palette = _get_palette(effective_style)
    accents = _get_card_accents(effective_style)
    slides_out: List[Slide] = []

    # Bộ motif thị giác theo ngữ cảnh chủ đề (ưu tiên lựa chọn của LLM,
    # fallback suy luận keyword — luôn có ít nhất theme 'generic').
    theme = resolve_visual_theme(
        prompt=f"{getattr(req, 'prompt', '')} {getattr(raw, 'topic', '')}",
        topic=raw.topic,
        llm_hint=getattr(raw, "visual_theme", None),
    )
    slide_w_in = SLIDE_W_IN if req.aspect_ratio != "4:3" else 10.0
    logger.info(
        "Visual theme '%s' (%s) — icon/motif & hoạ tiết nền theo ngữ cảnh chủ đề.",
        theme.key, theme.label,
    )

    sorted_raw_slides = sorted(raw.slides, key=lambda s: s.slide_number)
    sorted_raw_slides = sorted_raw_slides[: req.num_slides]
    total = len(sorted_raw_slides)

    # Thực thi mạch kể 3 phần + quy tắc đa dạng bố cục không trùng lặp liên tiếp
    resolved_layouts = _resolve_slide_layouts(sorted_raw_slides)

    for s_idx, raw_slide in enumerate(sorted_raw_slides):
        slide_number = s_idx + 1
        sorted_cards = sorted(raw_slide.cards, key=lambda c: c.order)
        num_cards = len(sorted_cards)
        layout = resolved_layouts[s_idx]
        section = _section_for(raw_slide.section, s_idx, req.language)

        logger.debug(
            "Slide %d: %d cards -> layout '%s' (section=%r)",
            slide_number, num_cards, layout.value, section,
        )

        elements: List[SlideElement] = []
        slide_subtitle: Optional[str] = None
        slide_bg = palette["bg"]

        # ------------------------------------------------------------------
        # MỞ BÀI — COVER_HERO: tiêu đề siêu lớn + subtitle + hàng badge
        # Nền GRADIENT tối có dải sáng mờ màu chủ đề (thay màu đặc #0A0C12).
        # ------------------------------------------------------------------
        if layout == LayoutType.COVER_HERO:
            lead = sorted_cards[0]
            badge_cards = sorted_cards[1:5]
            geo = _cover_geometry(
                raw_slide.slide_title,
                subtitle=lead.title,
                note=lead.description,
                badge_labels=[c.title for c in badge_cards],
            )
            elements.extend(_build_cover_elements(
                slide_idx=slide_number,
                slide_title=raw_slide.slide_title,
                section=section,
                geo=geo,
                subtitle_text=lead.title,
                note_text=lead.description,
                badge_cards=badge_cards,
                palette=palette,
                accents=accents,
                theme=theme,
            ))
            slide_subtitle = lead.title
            slide_bg = cover_gradient_css(palette["bg"], accents[0], accents[1 % len(accents)])

        # ------------------------------------------------------------------
        # KẾT BÀI — CONCLUSION_SUMMARY: khung tổng kết + 3 điểm cốt lõi + CTA
        # Nền GRADIENT dâng theo màu accent của CTA → cảm giác cao trào.
        # ------------------------------------------------------------------
        elif layout == LayoutType.CONCLUSION_SUMMARY:
            elements.append(_build_badge_element(slide_number, palette))
            elements.append(_build_kicker_element(slide_number, section, palette, theme))
            elements.append(_build_title_element(slide_number, raw_slide.slide_title, palette))

            row_cards, cta_card = _split_conclusion_cards(sorted_cards)
            cta_text = cta_card.title.strip() if cta_card else ""
            elements.extend(_build_conclusion_elements(
                slide_idx=slide_number,
                num_rows=len(row_cards),
                row_cards=row_cards,
                cta_text=cta_text,
                cta_card=cta_card,
                palette=palette,
                accents=accents,
            ))
            cta_accent = _normalize_hex(
                cta_card.color_theme if cta_card else None, accents[-1]
            )
            slide_bg = closing_gradient_css(palette["bg"], cta_accent)

        # ------------------------------------------------------------------
        # THÂN BÀI — BIG_STAT_CALLOUT / ASYMMETRIC_GRID / TIMELINE_STEPS / CARDS_ROW
        # Nền giữ màu đặc nhưng rải HOẠ TIẾT RẤT MỜ (3-6%) theo chủ đề —
        # chấm sao / lưới toạ độ / lattice chấm — nằm dưới mọi phần tử khác.
        # ------------------------------------------------------------------
        else:
            elements.extend(_build_decoration_elements(
                theme, slide_number, palette, accents, slide_w_in, SLIDE_H_IN
            ))
            card_coords_in = _calculate_cards_geometry_inches(layout, num_cards)
            card_coords_pct = [
                (_pct_w(x), _pct_h(y), _pct_w(w), _pct_h(h))
                for x, y, w, h in card_coords_in
            ]

            elements.append(_build_badge_element(slide_number, palette))
            elements.append(_build_kicker_element(slide_number, section, palette, theme))
            elements.append(_build_title_element(slide_number, raw_slide.slide_title, palette))

            for c_idx, card in enumerate(sorted_cards):
                coords = card_coords_pct[c_idx] if c_idx < len(card_coords_pct) else card_coords_pct[-1]
                elements.append(
                    _build_card_element(
                        card, c_idx, num_cards, slide_number, layout,
                        palette, accents, coords, theme,
                    )
                )

            if layout == LayoutType.TIMELINE_STEPS:
                elements.extend(_build_step_elements(num_cards, card_coords_in, slide_number, palette, accents))

        elements.extend(_build_footer_elements(slide_number, total, raw.topic, effective_style, palette))

        speaker_notes = None
        if req.include_speaker_notes:
            speaker_notes = _speaker_notes_for(
                layout, section, raw_slide.slide_title, sorted_cards, num_cards
            )

        # Mô tả morph theo vị trí trong mạch kể chuyện
        if total == 1:
            morph_desc = f"Tiêu điểm duy nhất: thẻ '{sorted_cards[0].morph_id if sorted_cards else 'hero'}' giữ nguyên để kết luận."
        elif slide_number == 1:
            morph_desc = (
                "Mở bài (COVER_HERO): tiêu đề siêu lớn giữ nguyên morph_id 'title_slide' "
                "để thu nhỏ dần về vùng header khi chuyển sang thân bài."
            )
        elif slide_number == total:
            morph_desc = (
                "Kết bài (CONCLUSION_SUMMARY): các luận điểm hội tụ vào khung tổng kết "
                "ở trung tâm, chốt thông điệp cốt lõi và lời kêu gọi hành động."
            )
        else:
            morph_desc = (
                f"Chuyển mạch sang '{section}' ({layout.value}): các đối tượng cùng morph_id "
                f"nội suy vị trí & kích thước mượt mà từ slide trước."
            )

        slides_out.append(Slide(
            slide_number=slide_number,
            title=raw_slide.slide_title,
            section=section,
            subtitle=slide_subtitle,
            speaker_notes=speaker_notes,
            morph_description=morph_desc,
            bg_color=slide_bg,
            layout_type=layout,
            elements=elements,
        ))

    return PresentationResponse(
        topic=raw.topic,
        style=effective_style,
        aspect_ratio=req.aspect_ratio,
        total_slides=len(slides_out),
        slides=slides_out,
        morph_strategy=(
            f"Narrative Arc Layouts (16:9): mở bài COVER_HERO (tiêu đề "
            f"{COVER_TITLE_MIN_PT}-{COVER_TITLE_MAX_PT}pt, lề {COVER_MX_IN}\") → thân bài "
            f"BIG_STAT_CALLOUT ({STAT_COL_RATIO:.0%} số khổng lồ) / ASYMMETRIC_GRID "
            f"({HERO_COL_RATIO:.0%}-{1 - HERO_COL_RATIO:.0%}) / TIMELINE_STEPS / CARDS_ROW "
            f"→ kết bài CONCLUSION_SUMMARY (3 card mỏng + CTA). "
            f"Lề thân bài M_x={MX_IN}\", khoảng cách G={GAP_IN}\". "
            f"Visual theme '{theme.key}': icon motif {theme.kicker_icons[0]} cạnh kicker, "
            f"hoạ tiết nền '{theme.pattern}' opacity 3-6% trên slide thân bài, nền gradient "
            f"cho mở bài & kết bài, card biến thể accent_top/accent_left/outline. "
            f"Morph IDs nhất quán: badge_header, section_kicker, title_slide, title_rule, "
            f"cover_subtitle, call_to_action, step_*, footer_topic/page + card IDs."
        ),
    )
