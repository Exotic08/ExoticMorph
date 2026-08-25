"""
Layout Engine — Pure Python Geometry Calculator (Flexbox Layout)
~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~
NHIỆM VỤ: Nhận dữ liệu thô `RawSlideContent` (chỉ có nội dung từ LLM) và
tính toán TỰ ĐỘNG toạ độ (x, y), kích thước (w, h) cho từng thẻ card,
cùng với badge tiêu đề và màu nền.

TRÁCH NHIỆM RÕ RÀNG (Separation of Concerns):
  - AI (LLM) : sáng tạo nội dung (chữ, màu, morph_id, thứ tự).
  - Python   : tính hình học (chia lưới, căn giữa, tính kích thước).

BỘ CÔNG THỨC HÌNH HỌC (Dynamic Flexbox 16:9):
  Canvas 16:9:  W = 13.333 inches, H = 7.5 inches.
  Lề trái/phải       : M_x      = 0.8 inches
  Lề trên (title)    : M_y      = 2.0 inches
  Lề dưới            : M_bottom = 0.8 inches
  Khoảng cách card   : G        = 0.4 inches (horizontal gap)

  Chiều cao cố định mỗi card:
        h = H - M_y - M_bottom = 7.5 - 2.0 - 0.8 = 4.7 inches

  Chiều rộng mỗi card (theo số lượng N, 1 ≤ N ≤ 4):
        w = ((W - 2·M_x) - (N-1)·G) / N

  Tọa độ card thứ i (0-indexed):
        x_i = M_x + i·(w + G)
        y_i = M_y = 2.0 inches

  Tất cả cards được xếp thành MỘT HÀNG DUY NHẤT (single-row flexbox)
  từ 1 đến 4 cards — đúng như công thức Flexbox của CSS/Web.
"""

import logging
from typing import List, Tuple

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
MY_IN = 2.0           # Lề trên (dành chỗ cho Badge + Slide Title)
MB_IN = 0.8           # Lề dưới (bottom margin)

# Khoảng cách giữa các card (horizontal gap) — inches
GAP_IN = 0.4

# Chiều cao cố định của mỗi card (single-row layout)
#   h = H - M_y - M_bottom = 7.5 - 2.0 - 0.8 = 4.7 inches
CARD_H_IN = SLIDE_H_IN - MY_IN - MB_IN   # = 4.7 inches


# ==============================================================================
# QUY ĐỔI INCHES → PERCENT (ppt_builder dùng %)
# ==============================================================================
# ppt_builder.py nhận tọa độ dưới dạng % (0-100) của slide width/height
# và tự quy đổi sang EMU/Inches qua _pct_to_inches().
# Do đó ta tính toán bằng inches (chính xác theo công thức) rồi quy đổi sang %.

def _inch_to_pct_w(inch: float) -> float:
    """Quy đổi inches → % chiều rộng slide."""
    return (inch / SLIDE_W_IN) * 100.0

def _inch_to_pct_h(inch: float) -> float:
    """Quy đổi inches → % chiều cao slide."""
    return (inch / SLIDE_H_IN) * 100.0


# ==============================================================================
# FLEXBOX GEOMETRY: công thức chính
# ==============================================================================

def _card_geometry_inches(n: int, i: int) -> Tuple[float, float, float, float]:
    """Tính (x, y, w, h) bằng inches cho card thứ i (0-indexed) trong
    bố cục n cards (1 ≤ n ≤ 4) — công thức Flexbox single-row.

    Công thức:
        usable_w = W - 2·M_x
        w = (usable_w - (n-1)·G) / n
        x = M_x + i·(w + G)
        y = M_y
        h = 4.7 inches

    Returns:
        (x_in, y_in, w_in, h_in) — đơn vị inches.
    """
    usable_w = SLIDE_W_IN - 2 * MX_IN
    w_in = (usable_w - (n - 1) * GAP_IN) / n
    x_in = MX_IN + i * (w_in + GAP_IN)
    y_in = MY_IN
    h_in = CARD_H_IN
    return x_in, y_in, w_in, h_in


def _card_geometry_pct(n: int, i: int) -> Tuple[float, float, float, float]:
    """Bọc _card_geometry_inches, quy đổi kết quả sang % và làm tròn."""
    x_in, y_in, w_in, h_in = _card_geometry_inches(n, i)
    x_pct = _inch_to_pct_w(x_in)
    y_pct = _inch_to_pct_h(y_in)
    w_pct = _inch_to_pct_w(w_in)
    h_pct = _inch_to_pct_h(h_in)
    return round(x_pct, 2), round(y_pct, 2), round(w_pct, 2), round(h_pct, 2)


# ==============================================================================
# BADGE & TITLE PLACEMENT (trong vùng M_y phía trên)
# ==============================================================================
# Vùng trên có sẵn M_y = 2.0 inches (tương đương 26.67% chiều cao) để đặt Badge + Title.
# Phân bổ:
#   - Badge: cách trên 0.4 in, cao 0.45 in (pill tag)
#   - Title: cách badge 0.25 in, cao ~0.9 in (phủ hết vùng còn lại)

BADGE_TOP_IN = 0.4     # cách mép trên 0.4"
BADGE_H_IN   = 0.45    # chiều cao badge
BADGE_W_IN   = 3.4     # chiều rộng badge ≈ 3.4 inches (~25.5% W)

TITLE_TOP_IN  = BADGE_TOP_IN + BADGE_H_IN + 0.25   # ≈ 1.1 inches
TITLE_H_IN    = MY_IN - TITLE_TOP_IN - 0.05        # ≈ 0.85 inches
TITLE_W_IN    = SLIDE_W_IN - 2 * MX_IN             # full nội dung, rộng ~11.73"

# Quy đổi sang %
BADGE_X_PCT = round(_inch_to_pct_w(MX_IN), 2)
BADGE_Y_PCT = round(_inch_to_pct_h(BADGE_TOP_IN), 2)
BADGE_W_PCT = round(_inch_to_pct_w(BADGE_W_IN), 2)
BADGE_H_PCT = round(_inch_to_pct_h(BADGE_H_IN), 2)

TITLE_X_PCT = round(_inch_to_pct_w(MX_IN), 2)
TITLE_Y_PCT = round(_inch_to_pct_h(TITLE_TOP_IN), 2)
TITLE_W_PCT = round(_inch_to_pct_w(TITLE_W_IN), 2)
TITLE_H_PCT = round(_inch_to_pct_h(TITLE_H_IN), 2)


# ==============================================================================
# STYLE PALETTES
# ==============================================================================
STYLE_PALETTES = {
    "Futuristic": {
        "bg":           "#090A0F",
        "card_fallback": "#161926",
        "card_border":  "#2A2F45",
        "text":         "#FFFFFF",
        "sub_text":     "#94A3B8",
        "badge":        "#8B5CF6",
        "badge_text":   "#FFFFFF",
        "accent":       "#06B6D4",
    },
    "Minimal": {
        "bg":           "#0F172A",
        "card_fallback": "#1E293B",
        "card_border":  "#334155",
        "text":         "#F8FAFC",
        "sub_text":     "#CBD5E1",
        "badge":        "#6366F1",
        "badge_text":   "#FFFFFF",
        "accent":       "#38BDF8",
    },
    "Corporate": {
        "bg":           "#0A1128",
        "card_fallback": "#141F36",
        "card_border":  "#1E2D4A",
        "text":         "#FFFFFF",
        "sub_text":     "#94A3B8",
        "badge":        "#2563EB",
        "badge_text":   "#FFFFFF",
        "accent":       "#10B981",
    },
    "Creative": {
        "bg":           "#120A1F",
        "card_fallback": "#241438",
        "card_border":  "#3B2159",
        "text":         "#FFFFFF",
        "sub_text":     "#E2E8F0",
        "badge":        "#D946EF",
        "badge_text":   "#FFFFFF",
        "accent":       "#F59E0B",
    },
}


def _get_palette(style: StyleType) -> dict:
    return STYLE_PALETTES.get(style, STYLE_PALETTES["Futuristic"])


# ==============================================================================
# BUILD ELEMENTS: badge + title + cards
# ==============================================================================

def _build_badge_element(slide_idx: int, palette: dict) -> SlideElement:
    """Badge (pill tag) ở góc trên-trái — cùng morph_id xuyên suốt để Morph."""
    return SlideElement(
        id=f"badge_slide_{slide_idx}",
        type="badge",
        content=f"SLIDE {slide_idx:02d}",
        x=BADGE_X_PCT,
        y=BADGE_Y_PCT,
        width=BADGE_W_PCT,
        height=BADGE_H_PCT,
        bg_color=palette["badge"],
        text_color=palette["badge_text"],
        morph_id="badge_header",
        font_size=11,
        shape_type="rounded_rectangle",
    )


def _build_title_element(
    slide_idx: int,
    slide_title: str,
    palette: dict,
) -> SlideElement:
    """Tiêu đề chính của slide, nằm ngay dưới badge, full-width."""
    return SlideElement(
        id=f"title_slide_{slide_idx}",
        type="heading",
        content=slide_title,
        x=TITLE_X_PCT,
        y=TITLE_Y_PCT,
        width=TITLE_W_PCT,
        height=TITLE_H_PCT,
        bg_color=None,
        text_color=palette["text"],
        morph_id="title_slide",
        font_size=24,
    )


def _build_card_element(
    card: ContentCard,
    card_index: int,
    num_cards: int,
    slide_idx: int,
    palette: dict,
) -> SlideElement:
    """Một thẻ card với hình học Flexbox (single-row), tính bằng công thức
    w = (W - 2·M_x - (n-1)·G) / n ; x = M_x + i·(w+G) ; y = M_y ; h = 4.7"."""

    # Với N > 4 (fallback), tạm xếp thành 2 hàng 3+2 hoặc 3+3 (giữ nguyên logic cũ)
    # Nhưng theo spec chính thức N ∈ [1,4] là single-row.
    n = min(num_cards, 4)
    i = min(card_index, n - 1)
    x, y, w, h = _card_geometry_pct(n, i)

    # Xử lý màu nền (đảm bảo có dấu '#')
    bg = card.color_theme if card.color_theme else palette["card_fallback"]
    if bg and not bg.startswith("#"):
        bg = f"#{bg}"

    # Font size tự động co giãn theo số lượng card (càng nhiều card → font nhỏ)
    if num_cards == 1:
        fs_title, fs_body = 28, 15
    elif num_cards == 2:
        fs_title, fs_body = 22, 13
    elif num_cards == 3:
        fs_title, fs_body = 18, 12
    else:  # 4
        fs_title, fs_body = 15, 11

    return SlideElement(
        id=f"slide{slide_idx}_card{card_index}_{card.morph_id}",
        type="card",
        content=card.title,
        label=f"",
        sub_text=card.body,
        x=x,
        y=y,
        width=w,
        height=h,
        bg_color=bg,
        text_color=palette["text"],
        morph_id=card.morph_id,
        font_size=fs_title,
        shape_type="rounded_rectangle",
        border_color=palette["card_border"],
    )


# ==============================================================================
# PUBLIC API: LLMOutput → PresentationResponse
# ==============================================================================

def compute_layout(
    raw: LLMOutput,
    req: GenerateRequest,
) -> PresentationResponse:
    """Chuyển `LLMOutput` (chỉ nội dung) thành `PresentationResponse` đã có
    đầy đủ toạ độ (x,y,w,h) — dùng công thức Flexbox single-row cho N=1..4.

    Quy trình:
      1. Sắp xếp slides theo slide_number, cắt bớt đúng số lượng yêu cầu.
      2. Với mỗi slide: sắp xếp cards theo `order`.
      3. Tính geometry Flexbox: w=(W-2M_x-(N-1)G)/N, x=M_x+i(w+G), y=M_y, h=4.7".
      4. Thêm badge + title với morph_id nhất quán xuyên suốt.
      5. Tạo speaker_notes và morph_description.
    """
    palette = _get_palette(req.style)
    slides_out: List[Slide] = []

    sorted_raw_slides = sorted(raw.slides, key=lambda s: s.slide_number)
    sorted_raw_slides = sorted_raw_slides[: req.num_slides]

    for s_idx, raw_slide in enumerate(sorted_raw_slides, start=1):
        sorted_cards = sorted(raw_slide.cards, key=lambda c: c.order)
        num_cards = len(sorted_cards)

        logger.debug(
            "Slide %d: %d cards -> Flexbox single-row layout (w=(W-2·%.1f-(%d-1)·%.1f)/%d, h=%.1f\")",
            s_idx, num_cards, MX_IN, num_cards, GAP_IN, num_cards, CARD_H_IN,
        )

        elements: List[SlideElement] = []
        elements.append(_build_badge_element(s_idx, palette))
        elements.append(_build_title_element(s_idx, raw_slide.slide_title, palette))

        for c_idx, card in enumerate(sorted_cards):
            elements.append(
                _build_card_element(card, c_idx, num_cards, s_idx, palette)
            )

        speaker_notes = None
        if req.include_speaker_notes:
            speaker_notes = (
                f"Slide {s_idx}: {raw_slide.slide_title}. "
                f"Trình bày {num_cards} điểm chính theo bố cục Flexbox. "
                f"Nhấn mạnh luồng chuyển động Morph khi chuyển sang slide tiếp theo."
            )

        if s_idx == 1:
            morph_desc = "Slide mở đầu: giới thiệu tổng quan chủ đề."
        elif s_idx == len(sorted_raw_slides):
            morph_desc = "Slide tổng kết: các thẻ hội tụ về trung tâm để kết luận."
        else:
            morph_desc = (
                f"Slide {s_idx}: giữ nguyên morph_id để Morph chuyển động "
                f"mượt mà từ slide trước."
            )

        slides_out.append(Slide(
            slide_number=s_idx,
            title=raw_slide.slide_title,
            subtitle=None,
            speaker_notes=speaker_notes,
            morph_description=morph_desc,
            bg_color=palette["bg"],
            elements=elements,
        ))

    return PresentationResponse(
        topic=raw.topic,
        style=req.style,
        aspect_ratio=req.aspect_ratio,
        total_slides=len(slides_out),
        slides=slides_out,
        morph_strategy=(
            f"Dynamic Flexbox single-row (16:9): "
            f"M_x={MX_IN}\", M_y={MY_IN}\", M_bottom={MB_IN}\", G={GAP_IN}\", "
            f"h={CARD_H_IN}\", w=(W-2·M_x-(N-1)·G)/N. "
            f"Morph IDs nhất quán xuyên suốt (badge_header, title_slide + card IDs)."
        ),
    )
