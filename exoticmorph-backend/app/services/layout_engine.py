"""
Layout Engine — Adaptive Editorial Geometry Calculator
~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~
NHIỆM VỤ: Nhận dữ liệu thô `RawSlideContent` (chỉ có nội dung từ LLM) và tính
toán TỰ ĐỘNG toạ độ (x, y), kích thước (w, h) cho từng thẻ card, badge, kicker,
tiêu đề, bước lộ trình và footer — theo số lượng ý tưởng trên mỗi slide.

TRÁCH NHIỆM RÕ RÀNG (Separation of Concerns):
  - AI (LLM) : sáng tạo nội dung (chữ, màu, morph_id, thứ tự, nhãn mục).
  - Python   : tính hình học & chọn bố cục (layout) phù hợp nhất với khung hình.

BỘ CÔNG THỨC HÌNH HỌC (Editorial 16:9):
  Canvas 16:9:  W = 13.333 inches, H = 7.5 inches.

  Vùng chữ (badge + kicker + title) nằm phía trên, vùng nội dung (cards) ở giữa,
  footer cố định dưới cùng để giữ "bộ nhận diện" nhất quán xuyên suốt deck.

  Bố cục tự động theo số thẻ N:
    N=1          -> hero       : 1 khối tuyên bố lớn, căn giữa, nhiều khoảng thở.
    N=2          -> compare    : 2 cột so sánh cân đối hai bên.
    N=3          -> features   : 3 thẻ tính năng đều nhau.
    N=4          -> roadmap    : 4 bước lộ trình, có vòng tròn số thứ tự + đường nối.
    N=5..6       -> grid       : lưới 2 hàng cân đối.

  Mọi thẻ đều giữ morph_id ổn định để PowerPoint Morph nội suy mượt mà giữa
  các slide (đối tượng cùng tên '!!<id>' sẽ được nội suy vị trí/kích thước/màu).
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
    SlideElement,
    StyleType,
)

logger = logging.getLogger("exoticmorph.layout")


# ==============================================================================
# HẰNG SỐ CANVAS 16:9 (đơn vị INCHES)
# ==============================================================================
SLIDE_W_IN = 13.333   # Chiều rộng slide 16:9 widescreen
SLIDE_H_IN = 7.5      # Chiều cao slide 16:9

# Lề (margins) — inches
MX_IN = 0.8           # Lề trái / phải  (left & right margin)

# --- Vùng tiêu đề (badge + kicker + title) ---
BADGE_TOP_IN = 0.40
BADGE_H_IN   = 0.40
BADGE_W_IN   = 2.30

KICKER_TOP_IN = 0.92
KICKER_H_IN   = 0.28

TITLE_TOP_IN  = 1.26
TITLE_H_IN    = 0.74

# --- Vùng nội dung (cards) ---
CARDS_TOP_IN = 2.58
CARDS_H_IN   = 3.95

# --- Vùng footer (bộ nhận diện cố định) ---
FOOTER_TOP_IN = 6.84
FOOTER_H_IN   = 0.28

# --- Lộ trình (roadmap): vòng tròn số thứ tự phía trên thẻ ---
STEP_TOP_IN  = 2.04
STEP_D_IN    = 0.46

# Khoảng cách giữa các thẻ (horizontal gap) — inches
GAP_IN = 0.4


# ==============================================================================
# QUY ĐỔI INCHES → PERCENT (ppt_builder dùng %)
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
# STYLE PALETTES — tinh tế, tương phản cao (ngọc bảo / tím thẫm / xám xì-gà /
# vàng đồng ấm áp). Mỗi palette gồm nền, thẻ, chữ, badge và 2 màu accent.
# ==============================================================================
STYLE_PALETTES = {
    "Futuristic": {
        "bg":           "#0A0C12",
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
        "bg":           "#0E1319",
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
        "bg":           "#0A1120",
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
        "bg":           "#120A1A",
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

# Màu accent tươi dành cho thẻ (fallback khi LLM không cung cấp color_theme).
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
# MẠCH KỂ CHUYỆN (narrative arc): Vấn đề → Nguyên nhân → Giải pháp → Kết quả
# → Hành động. Nhãn mục được suy ra THEO VỊ TRÍ slide (không nén theo tổng số),
# để luôn khớp với nội dung do Fallback/LLM viết cho từng vị trí.
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
    """Ưu tiên nhãn mục do LLM/fallback cung cấp; nếu rỗng thì suy ra theo vị trí
    trong mạch kể chuyện (đảm bảo khớp với nội dung của từng vị trí slide)."""
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
    """Cỡ chữ tiêu đề co giãn theo độ dài để luôn vừa khung, giữ phân cấp thị giác."""
    n = len(title or "")
    if n > 110:
        return 16
    if n > 70:
        return 19
    if n > 45:
        return 22
    return 26


def _layout_for_n(n: int) -> str:
    if n <= 1:
        return "hero"
    if n == 2:
        return "compare"
    if n == 3:
        return "features"
    if n == 4:
        return "roadmap"
    return "grid"


# ==============================================================================
# FLEXBOX GEOMETRY: công thức chính
# ==============================================================================
def _row_width(n: int) -> float:
    """Chiều rộng mỗi thẻ trong một hàng gồm n thẻ."""
    usable_w = SLIDE_W_IN - 2 * MX_IN
    return (usable_w - (n - 1) * GAP_IN) / n


def _card_geometry_inches(n: int, i: int, layout: str) -> Tuple[float, float, float, float]:
    """Tính (x, y, w, h) bằng inches cho thẻ thứ i trong bố cục gồm n thẻ.

    Returns: (x_in, y_in, w_in, h_in).
    """
    usable_w = SLIDE_W_IN - 2 * MX_IN

    if layout == "hero":
        w_in = min(usable_w, 9.6)
        x_in = MX_IN + (usable_w - w_in) / 2
        return x_in, CARDS_TOP_IN, w_in, CARDS_H_IN

    if layout == "grid":
        # Lưới 2 hàng: hàng trên ceil(n/2), hàng dưới phần còn lại.
        row_h = (CARDS_H_IN - GAP_IN) / 2
        top_n = (n + 1) // 2
        if i < top_n:
            row_n = top_n
            row_idx = 0
            j = i
        else:
            row_n = n - top_n
            row_idx = 1
            j = i - top_n
        w_in = (usable_w - (row_n - 1) * GAP_IN) / row_n
        # Căn giữa hàng dưới nếu ít thẻ hơn hàng trên.
        row_total_w = row_n * w_in + (row_n - 1) * GAP_IN
        x_in = MX_IN + (usable_w - row_total_w) / 2 + j * (w_in + GAP_IN)
        y_in = CARDS_TOP_IN + row_idx * (row_h + GAP_IN)
        return x_in, y_in, w_in, row_h

    # compare / features / roadmap: một hàng duy nhất.
    w_in = _row_width(n)
    x_in = MX_IN + i * (w_in + GAP_IN)
    return x_in, CARDS_TOP_IN, w_in, CARDS_H_IN


def _card_geometry_pct(n: int, i: int, layout: str) -> Tuple[float, float, float, float]:
    x_in, y_in, w_in, h_in = _card_geometry_inches(n, i, layout)
    return _pct_w(x_in), _pct_h(y_in), _pct_w(w_in), _pct_h(h_in)


def _card_title_font_size(num_cards: int, layout: str) -> int:
    """Cỡ chữ tiêu đề thẻ — càng nhiều thẻ thì chữ càng gọn, giữ phân cấp rõ ràng."""
    if layout == "hero":
        return 24
    if num_cards == 2:
        return 18
    if num_cards == 3:
        return 15
    if num_cards == 4:
        return 13
    return 12


def _normalize_hex(hex_str: Optional[str], fallback: str) -> str:
    """Đảm bảo màu có dấu '#'; chịu lỗi chuỗi màu CSS/transparent từ LLM."""
    value = (hex_str or "").strip()
    if not value:
        return fallback
    if not value.startswith("#"):
        value = f"#{value}"
    if len(value) != 7:
        return fallback
    return value


# ==============================================================================
# BUILD ELEMENTS: badge + kicker + title + cards + step + footer
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
    layout: str,
    palette: dict,
    accents: List[str],
) -> SlideElement:
    """Một thẻ card với hình học theo layout, kèm màu accent riêng."""
    x, y, w, h = _card_geometry_pct(num_cards, card_index, layout)

    # Màu accent của thẻ: ưu tiên color_theme từ LLM, fallback theo style.
    accent = _normalize_hex(card.color_theme, accents[card_index % len(accents)])

    # Nền thẻ: thẻ đầu (primary) dùng màu nhỉnh hơn để tạo điểm nhấn nhẹ.
    bg = palette["card_hero"] if card_index == 0 else palette["card_fallback"]

    fs_title = _card_title_font_size(num_cards, layout)

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
        step=(card_index + 1 if layout == "roadmap" else None),
    )


def _build_step_elements(
    num_cards: int, slide_idx: int, palette: dict, accents: List[str]
) -> List[SlideElement]:
    """Vòng tròn số thứ tự + đường nối cho bố cục lộ trình (roadmap)."""
    elements: List[SlideElement] = []
    step_y_pct = _pct_h(STEP_TOP_IN)
    step_w_pct = _pct_w(STEP_D_IN)
    step_h_pct = _pct_h(STEP_D_IN)
    center_y = STEP_TOP_IN + STEP_D_IN / 2

    for i in range(num_cards):
        x_in, _, w_in, _ = _card_geometry_inches(num_cards, i, "roadmap")
        cx = x_in + w_in / 2 - STEP_D_IN / 2
        elements.append(SlideElement(
            id=f"slide{slide_idx}_step_{i + 1}",
            type="badge",
            content=f"{i + 1}",
            x=_pct_w(cx),
            y=step_y_pct,
            width=step_w_pct,
            height=step_h_pct,
            bg_color=accents[i % len(accents)],
            text_color="#FFFFFF",
            morph_id=f"step_{i + 1}",
            font_size=13,
            shape_type="oval",
        ))

        # Đường nối ngang giữa hai vòng tròn liền kề.
        if i < num_cards - 1:
            bar_w = GAP_IN - 0.12
            bar_h = 0.04
            elements.append(SlideElement(
                id=f"slide{slide_idx}_conn_{i + 1}",
                type="accent",
                content="",
                x=_pct_w(x_in + w_in + 0.06),
                y=_pct_h(center_y - bar_h / 2),
                width=_pct_w(bar_w),
                height=_pct_h(bar_h),
                bg_color=palette["card_border"],
                text_color=None,
                morph_id="step_connector",
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
# PUBLIC API: LLMOutput → PresentationResponse
# ==============================================================================
def compute_layout(
    raw: LLMOutput,
    req: GenerateRequest,
) -> PresentationResponse:
    """Chuyển `LLMOutput` (chỉ nội dung) thành `PresentationResponse` đã có đầy đủ
    toạ độ (x, y, w, h) — tự chọn bố cục (hero/compare/features/roadmap/grid)
    theo số lượng thẻ, kèm badge, kicker, tiêu đề, bước lộ trình và footer.

    Quy trình:
      1. Sắp xếp slides theo slide_number, cắt bớt đúng số lượng yêu cầu.
      2. Với mỗi slide: sắp xếp cards theo `order`, chọn layout theo số thẻ.
      3. Tính geometry, gán màu accent, thêm badge + kicker + title + footer.
      4. Sinh speaker_notes và morph_description theo mạch kể chuyện.
    """
    palette = _get_palette(req.style)
    accents = _get_card_accents(req.style)
    slides_out: List[Slide] = []

    sorted_raw_slides = sorted(raw.slides, key=lambda s: s.slide_number)
    sorted_raw_slides = sorted_raw_slides[: req.num_slides]
    total = len(sorted_raw_slides)

    for s_idx, raw_slide in enumerate(sorted_raw_slides):
        slide_number = s_idx + 1
        sorted_cards = sorted(raw_slide.cards, key=lambda c: c.order)
        num_cards = len(sorted_cards)
        layout = _layout_for_n(num_cards)
        section = _section_for(raw_slide.section, s_idx, req.language)

        logger.debug(
            "Slide %d: %d cards -> layout '%s' (section=%r)",
            slide_number, num_cards, layout, section,
        )

        elements: List[SlideElement] = []
        elements.append(_build_badge_element(slide_number, palette))
        elements.append(_build_kicker_element(slide_number, section, palette))
        elements.append(_build_title_element(slide_number, raw_slide.slide_title, palette))

        for c_idx, card in enumerate(sorted_cards):
            elements.append(
                _build_card_element(card, c_idx, num_cards, slide_number, layout, palette, accents)
            )

        if layout == "roadmap":
            elements.extend(_build_step_elements(num_cards, slide_number, palette, accents))

        elements.extend(_build_footer_elements(slide_number, total, raw.topic, req.style, palette))

        speaker_notes = None
        if req.include_speaker_notes:
            speaker_notes = (
                f"Phần {section} — {raw_slide.slide_title}. "
                f"Trình bày {num_cards} luận điểm theo bố cục {layout}. "
                f"Dẫn dắt người nghe từ nhận diện vấn đề đến hành động cụ thể, "
                f"rồi nhường chỗ cho hiệu ứng Morph khi chuyển slide."
            )

        # Mô tả morph theo vị trí trong mạch kể chuyện.
        if total == 1:
            morph_desc = f"Tiêu điểm duy nhất: thẻ '{sorted_cards[0].morph_id if sorted_cards else 'hero'}' giữ nguyên để kết luận."
        elif slide_number == 1:
            morph_desc = "Mở đầu: khối nội dung trọng tâm phóng to từ vùng trung tâm để đặt vấn đề."
        elif slide_number == total:
            morph_desc = "Tổng kết: các thẻ hội tụ về trung tâm, chốt lại thông điệp và lời kêu gọi hành động."
        else:
            morph_desc = (
                f"Chuyển mạch sang '{section}': các đối tượng cùng morph_id "
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
            f"Adaptive Editorial (16:9): layout tự chọn theo số thẻ "
            f"(hero/compare/features/roadmap/grid), lề M_x={MX_IN}\", "
            f"khoảng cách G={GAP_IN}\", vùng thẻ {CARDS_H_IN}\". "
            f"Morph IDs nhất quán: badge_header, section_kicker, title_slide, "
            f"step_*, footer_topic/page + card IDs."
        ),
    )
