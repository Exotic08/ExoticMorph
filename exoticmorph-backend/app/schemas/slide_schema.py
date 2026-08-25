"""
Pydantic Schemas for Slide Generation & LLM Structured Outputs
~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~
TÁCH BIỆT TRÁCH NHIỆM (Separation of Concerns):

1. **LLM Content Schema** (cho AI sáng tạo — KHÔNG có tọa độ hình học):
   - `ContentCard`       : một thẻ nội dung (morph_id, title, body, color_theme, order)
   - `RawSlideContent`   : một slide thô (slide_number, slide_title, cards)
   - `LLMOutput`         : toàn bộ output của LLM (topic, slides)

2. **Laid-Out Slide Schema** (cho Python Geometry Engine tính toán):
   - `SlideElement`      : phần tử đã có tọa độ chính xác (x, y, w, h)
   - `Slide`             : slide đã được Layout Engine xử lý xong
   - `PresentationResponse`: toàn bộ bài trình chiếu với đầy đủ hình học, sẵn sàng dựng PPTX

QUY TẮC VÀNG:
   - LLM KHÔNG BAO GIỜ được trả về x, y, width, height. Python tính mọi thứ.
   - LLM chỉ trả về: chữ (nội dung), ý tưởng (title/body), màu (color_theme),
     và morph_id (để giữ liên kết Morph giữa các slide).
"""

from typing import List, Optional, Literal
from pydantic import BaseModel, ConfigDict, Field, field_validator


# LLM Strict Models: từ chối MỌI trường thừa (vd: LLM cố trả về x, y, width, height)
_LLM_STRICT = ConfigDict(extra="forbid")


# ==============================================================================
# 1. LLM STRICT CONTENT SCHEMA — Output của AI, KHÔNG CÓ TỌA ĐỘ
# ==============================================================================

class ContentCard(BaseModel):
    """Một thẻ nội dung do LLM sinh ra — CHỈ chứa nội dung sáng tạo, KHÔNG có geometry.

    Layout Engine sẽ dùng `order` để sắp xếp và tự tính x, y, width, height.
    `morph_id` BẮT BUỘC giữ nguyên giữa slide N và slide N+1 nếu cùng một
    đối tượng cần hiệu ứng Morph chuyển động.
    """

    model_config = _LLM_STRICT

    morph_id: str = Field(
        ...,
        min_length=1,
        max_length=80,
        description=(
            "ID liên kết Morph duy nhất (ví dụ: 'core_card', 'col_1', 'kpi_roi'). "
            "PHẢI giữ nguyên giá trị này giữa slide N và slide N+1 cho cùng một "
            "đối tượng để PowerPoint tự động morph chuyển động."
        ),
    )
    title: str = Field(
        ...,
        min_length=3,
        max_length=80,
        description="Tiêu đề tự nhiên dài 3-6 từ, chứa thuật ngữ thực tế của chủ đề.",
    )
    description: str = Field(
        ..., min_length=150, max_length=450,
        description="Đoạn văn bắt buộc 30-50 từ, chứa dữ kiện hoặc ví dụ cụ thể.",
    )

    @field_validator("title")
    @classmethod
    def title_word_count(cls, value: str) -> str:
        if not 3 <= len(value.split()) <= 6:
            raise ValueError("title phải gồm 3-6 từ")
        return value

    @field_validator("description")
    @classmethod
    def description_word_count(cls, value: str) -> str:
        if not 30 <= len(value.split()) <= 50:
            raise ValueError("description phải gồm 30-50 từ")
        return value

    @property
    def body(self) -> str:
        """Tương thích ngược với Layout Engine; dữ liệu chuẩn là description."""
        return self.description
    color_theme: str = Field(
        ...,
        min_length=4,
        max_length=7,
        pattern=r"^#?[0-9A-Fa-f]{6}$",
        description="Mã màu nền thẻ dạng Hex (ví dụ: '#1E2235', '#8B5CF6').",
    )
    order: int = Field(
        ...,
        ge=0,
        le=20,
        description="Thứ tự của thẻ trong slide (0 = trái nhất / trên cùng, tăng dần).",
    )


class RawSlideContent(BaseModel):
    """Một slide thô do LLM trả về — chỉ có nội dung và danh sách thẻ.

    Layout Engine sẽ tự động:
      - Chia lưới dựa trên số lượng cards
      - Tính tọa độ x, y, width, height cho từng thẻ
      - Thêm badge, tiêu đề, màu nền theo style
    """

    model_config = _LLM_STRICT

    slide_number: int = Field(
        ...,
        ge=1,
        description="Thứ tự slide (bắt đầu từ 1, liên tục tăng dần)",
    )
    slide_title: str = Field(
        ...,
        min_length=1,
        max_length=200,
        description="Tiêu đề chính của slide, hiển thị ở vùng header phía trên các thẻ",
    )
    cards: List[ContentCard] = Field(
        ...,
        min_length=1,
        max_length=6,
        description="Danh sách các thẻ nội dung trong slide (1-6 thẻ). Layout Engine sẽ tự chia lưới.",
    )


class LLMOutput(BaseModel):
    """Định dạng JSON DUY NHẤT mà LLM được phép trả về.

    KHÔNG CÓ x, y, width, height ở bất kỳ đâu. Python Geometry Engine sẽ
    tính toàn bộ hình học sau khi LLM trả về nội dung.
    """

    model_config = _LLM_STRICT

    topic: str = Field(
        ...,
        min_length=1,
        max_length=300,
        description="Chủ đề tổng thể của bài trình chiếu",
    )
    slides: List[RawSlideContent] = Field(
        ...,
        min_length=1,
        max_length=30,
        description="Danh sách các slide (đúng số lượng người dùng yêu cầu)",
    )


# ==============================================================================
# 2. LAID-OUT SCHEMA — Sau khi Layout Engine tính toán hình học
#    (Được dùng bởi ppt_builder.py để dựng file PPTX)
# ==============================================================================

SlideElementType = Literal["text", "shape", "card", "metric", "heading", "badge"]
AspectRatioType = Literal["16:9", "4:3"]
StyleType = Literal["Futuristic", "Minimal", "Corporate", "Creative"]

MAX_ELEMENTS_PER_SLIDE = 40
MAX_SLIDES_PER_PRESENTATION = 30


class SlideElement(BaseModel):
    """Đại diện cho một phần tử đã có tọa độ CHÍNH XÁC trên slide.

    Tọa độ x, y, width, height được tính theo % (0.0 -> 100.0) của slide
    DO PYTHON LAYOUT ENGINE tính toán — LLM KHÔNG đụng tới.
    """

    id: str = Field(description="Mã định danh duy nhất của phần tử trong slide hiện tại")
    type: SlideElementType = Field(default="card")
    content: str = Field(default="")
    x: float = Field(ge=0.0, le=100.0)
    y: float = Field(ge=0.0, le=100.0)
    width: float = Field(ge=1.0, le=100.0)
    height: float = Field(ge=1.0, le=100.0)
    bg_color: Optional[str] = Field(default="#1E2230")
    text_color: Optional[str] = Field(default="#FFFFFF")
    morph_id: str = Field(default="")
    font_size: Optional[int] = Field(default=None, ge=6, le=200)
    shape_type: Optional[str] = Field(default="rounded_rectangle")
    border_color: Optional[str] = Field(default=None)
    label: Optional[str] = Field(default=None)
    sub_text: Optional[str] = Field(default=None)


class Slide(BaseModel):
    """Cấu trúc một slide HOÀN CHỈNH, đã có đầy đủ tọa độ hình học."""

    slide_number: int = Field(ge=1)
    title: str = Field(default="")
    subtitle: Optional[str] = Field(default=None)
    speaker_notes: Optional[str] = Field(default=None, max_length=2000)
    morph_description: Optional[str] = Field(default=None)
    bg_color: Optional[str] = Field(default="#0E1017")
    elements: List[SlideElement] = Field(
        default_factory=list, max_length=MAX_ELEMENTS_PER_SLIDE
    )


class PresentationResponse(BaseModel):
    """Toàn bộ bài trình chiếu, sẵn sàng để build_presentation() dựng PPTX."""

    topic: str = Field(default="")
    style: StyleType = Field(default="Futuristic")
    aspect_ratio: AspectRatioType = Field(default="16:9")
    total_slides: int = Field(ge=1)
    slides: List[Slide] = Field(min_length=1, max_length=MAX_SLIDES_PER_PRESENTATION)
    morph_strategy: Optional[str] = Field(default=None)


# ==============================================================================
# 3. API REQUEST SCHEMA — Payload từ client
# ==============================================================================

class GenerateRequest(BaseModel):
    """Dữ liệu payload từ client gửi lên API /api/v1/generate."""

    prompt: str = Field(
        min_length=3,
        max_length=4000,
        description="Mô tả nội dung ý tưởng cần tạo bài trình chiếu",
        examples=["Tạo bài thuyết trình Pitch Deck gọi vốn 1 triệu USD cho startup AI SaaS"],
    )
    num_slides: int = Field(
        default=5, ge=1, le=20,
        description="Số lượng slide mong muốn (thường là 3, 5, 10)",
    )
    style: StyleType = Field(
        default="Futuristic",
        description="Phong cách thiết kế: 'Futuristic' | 'Minimal' | 'Corporate' | 'Creative'",
    )
    aspect_ratio: AspectRatioType = Field(default="16:9")
    language: str = Field(
        default="vi", max_length=10,
        description="Ngôn ngữ nội dung: 'vi' hoặc 'en'",
    )
    include_speaker_notes: bool = Field(default=True)
