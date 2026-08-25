"""
PPTX Generator Service for ExoticMorph
~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~
Đọc dữ liệu có cấu trúc từ LLM (PresentationResponse), chuyển đổi tọa độ % sang Inches,
dựng slide bằng python-pptx và can thiệp OpenXML để kích hoạt hiệu ứng Morph.

Nâng cấp trong đợt rework:
- Validate dữ liệu vào (từ chối danh sách slide rỗng với thông báo rõ ràng thay vì
  để IndexError/KeyError bùng nổ thành HTTP 500 ở tầng routes).
- Kéo tọa độ tràn lề về trong khung hình (ưu tiên giữ nguyên kích thước hộp).
- Ghi Speaker Notes thật vào file .pptx (notes slide của PowerPoint).
- Dọn import thừa, chú thích rõ ràng phần quản lý bộ nhớ (BytesIO).
"""

import io
from typing import Optional, Tuple

from pptx import Presentation
from pptx.util import Inches, Pt
from pptx.enum.shapes import MSO_SHAPE
from pptx.enum.text import PP_ALIGN
from pptx.dml.color import RGBColor

from app.schemas.slide_schema import PresentationResponse, Slide, SlideElement
from app.core.xml_helper import enable_morph_transition, set_shape_morph_id


def hex_to_rgb(hex_str: Optional[str], default: RGBColor = RGBColor(255, 255, 255)) -> RGBColor:
    """Chuyển đổi chuỗi Hex (ví dụ '#8B5CF6' hoặc '8B5CF6') sang RGBColor của python-pptx.

    Chịu lỗi: chuỗi rỗng, sai độ dài, ký tự hex không hợp lệ -> trả màu default
    (LLLM hay trả màu "transparent" hoặc tên màu CSS nên phải phòng thủ).
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

    def _pct_to_inches(
        self, x_pct: float, y_pct: float, w_pct: float, h_pct: float
    ) -> Tuple[int, int, int, int]:
        """Quy đổi tọa độ % màn hình sang đơn vị Inches (EMU) của PowerPoint.

        FIX: hộp bị đẩy tràn lề (x + w > 100%) sẽ được kéo về trong khung hình,
        ưu tiên GIỮ NGUYÊN kích thước và dịch góc trên-trái (đảm bảo đối tượng
        morph không bị phóng to/thu nhỏ bất ngờ khi PowerPoint render).
        """
        w = max(1.0, min(w_pct, 100.0))
        h = max(1.0, min(h_pct, 100.0))
        # Dịch góc trên-trái sao cho cạnh phải/dưới không vượt 100%.
        x = min(max(0.0, x_pct), max(0.0, 100.0 - w))
        y = min(max(0.0, y_pct), max(0.0, 100.0 - h))

        left = Inches((x / 100.0) * self.slide_width_in)
        top = Inches((y / 100.0) * self.slide_height_in)
        width = Inches((w / 100.0) * self.slide_width_in)
        height = Inches((h / 100.0) * self.slide_height_in)
        return left, top, width, height

    def _set_slide_background(self, slide, bg_hex: Optional[str]) -> None:
        """Tô màu nền toàn diện cho slide."""
        color = hex_to_rgb(bg_hex, RGBColor(14, 16, 23))
        bg = slide.background
        fill = bg.fill
        fill.solid()
        fill.fore_color.rgb = color

    def _write_speaker_notes(self, slide, slide_data: Slide) -> None:
        """Ghi lời dẫn người thuyết trình vào notes slide (khung Notes của PowerPoint).

        Bọc try/except: notes slide chỉ là tính năng phụ, tuyệt đối không để lỗi
        notes làm hỏng toàn bộ file .pptx đã build.
        """
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

    def _add_element_to_slide(self, slide, elem: SlideElement) -> None:
        """Thêm một phần tử trực quan vào slide và gán Morph ID."""
        left, top, width, height = self._pct_to_inches(elem.x, elem.y, elem.width, elem.height)

        bg_rgb = hex_to_rgb(elem.bg_color, RGBColor(22, 25, 38))
        text_rgb = hex_to_rgb(elem.text_color, RGBColor(255, 255, 255))

        # Chọn loại hình khối tương ứng
        if elem.shape_type == "circle":
            mso_shape = MSO_SHAPE.OVAL
        elif elem.shape_type == "rectangle":
            mso_shape = MSO_SHAPE.RECTANGLE
        else:
            mso_shape = MSO_SHAPE.ROUNDED_RECTANGLE

        # Font size an toàn trong [6, 200] — schema đã chặn nhưng phòng hộ doubles.
        font_size = max(6, min(int(elem.font_size or 0), 200)) if elem.font_size else None

        # Trường hợp 1: Thẻ Heading trong suốt
        if elem.type == "heading":
            tx_box = slide.shapes.add_textbox(left, top, width, height)
            tf = tx_box.text_frame
            tf.word_wrap = True
            p = tf.paragraphs[0]
            p.text = elem.content
            p.font.bold = True
            p.font.size = Pt(font_size or 24)
            p.font.color.rgb = text_rgb
            p.font.name = "Segoe UI"

            # Gán Morph ID
            set_shape_morph_id(tx_box, elem.morph_id)
            return

        # Trường hợp 2: Badge / Pill Tag
        if elem.type == "badge":
            shape = slide.shapes.add_shape(MSO_SHAPE.ROUNDED_RECTANGLE, left, top, width, height)
            shape.fill.solid()
            shape.fill.fore_color.rgb = bg_rgb
            shape.line.color.rgb = bg_rgb

            tf = shape.text_frame
            tf.word_wrap = True
            p = tf.paragraphs[0]
            p.text = elem.content
            p.alignment = PP_ALIGN.CENTER
            p.font.bold = True
            p.font.size = Pt(font_size or 10)
            p.font.color.rgb = text_rgb
            p.font.name = "Segoe UI"

            set_shape_morph_id(shape, elem.morph_id)
            return

        # Trường hợp 3: Card / Metric Box / Shape tiêu chuẩn
        shape = slide.shapes.add_shape(mso_shape, left, top, width, height)
        shape.fill.solid()
        shape.fill.fore_color.rgb = bg_rgb

        # Viền nhẹ cho card
        if elem.border_color:
            shape.line.color.rgb = hex_to_rgb(elem.border_color, RGBColor(60, 65, 85))
            shape.line.width = Pt(1.5)
        else:
            shape.line.color.rgb = RGBColor(60, 65, 85)
            shape.line.width = Pt(1.0)

        tf = shape.text_frame
        tf.word_wrap = True
        tf.margin_left = Inches(0.15)
        tf.margin_right = Inches(0.15)
        tf.margin_top = Inches(0.15)
        tf.margin_bottom = Inches(0.15)

        # 1. Nhãn phụ Label nếu có
        if elem.label:
            p_label = tf.paragraphs[0]
            p_label.text = elem.label.upper()
            p_label.font.bold = True
            p_label.font.size = Pt(10)
            p_label.font.color.rgb = RGBColor(148, 163, 184)
            p_label.font.name = "Segoe UI"

            p_main = tf.add_paragraph()
            p_main.space_before = Pt(4)
        else:
            p_main = tf.paragraphs[0]

        # 2. Nội dung chính
        p_main.text = elem.content
        p_main.font.bold = True
        if elem.type == "metric":
            p_main.font.size = Pt(font_size or 32)
        else:
            p_main.font.size = Pt(font_size or 15)
        p_main.font.color.rgb = text_rgb
        p_main.font.name = "Segoe UI"

        # 3. Văn bản chi tiết Sub-text nếu có
        if elem.sub_text:
            lines = elem.sub_text.split("\n")
            for idx, line in enumerate(lines):
                if not line.strip():
                    continue
                p_sub = tf.add_paragraph()
                p_sub.text = line.strip()
                p_sub.font.size = Pt(10.5)
                p_sub.font.color.rgb = RGBColor(203, 213, 225)
                p_sub.font.name = "Segoe UI"
                p_sub.space_before = Pt(4 if idx == 0 else 2)

        # GÁN TIỀN TỐ '!!' VÀO XML CNVPR CỦA SHAPE CHO PPTX MORPH ENGINE
        set_shape_morph_id(shape, elem.morph_id)

    def build_presentation(self) -> io.BytesIO:
        """Dựng toàn bộ slide, chèn Morph XML transitions và xuất ra BytesIO.

        Về bộ nhớ: mỗi service instance sở hữu MỘT Presentation và MỘT buffer
        BytesIO; Python GC thu hồi toàn bộ sau khi request kết thúc (không giữ
        tham chiếu toàn cục nào) nên không xảy hiện tượng memory leak khi tạo
        nhiều slide / nhiều request liên tiếp.
        """
        if not self.data.slides:
            # FIX silent bug: từ chối sớm với thông báo rõ ràng thay vì để
            # IndexError phát sinh ở tầng routes (HTTP 500 chung chung).
            raise ValueError("Dữ liệu bài trình chiếu trống: không có slide nào để dựng file PPTX.")

        for slide_idx, slide_data in enumerate(self.data.slides):
            # Tạo slide mới
            slide = self.prs.slides.add_slide(self.blank_layout)

            # Tô màu nền
            self._set_slide_background(slide, slide_data.bg_color)

            # Ghi lời dẫn người thuyết trình (nếu có)
            self._write_speaker_notes(slide, slide_data)

            # Dựng các phần tử của slide
            for elem in slide_data.elements:
                self._add_element_to_slide(slide, elem)

            # KÍCH HOẠT HIỆU ỨNG MORPH CHO TẤT CẢ CÁC SLIDE TỪ SLIDE 2 TRỞ ĐI
            if slide_idx >= 1:
                enable_morph_transition(
                    slide=slide,
                    duration_ms=1250,
                    morph_option="byObject",
                    advance_on_click=True,
                )

        # Lưu vào bộ nhớ RAM (buffer được seek(0) để caller đọc từ đầu).
        buffer = io.BytesIO()
        self.prs.save(buffer)
        buffer.seek(0)
        return buffer


def build_pptx_from_schema(data: PresentationResponse) -> io.BytesIO:
    """Hàm helper tiện ích dựng file PPTX từ PresentationResponse."""
    service = PPTXMorphGeneratorService(data)
    return service.build_presentation()
