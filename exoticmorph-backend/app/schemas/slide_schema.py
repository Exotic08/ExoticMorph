"""
Pydantic Schemas for Slide Generation & LLM Structured Outputs
~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~
TÁCH BIỆT TRÁCH NHIỆM (Separation of Concerns):

1. **LLM Content Schema** (cho AI sáng tạo — KHÔNG có tọa độ hình học):
   - `LayoutType`        : Enum 5 kiểu bố cục đa dạng (CARDS_ROW, SPLIT_HERO, STAT_GRID, TIMELINE_STEPS, GRID_2X2)
   - `ContentCard`       : một thẻ nội dung (morph_id, title, description, color_theme, order)
   - `SlideData`         : một slide thô (slide_number, section, slide_title, layout_type, cards)
   - `RawSlideContent`   : bí danh tương thích ngược của SlideData
   - `LLMOutput`         : toàn bộ output của LLM (topic, slides)

2. **Laid-Out Slide Schema** (cho Python Geometry Engine tính toán):
   - `SlideElement`      : phần tử đã có tọa độ chính xác (x, y, w, h)
   - `Slide`             : slide đã được Layout Engine xử lý xong (kèm layout_type)
   - `PresentationResponse`: toàn bộ bài trình chiếu với đầy đủ hình học, sẵn sàng dựng PPTX

QUY TẮC VÀNG:
   - LLM KHÔNG BAO GIỜ được trả về x, y, width, height. Python tính mọi thứ.
   - LLM chỉ trả về: chữ (nội dung), ý tưởng (title/description), màu (color_theme),
     morph_id (để giữ liên kết Morph giữa các slide) và lựa chọn layout_type phù hợp ngữ cảnh.
"""

from enum import Enum
from typing import Any, List, Optional, Literal
from pydantic import BaseModel, ConfigDict, Field, field_validator


# LLM Strict Models: từ chối MỌI trường thừa (vd: LLM cố trả về x, y, width, height)
_LLM_STRICT = ConfigDict(extra="forbid")


# ==============================================================================
# 0. DYNAMIC LAYOUT TYPES ENUM
# ==============================================================================

class LayoutType(str, Enum):
    """5 kiểu bố cục đa dạng cho slide trình chiếu (Dynamic Layout Diversity).

    - CARDS_ROW      : 2-3 thẻ nằm ngang (Layout mặc định truyền thống).
    - SPLIT_HERO     : Cột trái rộng (ý chính/Hero point), cột phải xếp 2 thẻ phụ.
    - STAT_GRID      : Slide nhấn mạnh số liệu (con số to nổi bật + label ngắn).
    - TIMELINE_STEPS : Tiến trình 3-4 bước theo chiều ngang.
    - GRID_2X2       : Lưới 4 thẻ chia đều 2 hàng x 2 cột.
    """

    CARDS_ROW = "CARDS_ROW"
    SPLIT_HERO = "SPLIT_HERO"
    STAT_GRID = "STAT_GRID"
    TIMELINE_STEPS = "TIMELINE_STEPS"
    GRID_2X2 = "GRID_2X2"


# Bảng ánh xạ linh hoạt hỗ trợ tương thích ngược (chấp nhận cả alias chữ thường/cũ)
_LAYOUT_ALIAS_MAP = {
    "CARDS_ROW": LayoutType.CARDS_ROW,
    "CARDS": LayoutType.CARDS_ROW,
    "FEATURES": LayoutType.CARDS_ROW,
    "COMPARE": LayoutType.CARDS_ROW,
    "SPLIT_HERO": LayoutType.SPLIT_HERO,
    "HERO": LayoutType.SPLIT_HERO,
    "SPLIT": LayoutType.SPLIT_HERO,
    "STAT_GRID": LayoutType.STAT_GRID,
    "STAT": LayoutType.STAT_GRID,
    "STATS": LayoutType.STAT_GRID,
    "METRICS": LayoutType.STAT_GRID,
    "METRICS_GRID": LayoutType.STAT_GRID,
    "TIMELINE_STEPS": LayoutType.TIMELINE_STEPS,
    "TIMELINE": LayoutType.TIMELINE_STEPS,
    "ROADMAP": LayoutType.TIMELINE_STEPS,
    "STEPS": LayoutType.TIMELINE_STEPS,
    "GRID_2X2": LayoutType.GRID_2X2,
    "GRID": LayoutType.GRID_2X2,
    "2X2": LayoutType.GRID_2X2,
}


def _coerce_layout_type(value: Any) -> LayoutType:
    """Chuẩn hóa giá trị layout_type về Enum chuẩn, không phân biệt hoa thường."""
    if isinstance(value, LayoutType):
        return value
    if isinstance(value, str):
        clean = value.strip().upper().replace("-", "_").replace(" ", "_")
        if clean in _LAYOUT_ALIAS_MAP:
            return _LAYOUT_ALIAS_MAP[clean]
        try:
            return LayoutType(clean)
        except ValueError:
            pass
    return LayoutType.CARDS_ROW


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
        min_length=1,
        max_length=120,
        description=(
            "Tiêu đề là MỘT THÔNG ĐIỆP CỤ THỂ (1-10 từ) hoặc con số/chỉ số định lượng nổi bật. "
            "Ví dụ ĐÚNG: 'Doanh thu tăng 35% nhờ mở rộng thị trường', '465 °C', '+35%'; SAI: 'Tình hình doanh thu'."
        ),
    )
    description: str = Field(
        ...,
        min_length=10,
        max_length=520,
        description=(
            "Đoạn diễn giải hoặc label ngắn (3-60 từ) giải thích rõ bản chất vấn đề, "
            "chứa dữ kiện định lượng, mốc thời gian, ví dụ hoặc quan hệ nhân quả."
        ),
    )

    @field_validator("title")
    @classmethod
    def title_word_count(cls, value: str) -> str:
        # Chấp nhận từ 1 từ (cho các con số đo lường như 465°C, +35%, 1.989×10³⁰kg) tới 15 từ
        words = value.split()
        if not 1 <= len(words) <= 15:
            raise ValueError("title phải gồm 1-15 từ")
        return value

    @field_validator("description")
    @classmethod
    def description_word_count(cls, value: str) -> str:
        # Chấp nhận từ label ngắn (3 từ) tới đoạn văn chi tiết (80 từ)
        words = value.split()
        if not 3 <= len(words) <= 80:
            raise ValueError("description phải gồm 3-80 từ")
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


class SlideData(BaseModel):
    """Một slide thô do LLM trả về — chỉ có nội dung, danh sách thẻ và lựa chọn layout_type.

    Layout Engine sẽ tự động:
      - Chia lưới dựa trên layout_type và số lượng cards
      - Tính tọa độ x, y, width, height cho từng thẻ
      - Thêm badge, tiêu đề, màu nền theo style
    """

    model_config = _LLM_STRICT

    slide_number: int = Field(
        ...,
        ge=1,
        description="Thứ tự slide (bắt đầu từ 1, liên tục tăng dần)",
    )
    section: str = Field(
        ...,
        min_length=0,
        max_length=60,
        description=(
            "Nhãn mục (kicker) ngắn gọn, viết HOA thể hiện vị trí slide trong mạch kể chuyện, "
            "ví dụ: 'VẤN ĐỀ', 'NGUYÊN NHÂN', 'GIẢI PHÁP', 'KẾT QUẢ', 'HÀNH ĐỘNG'. "
            "Không dùng nhãn sáo rỗng như 'Giới thiệu' hay 'Tổng quan'."
        ),
    )
    slide_title: str = Field(
        ...,
        min_length=1,
        max_length=200,
        description="Tiêu đề chính của slide — là một thông điệp/kết luận cụ thể, hiển thị ở vùng header phía trên các thẻ",
    )
    layout_type: LayoutType = Field(
        default=LayoutType.CARDS_ROW,
        description=(
            "Kiểu bố cục của slide: "
            "CARDS_ROW (2-3 thẻ nằm ngang), "
            "SPLIT_HERO (cột trái hero rộng + cột phải xếp 2 thẻ phụ), "
            "STAT_GRID (nhấn mạnh số liệu to nổi bật + label ngắn), "
            "TIMELINE_STEPS (tiến trình 3-4 bước ngang), "
            "GRID_2X2 (lưới 4 thẻ chia đều 2 hàng x 2 cột). "
            "Không được để 2 slide liên tiếp có cùng layout_type."
        ),
    )
    cards: List[ContentCard] = Field(
        ...,
        min_length=1,
        max_length=6,
        description="Danh sách các thẻ nội dung trong slide (1-6 thẻ). Layout Engine sẽ tự chia lưới theo layout_type.",
    )

    @field_validator("layout_type", mode="before")
    @classmethod
    def parse_layout_type(cls, value: Any) -> LayoutType:
        return _coerce_layout_type(value)


# Bí danh tương thích ngược hoàn toàn với tên gọi cũ
RawSlideContent = SlideData


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
    slides: List[SlideData] = Field(
        ...,
        min_length=1,
        max_length=30,
        description="Danh sách các slide (đúng số lượng người dùng yêu cầu)",
    )


# ==============================================================================
# 2. LAID-OUT SCHEMA — Sau khi Layout Engine tính toán hình học
#    (Được dùng bởi ppt_builder.py để dựng file PPTX)
# ==============================================================================

SlideElementType = Literal[
    "text", "shape", "card", "metric", "heading", "badge",
    "kicker", "footer", "connector", "accent",
]
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
    width: float = Field(ge=0.01, le=100.0)
    height: float = Field(ge=0.01, le=100.0)
    bg_color: Optional[str] = Field(default="#1E2230")
    text_color: Optional[str] = Field(default="#FFFFFF")
    morph_id: str = Field(default="")
    font_size: Optional[int] = Field(default=None, ge=6, le=200)
    shape_type: Optional[str] = Field(default="rounded_rectangle")
    border_color: Optional[str] = Field(default=None)
    label: Optional[str] = Field(default=None)
    sub_text: Optional[str] = Field(default=None)
    accent_color: Optional[str] = Field(default=None)
    step: Optional[int] = Field(default=None, ge=1, le=20)
    align: Optional[str] = Field(default=None, pattern="^(left|center|right)$")


class Slide(BaseModel):
    """Cấu trúc một slide HOÀN CHỈNH, đã có đầy đủ tọa độ hình học."""

    slide_number: int = Field(ge=1)
    title: str = Field(default="")
    section: str = Field(default="")
    subtitle: Optional[str] = Field(default=None)
    speaker_notes: Optional[str] = Field(default=None, max_length=2000)
    morph_description: Optional[str] = Field(default=None)
    bg_color: Optional[str] = Field(default="#0E1017")
    layout_type: LayoutType = Field(default=LayoutType.CARDS_ROW)
    elements: List[SlideElement] = Field(
        default_factory=list, max_length=MAX_ELEMENTS_PER_SLIDE
    )

    @field_validator("layout_type", mode="before")
    @classmethod
    def parse_layout_type(cls, value: Any) -> LayoutType:
        return _coerce_layout_type(value)


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
