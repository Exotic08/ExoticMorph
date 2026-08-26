"""
PPTX Generator Service for ExoticMorph
~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~
Đọc dữ liệu có cấu trúc từ Layout Engine (PresentationResponse), chuyển đổi tọa
độ % sang Inches, dựng slide bằng python-pptx và can thiệp OpenXML để kích hoạt
hiệu ứng Morph.

Đợt nâng cấp (Executive Design):
- Kiểu chữ phân cấp rõ ràng: kicker in hoa có tracking, tiêu đề lớn đậm, thân
  chữ tương phản cao với khoảng cách dòng thoáng.
- Mỗi thẻ có thanh accent trên đỉnh (màu nhận diện) + nền tối sang trọng.
- Bố cục lộ trình (roadmap) có vòng tròn số thứ tự và đường nối.
- Footer cố định (chủ đề + số trang) trên mọi slide để đồng bộ bộ nhận diện.
"""

import io
from typing import Optional, Tuple

from pptx import Presentation
from pptx.util import Inches, Pt, Emu
from pptx.enum.shapes import MSO_SHAPE
from pptx.enum.text import PP_ALIGN
from pptx.dml.color import RGBColor

from app.schemas.slide_schema import PresentationResponse, Slide, SlideElement
from app.core.xml_helper import enable_morph_transition, set_shape_morph_id
from app.services.layout_engine import STYLE_PALETTES

# Thời lượng chuyển cảnh Morph (ms) — nhanh, dứt khoát như keynote chuyên nghiệp.
MORPH_DURATION_MS = 900


def hex_to_rgb(hex_str: Optional[str], default: RGBColor = RGBColor(255, 255, 255)) -> RGBColor:
    """Chuyển đổi chuỗi Hex (ví dụ '#8B5CF6' hoặc '8B5CF6') sang RGBColor của python-pptx.

    Chịu lỗi: chuỗi rỗng, sai độ dài, ký tự hex không hợp lệ -> trả màu default.
    """
    if not hex_str or not isinstance(hex_str, str):
        return default

    clean = hex_str.strip().lstrip("#")
    if len(clean) == 3:
        clean = "".join([c * 2 for c in clean])
    if len(clean) != 6:
        return default

    try:
        r = int(clean[0:2], 16)
        g = int(clean[2:4], 16)
        b = int(clean[4:6], 16)
        return RGBColor(r, g, b)
    except ValueError:
        return default


def _set_letter_spacing(run, spacing_pt: float) -> None:
    """Tăng khoảng cách giữa các ký tự (tracking) cho hiệu ứng 'small caps' sang trọng.

    Thuộc tính `spc` của DrawingML tính bằng 1/100 pt.
    """
    try:
        rpr = run._r.get_or_add_rPr()
        rpr.set("spc", str(int(spacing_pt * 100)))
    except Exception:  # noqa: BLE001
        pass


class PPTXMorphGeneratorService:
    """Service chuyển đổi dữ liệu PresentationResponse sang tệp .pptx hoàn chỉnh."""

    def __init__(self, data: PresentationResponse) -> None:
        self.data = data
        self.prs = Presentation()

        # Thiết lập kích thước slide theo tỉ lệ
        if self.data.aspect_ratio == "4:3":
            self.slide_width_in = 10.0
            self.slide_height_in = 7.5
        else:  # Mặc định 16:9 Widescreen
            self.slide_width_in = 13.333
            self.slide_height_in = 7.5

        self.prs.slide_width = Inches(self.slide_width_in)
        self.prs.slide_height = Inches(self.slide_height_in)
        self.blank_layout = self.prs.slide_layouts[6]

        self.palette = STYLE_PALETTES.get(
            self.data.style, STYLE_PALETTES["Futuristic"]
        )

    def _pct_to_inches(
        self, x_pct: float, y_pct: float, w_pct: float, h_pct: float
    ) -> Tuple[Emu, Emu, Emu, Emu]:
        """Quy đổi tọa độ % màn hình sang đơn vị Inches (EMU) của PowerPoint.

        Kéo hộp tràn lề về trong khung hình, ưu tiên GIỮ NGUYÊN kích thước.
        """
        w = max(0.05, min(w_pct, 100.0))
        h = max(0.05, min(h_pct, 100.0))
        x = min(max(0.0, x_pct), max(0.0, 100.0 - w))
        y = min(max(0.0, y_pct), max(0.0, 100.0 - h))

        left = Inches((x / 100.0) * self.slide_width_in)
        top = Inches((y / 100.0) * self.slide_height_in)
        width = Inches((w / 100.0) * self.slide_width_in)
        height = Inches((h / 100.0) * self.slide_height_in)
        return left, top, width, height

    def _set_slide_background(self, slide, bg_hex: Optional[str]) -> None:
        """Tô màu nền toàn diện cho slide."""
        color = hex_to_rgb(bg_hex, RGBColor(10, 12, 18))
        bg = slide.background
        fill = bg.fill
        fill.solid()
        fill.fore_color.rgb = color

    def _write_speaker_notes(self, slide, slide_data: Slide) -> None:
        """Ghi lời dẫn người thuyết trình vào notes slide (khung Notes của PowerPoint)."""
        if not slide_data.speaker_notes:
            return
        try:
            slide.notes_slide.notes_text_frame.text = slide_data.speaker_notes
        except Exception as exc:  # noqa: BLE001
            import logging
            logging.getLogger("exoticmorph.generator").warning(
                "Không ghi được speaker notes cho slide %d: %s",
                slide_data.slide_number, exc,
            )

    def _alignment(self, align: Optional[str]) -> PP_ALIGN:
        if align == "center":
            return PP_ALIGN.CENTER
        if align == "right":
            return PP_ALIGN.RIGHT
        return PP_ALIGN.LEFT

    @staticmethod
    def _body_font_size(title_size: int) -> float:
        """Cỡ chữ thân bài co giãn theo cỡ chữ tiêu đề để giữ phân cấp thị giác."""
        if title_size >= 24:
            return 14.0
        if title_size >= 18:
            return 12.0
        if title_size >= 15:
            return 11.0
        if title_size >= 13:
            return 10.0
        return 9.5

    # ==========================================================================
    # CÁC LOẠI PHẦN TỬ
    # ==========================================================================
    def _add_heading(self, slide, elem: SlideElement) -> None:
        """Tiêu đề chính — in đậm, cỡ lớn, độ tương phản cao."""
        left, top, width, height = self._pct_to_inches(elem.x, elem.y, elem.width, elem.height)
        tx_box = slide.shapes.add_textbox(left, top, width, height)
        tf = tx_box.text_frame
        tf.word_wrap = True
        tf.margin_left = tf.margin_top = tf.margin_right = tf.margin_bottom = 0
        p = tf.paragraphs[0]
        p.text = elem.content
        p.font.bold = True
        p.font.size = Pt(elem.font_size or 24)
        p.font.color.rgb = hex_to_rgb(elem.text_color, RGBColor(255, 255, 255))
        p.font.name = "Segoe UI"
        set_shape_morph_id(tx_box, elem.morph_id)

    def _add_kicker(self, slide, elem: SlideElement) -> None:
        """Nhãn mục (kicker) in hoa, có tracking — thể hiện vị trí trong mạch kể chuyện."""
        left, top, width, height = self._pct_to_inches(elem.x, elem.y, elem.width, elem.height)
        tx_box = slide.shapes.add_textbox(left, top, width, height)
        tf = tx_box.text_frame
        tf.word_wrap = True
        tf.margin_left = tf.margin_top = tf.margin_right = tf.margin_bottom = 0
        p = tf.paragraphs[0]
        run = p.add_run()
        run.text = elem.content.upper()
        run.font.bold = True
        run.font.size = Pt(elem.font_size or 12)
        run.font.color.rgb = hex_to_rgb(elem.text_color, RGBColor(200, 210, 230))
        run.font.name = "Segoe UI"
        _set_letter_spacing(run, 2.4)
        set_shape_morph_id(tx_box, elem.morph_id)

    def _add_footer(self, slide, elem: SlideElement) -> None:
        """Footer nhỏ — đồng bộ bộ nhận diện ở mọi slide."""
        left, top, width, height = self._pct_to_inches(elem.x, elem.y, elem.width, elem.height)
        tx_box = slide.shapes.add_textbox(left, top, width, height)
        tf = tx_box.text_frame
        tf.word_wrap = False
        tf.margin_left = tf.margin_top = tf.margin_right = tf.margin_bottom = 0
        p = tf.paragraphs[0]
        p.text = elem.content
        p.alignment = self._alignment(elem.align)
        p.font.size = Pt(elem.font_size or 9)
        p.font.color.rgb = hex_to_rgb(elem.text_color, RGBColor(150, 160, 175))
        p.font.name = "Segoe UI"
        set_shape_morph_id(tx_box, elem.morph_id)

    def _add_badge(self, slide, elem: SlideElement) -> None:
        """Pill tag / vòng tròn số thứ tự (oval khi shape_type='oval')."""
        left, top, width, height = self._pct_to_inches(elem.x, elem.y, elem.width, elem.height)
        mso = MSO_SHAPE.OVAL if elem.shape_type == "oval" else MSO_SHAPE.ROUNDED_RECTANGLE
        shape = slide.shapes.add_shape(mso, left, top, width, height)
        shape.fill.solid()
        shape.fill.fore_color.rgb = hex_to_rgb(elem.bg_color, RGBColor(139, 92, 246))
        shape.line.fill.background()

        tf = shape.text_frame
        tf.word_wrap = False
        tf.margin_left = tf.margin_top = tf.margin_right = tf.margin_bottom = 0
        p = tf.paragraphs[0]
        p.text = elem.content
        p.alignment = PP_ALIGN.CENTER
        p.font.bold = True
        p.font.size = Pt(elem.font_size or 11)
        p.font.color.rgb = hex_to_rgb(elem.text_color, RGBColor(255, 255, 255))
        p.font.name = "Segoe UI"
        set_shape_morph_id(shape, elem.morph_id)

    def _add_accent(self, slide, elem: SlideElement) -> None:
        """Hình trang trí (đường nối lộ trình) — tô màu, không chữ."""
        left, top, width, height = self._pct_to_inches(elem.x, elem.y, elem.width, elem.height)
        mso = MSO_SHAPE.OVAL if elem.shape_type == "oval" else MSO_SHAPE.RECTANGLE
        shape = slide.shapes.add_shape(mso, left, top, width, height)
        shape.fill.solid()
        shape.fill.fore_color.rgb = hex_to_rgb(elem.bg_color, RGBColor(70, 78, 100))
        shape.line.fill.background()
        set_shape_morph_id(shape, elem.morph_id)

    def _add_card(self, slide, elem: SlideElement, is_primary: bool) -> None:
        """Thẻ nội dung 2 phần: tiêu đề (thông điệp cụ thể) + đoạn diễn giải chi tiết.

        - Nền tối sang trọng, viền mảnh.
        - Thanh accent trên đỉnh (màu nhận diện của thẻ), dày hơn cho thẻ chính.
        - Tiêu đề đậm, thân bài tương phản cao với khoảng cách dòng thoáng.
        """
        left, top, width, height = self._pct_to_inches(elem.x, elem.y, elem.width, elem.height)
        accent_rgb = hex_to_rgb(elem.accent_color, RGBColor(16, 185, 129))

        # --- Thân thẻ (vẽ trước, nằm dưới thanh accent) ---
        shape = slide.shapes.add_shape(
            MSO_SHAPE.ROUNDED_RECTANGLE, left, top, width, height
        )
        shape.fill.solid()
        shape.fill.fore_color.rgb = hex_to_rgb(elem.bg_color, RGBColor(20, 24, 39))
        if elem.border_color:
            shape.line.color.rgb = hex_to_rgb(elem.border_color, RGBColor(40, 46, 66))
            shape.line.width = Pt(1.0)
        else:
            shape.line.fill.background()

        # --- Thanh accent trên đỉnh (vẽ sau để nổi trên nền thẻ) ---
        bar_h = 0.09 if is_primary else 0.05
        bar = slide.shapes.add_shape(
            MSO_SHAPE.RECTANGLE,
            left + Inches(0.08), top + Inches(0.045), width - Inches(0.16), Inches(bar_h),
        )
        bar.fill.solid()
        bar.fill.fore_color.rgb = accent_rgb
        bar.line.fill.background()
        set_shape_morph_id(bar, f"{elem.morph_id}_accent")

        tf = shape.text_frame
        tf.word_wrap = True
        tf.margin_left = Inches(0.24)
        tf.margin_right = Inches(0.24)
        tf.margin_top = Inches(0.30 if is_primary else 0.26)
        tf.margin_bottom = Inches(0.18)

        title_size = int(elem.font_size or 15)

        # 1) Tiêu đề — thông điệp cụ thể, in đậm, tương phản cao.
        p_title = tf.paragraphs[0]
        p_title.text = elem.content
        p_title.font.bold = True
        p_title.font.size = Pt(title_size)
        p_title.font.color.rgb = hex_to_rgb(elem.text_color, RGBColor(255, 255, 255))
        p_title.font.name = "Segoe UI"

        # 2) Đoạn diễn giải chi tiết (2-3 câu) — màu phụ, khoảng cách dòng thoáng.
        if elem.sub_text:
            body = elem.sub_text.strip()
            p_body = tf.add_paragraph()
            p_body.space_before = Pt(8)
            p_body.text = body
            p_body.font.size = Pt(self._body_font_size(title_size))
            p_body.font.color.rgb = hex_to_rgb(self.palette.get("sub_text"), RGBColor(165, 175, 195))
            p_body.font.name = "Segoe UI"
            p_body.line_spacing = 1.14

        set_shape_morph_id(shape, elem.morph_id)

    def _add_element_to_slide(self, slide, elem: SlideElement, is_primary: bool = False) -> None:
        """Phân luồng theo loại phần tử."""
        if elem.type == "heading":
            self._add_heading(slide, elem)
        elif elem.type == "kicker":
            self._add_kicker(slide, elem)
        elif elem.type == "footer":
            self._add_footer(slide, elem)
        elif elem.type == "badge":
            self._add_badge(slide, elem)
        elif elem.type == "accent":
            self._add_accent(slide, elem)
        else:
            # card / metric / text / shape mặc định dùng kiểu thẻ nội dung.
            self._add_card(slide, elem, is_primary)

    def build_presentation(self) -> io.BytesIO:
        """Dựng toàn bộ slide, chèn Morph XML transitions và xuất ra BytesIO."""
        if not self.data.slides:
            raise ValueError("Dữ liệu bài trình chiếu trống: không có slide nào để dựng file PPTX.")

        for slide_idx, slide_data in enumerate(self.data.slides):
            slide = self.prs.slides.add_slide(self.blank_layout)
            self._set_slide_background(slide, slide_data.bg_color)
            self._write_speaker_notes(slide, slide_data)

            # Xác định thẻ chính (primary) = thẻ đầu tiên trong danh sách (nếu có >= 2 thẻ).
            card_elements = [e for e in slide_data.elements if e.type in ("card", "text", "shape", "metric")]
            primary_id = card_elements[0].id if len(card_elements) >= 2 else None

            for elem in slide_data.elements:
                self._add_element_to_slide(slide, elem, is_primary=(elem.id == primary_id))

            # Kích hoạt hiệu ứng Morph cho tất cả slide từ slide 2 trở đi.
            if slide_idx >= 1:
                enable_morph_transition(
                    slide=slide,
                    duration_ms=MORPH_DURATION_MS,
                    morph_option="byObject",
                    advance_on_click=True,
                )

        buffer = io.BytesIO()
        self.prs.save(buffer)
        buffer.seek(0)
        return buffer


def build_pptx_from_schema(data: PresentationResponse) -> io.BytesIO:
    """Hàm helper tiện ích dựng file PPTX từ PresentationResponse."""
    service = PPTXMorphGeneratorService(data)
    return service.build_presentation()
