"""
Layout Engine — Dynamic Layout Diversity & Adaptive Geometry Calculator
~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~
NHIỆM VỤ: Nhận dữ liệu thô `SlideData` (từ LLM) và tính toán TỰ ĐỘNG toạ độ
(x, y), kích thước (w, h) cho từng thẻ card, badge, kicker, tiêu đề, bước lộ
trình và footer — theo 5 kiểu bố cục đa dạng (Dynamic Layout Diversity):

  1. CARDS_ROW      : 2-3 thẻ nằm ngang (Layout mặc định truyền thống).
  2. SPLIT_HERO     : Cột trái rộng (chứa ý chính/Hero point), cột phải xếp 2 thẻ phụ.
  3. STAT_GRID      : Slide nhấn mạnh số liệu (con số to nổi bật + label ngắn).
  4. TIMELINE_STEPS : Tiến trình 3-4 bước theo chiều ngang (kèm số thứ tự + đường nối).
  5. GRID_2X2       : Lưới 4 thẻ chia đều 2 hàng x 2 cột cân đối.

QUY TẮC ĐA DẠNG BẮT BUỘC:
  Trong toàn bộ bài thuyết trình, KHÔNG ĐƯỢC để 2 slide liên tiếp có cùng
  một `layout_type`. Layout Engine sẽ tự động thực thi và bảo đảm quy tắc này.
"""

import logging
from typing import List, Tuple, Optional

from app.schemas.slide_schema import (
    ContentCard,
    GenerateRequest,
    LLMOutput,
    PresentationResponse,
    RawSlideContent,
    Slide,
    SlideData,
    SlideElement,
    StyleType,
    LayoutType,
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
CARDS_TOP_IN = 2.58
CARDS_H_IN   = 3.95

# --- Vùng footer (bộ nhận diện cố định) ---
FOOTER_TOP_IN = 6.84
FOOTER_H_IN   = 0.28

# --- Tiến trình / Lộ trình (TIMELINE_STEPS): vòng tròn số thứ tự phía trên thẻ ---
STEP_TOP_IN           = 2.04
STEP_D_IN             = 0.46
TIMELINE_CARDS_TOP_IN = 2.68
TIMELINE_CARDS_H_IN   = 3.85

# Khoảng cách giữa các thẻ (gap) — inches
GAP_IN   = 0.40
GAP_Y_IN = 0.35


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
    "Minimal": {
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
    "Minimal":    ["#10B981", "#38BDF8", "#C9A227", "#6366F1"],
    "Corporate":  ["#C9A227", "#10B981", "#3A86FF", "#B08D2E"],
    "Creative":   ["#EC4899", "#F59E0B", "#06B6D4", "#8B5CF6"],
}


def _get_palette(style: StyleType) -> dict:
    return STYLE_PALETTES.get(style, STYLE_PALETTES["Futuristic"])


def _get_card_accents(style: StyleType) -> List[str]:
    return CARD_ACCENTS.get(style, CARD_ACCENTS["Futuristic"])


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
    """
    usable_w = SLIDE_W_IN - 2 * MX_IN

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


def _card_title_font_size(num_cards: int, layout: LayoutType, card_index: int = 0) -> int:
    """Cỡ chữ tiêu đề thẻ điều chỉnh tối ưu cho từng kiểu bố cục."""
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


def _build_kicker_element(slide_idx: int, section: str, palette: dict) -> SlideElement:
    """Nhãn mục (kicker) in hoa ngay trên tiêu đề — thể hiện vị trí trong mạch kể chuyện."""
    return SlideElement(
        id=f"kicker_slide_{slide_idx}",
        type="kicker",
        content=(section or "").upper(),
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
    slide_idx: int, slide_title: str, palette: dict
) -> SlideElement:
    """Tiêu đề chính của slide — một thông điệp cụ thể, in đậm, cỡ lớn."""
    return SlideElement(
        id=f"title_slide_{slide_idx}",
        type="heading",
        content=slide_title,
        x=_pct_w(MX_IN),
        y=_pct_h(TITLE_TOP_IN),
        width=_pct_w(SLIDE_W_IN - 2 * MX_IN),
        height=_pct_h(TITLE_H_IN),
        bg_color=None,
        text_color=palette["text"],
        morph_id="title_slide",
        font_size=_title_font_size(slide_title),
    )


def _build_card_element(
    card: ContentCard,
    card_index: int,
    num_cards: int,
    slide_idx: int,
    layout: LayoutType,
    palette: dict,
    accents: List[str],
    coords_pct: Tuple[float, float, float, float],
) -> SlideElement:
    """Một thẻ card với hình học theo layout_type, kèm màu accent riêng."""
    x, y, w, h = coords_pct
    accent = _normalize_hex(card.color_theme, accents[card_index % len(accents)])

    is_hero = (layout == LayoutType.SPLIT_HERO and card_index == 0)
    bg = palette["card_hero"] if (is_hero or (layout == LayoutType.CARDS_ROW and card_index == 0)) else palette["card_fallback"]

    fs_title = _card_title_font_size(num_cards, layout, card_index)

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
    )


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
    """Suy luận kiểu layout tối ưu dựa trên nội dung slide và số lượng thẻ."""
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
    is_hero = slide.slide_number == 1 or any(kw in combined for kw in hero_keywords)

    if has_stats:
        return LayoutType.STAT_GRID
    if is_steps and 3 <= num_cards <= 4:
        return LayoutType.TIMELINE_STEPS
    if is_hero and num_cards <= 3:
        return LayoutType.SPLIT_HERO
    if num_cards == 4:
        return LayoutType.GRID_2X2
    return LayoutType.CARDS_ROW


def _resolve_slide_layouts(slides: List[SlideData]) -> List[LayoutType]:
    """Đảm bảo không bao giờ có 2 slide liên tiếp có cùng một layout_type.

    Ưu tiên lựa chọn layout của LLM; nếu phát hiện 2 slide liên tiếp trùng layout
    thì tự động đổi sang kiểu layout phù hợp khác để thỏa mãn điều kiện đa dạng.
    """
    resolved: List[LayoutType] = []

    # Chu trình ưu tiên để luân chuyển đa dạng layout
    diversity_cycle = [
        LayoutType.SPLIT_HERO,
        LayoutType.STAT_GRID,
        LayoutType.TIMELINE_STEPS,
        LayoutType.GRID_2X2,
        LayoutType.CARDS_ROW,
    ]

    for idx, slide in enumerate(slides):
        num_cards = len(slide.cards)
        current = slide.layout_type

        # Nếu layout_type rỗng hoặc chưa xác định, tự suy luận từ nội dung
        if not current:
            current = _infer_layout_from_content(slide, num_cards)

        if idx > 0 and current == resolved[idx - 1]:
            prev = resolved[idx - 1]
            inferred = _infer_layout_from_content(slide, num_cards)
            if inferred != prev and inferred != current:
                chosen = inferred
            else:
                candidates = [l for l in diversity_cycle if l != prev and l != current]
                if not candidates:
                    candidates = [l for l in diversity_cycle if l != prev]
                # Chọn layout phù hợp nhất với số lượng thẻ hiện có
                if num_cards == 4 and LayoutType.GRID_2X2 in candidates:
                    chosen = LayoutType.GRID_2X2
                elif num_cards >= 3 and LayoutType.TIMELINE_STEPS in candidates and idx >= 2:
                    chosen = LayoutType.TIMELINE_STEPS
                elif num_cards <= 3 and LayoutType.SPLIT_HERO in candidates:
                    chosen = LayoutType.SPLIT_HERO
                else:
                    chosen = candidates[idx % len(candidates)]

            logger.info(
                "Slide %d: Phát hiện trùng layout_type='%s' với slide trước -> tự động chuyển sang '%s' để bảo đảm đa dạng.",
                slide.slide_number, current.value, chosen.value,
            )
            current = chosen

        resolved.append(current)

    return resolved


# ==============================================================================
# PUBLIC API: LLMOutput → PresentationResponse
# ==============================================================================

def compute_layout(
    raw: LLMOutput,
    req: GenerateRequest,
) -> PresentationResponse:
    """Chuyển `LLMOutput` thành `PresentationResponse` đã có đầy đủ tọa độ (x, y, w, h)
    cho từng thẻ theo 5 kiểu bố cục: CARDS_ROW, SPLIT_HERO, STAT_GRID, TIMELINE_STEPS, GRID_2X2.

    Quy trình:
      1. Sắp xếp slides theo slide_number, cắt bớt đúng số lượng yêu cầu.
      2. Giải quyết và thực thi quy tắc đa dạng layout: không có 2 slide liên tiếp trùng layout.
      3. Tính toán hình học chuẩn xác theo từng layout_type.
      4. Thêm badge, kicker, tiêu đề, bước lộ trình và footer.
      5. Tạo speaker_notes và morph_description hỗ trợ chuyển cảnh Morph.
    """
    palette = _get_palette(req.style)
    accents = _get_card_accents(req.style)
    slides_out: List[Slide] = []

    sorted_raw_slides = sorted(raw.slides, key=lambda s: s.slide_number)
    sorted_raw_slides = sorted_raw_slides[: req.num_slides]
    total = len(sorted_raw_slides)

    # Giải quyết và thực thi quy tắc đa dạng bố cục không trùng lặp liên tiếp
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

        # Tính toán hình học chi tiết từng thẻ
        card_coords_in = _calculate_cards_geometry_inches(layout, num_cards)
        card_coords_pct = [
            (_pct_w(x), _pct_h(y), _pct_w(w), _pct_h(h))
            for x, y, w, h in card_coords_in
        ]

        elements: List[SlideElement] = []
        elements.append(_build_badge_element(slide_number, palette))
        elements.append(_build_kicker_element(slide_number, section, palette))
        elements.append(_build_title_element(slide_number, raw_slide.slide_title, palette))

        for c_idx, card in enumerate(sorted_cards):
            coords = card_coords_pct[c_idx] if c_idx < len(card_coords_pct) else card_coords_pct[-1]
            elements.append(
                _build_card_element(card, c_idx, num_cards, slide_number, layout, palette, accents, coords)
            )

        if layout == LayoutType.TIMELINE_STEPS:
            elements.extend(_build_step_elements(num_cards, card_coords_in, slide_number, palette, accents))

        elements.extend(_build_footer_elements(slide_number, total, raw.topic, req.style, palette))

        speaker_notes = None
        if req.include_speaker_notes:
            speaker_notes = (
                f"Phần {section} — {raw_slide.slide_title}. "
                f"Trình bày {num_cards} luận điểm theo bố cục {layout.value}. "
                f"Dẫn dắt người nghe từ nhận diện vấn đề đến hành động cụ thể, "
                f"rồi nhường chỗ cho hiệu ứng Morph khi chuyển slide."
            )

        # Mô tả morph theo vị trí trong mạch kể chuyện
        if total == 1:
            morph_desc = f"Tiêu điểm duy nhất: thẻ '{sorted_cards[0].morph_id if sorted_cards else 'hero'}' giữ nguyên để kết luận."
        elif slide_number == 1:
            morph_desc = "Mở đầu: khối nội dung trọng tâm phóng to từ vùng trung tâm để đặt vấn đề."
        elif slide_number == total:
            morph_desc = "Tổng kết: các thẻ hội tụ về trung tâm, chốt lại thông điệp và lời kêu gọi hành động."
        else:
            morph_desc = (
                f"Chuyển mạch sang '{section}' ({layout.value}): các đối tượng cùng morph_id "
                f"nội suy vị trí & kích thước mượt mà từ slide trước."
            )

        slides_out.append(Slide(
            slide_number=slide_number,
            title=raw_slide.slide_title,
            section=section,
            subtitle=None,
            speaker_notes=speaker_notes,
            morph_description=morph_desc,
            bg_color=palette["bg"],
            layout_type=layout,
            elements=elements,
        ))

    return PresentationResponse(
        topic=raw.topic,
        style=req.style,
        aspect_ratio=req.aspect_ratio,
        total_slides=len(slides_out),
        slides=slides_out,
        morph_strategy=(
            f"Dynamic Layout Diversity (16:9): CARDS_ROW, SPLIT_HERO, STAT_GRID, "
            f"TIMELINE_STEPS, GRID_2X2 luân chuyển linh hoạt theo ngữ cảnh, lề M_x={MX_IN}\", "
            f"khoảng cách G={GAP_IN}\". "
            f"Morph IDs nhất quán: badge_header, section_kicker, title_slide, "
            f"step_*, footer_topic/page + card IDs."
        ),
    )
