"""
Pydantic Schemas for Slide Generation & LLM Structured Outputs
~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~
Định nghĩa cấu trúc dữ liệu nghiêm ngặt cho yêu cầu, phản hồi và định dạng JSON
trả về từ LLM (OpenAI GPT-4o / Gemini 1.5 Pro).
"""

from typing import List, Optional, Literal
from pydantic import BaseModel, Field


# Các loại phần tử trực quan hỗ trợ trên slide
SlideElementType = Literal["text", "shape", "card", "metric", "heading", "badge"]

# Tỉ lệ slide
AspectRatioType = Literal["16:9", "4:3"]

# Phong cách đồ họa
StyleType = Literal["Futuristic", "Minimal", "Corporate", "Creative"]


class SlideElement(BaseModel):
    """Đại diện cho một phần tử đơn lẻ trên slide (thẻ, văn bản, số liệu, hình khối).
    
    Tọa độ x, y, width, height được tính theo % chiều rộng và chiều cao màn hình (0.0 -> 100.0).
    Thuộc tính `morph_id` BẮT BUỘC giữ nguyên giữa các slide nếu đối tượng cần biến đổi hình ảnh mượt mà.
    """

    id: str = Field(
        description="Mã định danh duy nhất của phần tử trong slide hiện tại"
    )
    type: SlideElementType = Field(
        default="card",
        description="Loại phần tử: 'heading' | 'text' | 'card' | 'metric' | 'shape' | 'badge'",
    )
    content: str = Field(
        description="Nội dung văn bản chính hiển thị trên phần tử"
    )
    x: float = Field(
        ge=0.0,
        le=100.0,
        description="Vị trí tọa độ X (% chiều rộng slide từ 0.0 đến 100.0)",
    )
    y: float = Field(
        ge=0.0,
        le=100.0,
        description="Vị trí tọa độ Y (% chiều cao slide từ 0.0 đến 100.0)",
    )
    width: float = Field(
        ge=1.0,
        le=100.0,
        description="Độ rộng phần tử (% chiều rộng slide)",
    )
    height: float = Field(
        ge=1.0,
        le=100.0,
        description="Chiều cao phần tử (% chiều cao slide)",
    )
    bg_color: Optional[str] = Field(
        default="#1E2230",
        description="Mã màu nền Hex (ví dụ: '#1E2230', '#10B981', '#F97316')",
    )
    text_color: Optional[str] = Field(
        default="#FFFFFF",
        description="Mã màu chữ Hex (ví dụ: '#FFFFFF', '#94A3B8')",
    )
    morph_id: str = Field(
        description="ID liên kết Morph duy nhất (ví dụ: 'kpi_card_1'). Các shape ở các slide tiếp theo có cùng morph_id sẽ tự động biến đổi vị trí và kích thước!"
    )
    font_size: Optional[int] = Field(
        default=None,
        description="Kích thước font chữ (Pt) gợi ý",
    )
    shape_type: Optional[str] = Field(
        default="rounded_rectangle",
        description="Loại hình khối: 'rounded_rectangle' | 'rectangle' | 'circle'",
    )
    border_color: Optional[str] = Field(
        default=None,
        description="Mã màu viền Hex nếu có",
    )
    label: Optional[str] = Field(
        default=None,
        description="Nhãn phụ hoặc tiêu đề thẻ (nếu là dạng card/metric)",
    )
    sub_text: Optional[str] = Field(
        default=None,
        description="Văn bản phụ hoặc thông số chi tiết",
    )


class Slide(BaseModel):
    """Cấu trúc một slide hoàn chỉnh chứa danh sách các phần tử Morph."""

    slide_number: int = Field(
        ge=1,
        description="Thứ tự slide bắt đầu từ 1",
    )
    title: str = Field(
        description="Tiêu đề chính của slide"
    )
    subtitle: Optional[str] = Field(
        default=None,
        description="Tiêu đề phụ hoặc thông điệp dẫn dắt",
    )
    morph_description: Optional[str] = Field(
        default=None,
        description="Mô tả chuyển động Morph từ slide trước sang slide này",
    )
    bg_color: Optional[str] = Field(
        default="#0E1017",
        description="Mã màu nền slide Hex (mặc định Dark Mode '#0E1017')",
    )
    elements: List[SlideElement] = Field(
        default_factory=list,
        description="Danh sách các phần tử trực quan trên slide",
    )


class PresentationResponse(BaseModel):
    """Cấu trúc dữ liệu toàn bộ bài trình chiếu trả về từ LLM."""

    topic: str = Field(
        description="Chủ đề bài thuyết trình"
    )
    style: StyleType = Field(
        default="Futuristic",
        description="Phong cách thiết kế",
    )
    aspect_ratio: AspectRatioType = Field(
        default="16:9",
        description="Tỉ lệ khung hình bài thuyết trình",
    )
    total_slides: int = Field(
        ge=1,
        description="Tổng số lượng slide",
    )
    slides: List[Slide] = Field(
        description="Danh sách các slide theo đúng thứ tự"
    )
    morph_strategy: Optional[str] = Field(
        default=None,
        description="Chiến lược chuyển động hình học tổng thể",
    )


class GenerateRequest(BaseModel):
    """Dữ liệu payload từ client gửi lên API /api/v1/generate."""

    prompt: str = Field(
        min_length=3,
        description="Mô tả nội dung ý tưởng cần tạo bài trình chiếu",
        examples=["Tạo bài thuyết trình Pitch Deck gọi vốn 1 triệu USD cho startup AI SaaS"],
    )
    num_slides: int = Field(
        default=5,
        ge=1,
        le=20,
        description="Số lượng slide mong muốn (thường là 3, 5, 10)",
        examples=[5],
    )
    style: StyleType = Field(
        default="Futuristic",
        description="Phong cách thiết kế: 'Futuristic' | 'Minimal' | 'Corporate' | 'Creative'",
        examples=["Futuristic"],
    )
    aspect_ratio: AspectRatioType = Field(
        default="16:9",
        description="Tỉ lệ slide: '16:9' hoặc '4:3'",
        examples=["16:9"],
    )
    language: str = Field(
        default="vi",
        description="Ngôn ngữ nội dung: 'vi' (Tiếng Việt) hoặc 'en' (Tiếng Anh)",
        examples=["vi"],
    )
