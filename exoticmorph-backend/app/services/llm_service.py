"""
LLM Service Module for ExoticMorph
~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~
Tích hợp OpenAI GPT-4o và Google Gemini 1.5 Pro với Structured JSON Mode
để phân tích prompt, sinh dàn ý và tính toán tọa độ Morph cho từng slide.
"""

import json
import logging
from typing import Optional
from app.config import settings
from app.schemas.slide_schema import (
    GenerateRequest,
    PresentationResponse,
    Slide,
    SlideElement,
)

logger = logging.getLogger("exoticmorph.llm")

# ==============================================================================
# System Prompt: Master Motion Designer & Presentation Architect
# ==============================================================================
SYSTEM_PROMPT = """Bạn là một "Master Motion Designer & Presentation Architect" hàng đầu thế giới, chuyên gia thiết kế bài thuyết trình PowerPoint chuẩn OpenXML có hiệu ứng Morph chuyển động liền mạch.

NHIỆM VỤ CỦA BẠN:
Nhận chủ đề/prompt từ người dùng và thiết kế một bài thuyết trình hoàn chỉnh. Bạn phải tính toán chính xác bố cục không gian (tọa độ x, y, width, height từ 0.0 đến 100.0%) và đặc biệt là hệ thống liên kết MORPH ID giữa các slide.

QUY TẮC BẮT BUỘC VỀ HIỆU ỨNG MORPH (THE GOLDEN RULES OF MORPHING):
1. **BẢO TOÀN MORPH_ID LIÊN KẾT**: 
   - Để PowerPoint tự động biến đổi vật thể giữa Slide N và Slide N+1, hai phần tử tương ứng ở 2 slide BẮT BUỘC PHẢI DÙNG CHUNG MỘT `morph_id` (ví dụ: `card_kpi_1`, `hero_box`, `badge_status`).
   - Ví dụ: Ở Slide 1, một thẻ nằm ở trung tâm (x: 25, y: 30, w: 50, h: 40) với `morph_id: "core_card"`. Sang Slide 2, thẻ đó thu nhỏ và dạt sang góc trái (x: 5, y: 15, w: 25, h: 70) VẪN PHẢI GIỮ NGUYÊN `morph_id: "core_card"`.
2. **TỌA ĐỘ VÀ KHÔNG GIAN (% MÀN HÌNH)**:
   - Slide có kích thước 100% x 100%. Đảm bảo x + width <= 96% và y + height <= 96% để tránh tràn lề màn hình.
   - Khoảng lề an toàn (safe margin): x >= 5%, y >= 8%.
3. **MÀU SẮC & PHONG CÁCH (THEME PALETTE)**:
   - **Futuristic**: Nền `#090A0F`, Thẻ `#131622`, Chữ `#FFFFFF`, Điểm nhấn `#8B5CF6`, `#06B6D4`, `#EC4899`.
   - **Minimal**: Nền `#0F172A`, Thẻ `#1E293B`, Chữ `#F8FAFC`, Điểm nhấn `#6366F1`, `#38BDF8`.
   - **Corporate**: Nền `#0A1128`, Thẻ `#1C2541`, Chữ `#FFFFFF`, Điểm nhấn `#3A86FF`, `#10B981`.
   - **Creative**: Nền `#120A1F`, Thẻ `#241438`, Chữ `#FFFFFF`, Điểm nhấn `#D946EF`, `#F59E0B`.

CẤU TRÚC JSON TRẢ VỀ:
Trả về DUY NHẤT một JSON Object hợp lệ theo đúng cấu trúc Schema sau:
{
  "topic": string,
  "style": "Futuristic" | "Minimal" | "Corporate" | "Creative",
  "aspect_ratio": "16:9" | "4:3",
  "total_slides": number,
  "morph_strategy": string,
  "slides": [
    {
      "slide_number": number,
      "title": string,
      "subtitle": string,
      "morph_description": string,
      "bg_color": string (hex),
      "elements": [
        {
          "id": string,
          "type": "heading" | "text" | "card" | "metric" | "shape" | "badge",
          "content": string,
          "label": string | null,
          "sub_text": string | null,
          "x": number (0-100),
          "y": number (0-100),
          "width": number (0-100),
          "height": number (0-100),
          "bg_color": string (hex),
          "text_color": string (hex),
          "morph_id": string,
          "font_size": number | null,
          "shape_type": "rounded_rectangle" | "rectangle" | "circle",
          "border_color": string | null
        }
      ]
    }
  ]
}
"""


def generate_fallback_presentation(req: GenerateRequest) -> PresentationResponse:
    """Hàm sinh dữ liệu dự phòng thông minh (Heuristic Fallback Generator)
    khi chưa có API Key hoặc khi dịch vụ AI bên ngoài gặp sự cố mạng.
    Đảm bảo 100% hệ thống luôn hoạt động mượt mà và trả về dữ liệu đúng schema.
    """
    logger.info("Sử dụng Heuristic Fallback Generator cho prompt: %s", req.prompt[:60])
    
    num_slides = max(1, min(req.num_slides, 10))
    style = req.style
    
    # Bảng màu theo style
    palettes = {
        "Futuristic": {
            "bg": "#090A0F",
            "card1": "#161926",
            "card2": "#1E2235",
            "accent1": "#8B5CF6",
            "accent2": "#06B6D4",
            "accent3": "#EC4899",
            "text": "#FFFFFF",
            "sub": "#94A3B8"
        },
        "Minimal": {
            "bg": "#0F172A",
            "card1": "#1E293B",
            "card2": "#334155",
            "accent1": "#6366F1",
            "accent2": "#38BDF8",
            "accent3": "#10B981",
            "text": "#F8FAFC",
            "sub": "#CBD5E1"
        },
        "Corporate": {
            "bg": "#0A1128",
            "card1": "#141F36",
            "card2": "#1E2D4A",
            "accent1": "#2563EB",
            "accent2": "#10B981",
            "accent3": "#F59E0B",
            "text": "#FFFFFF",
            "sub": "#94A3B8"
        },
        "Creative": {
            "bg": "#120A1F",
            "card1": "#241438",
            "card2": "#341D4E",
            "accent1": "#D946EF",
            "accent2": "#F59E0B",
            "accent3": "#06B6D4",
            "text": "#FFFFFF",
            "sub": "#E2E8F0"
        }
    }
    p = palettes.get(style, palettes["Futuristic"])
    
    # Tạo tiêu đề sạch
    title = req.prompt.split("\n")[0].strip()
    if len(title) > 60:
        title = title[:60] + "..."
    if not title:
        title = "Chiến Lược Đột Phá AI ExoticMorph"
        
    slides: list[Slide] = []
    
    # ==================== SLIDE 1: COVER HERO ====================
    slides.append(
        Slide(
            slide_number=1,
            title=title,
            subtitle=f"Bản trình chiếu tối ưu hóa Morph tự động ({style} Style)",
            morph_description="Khối tiêu đề chính phóng to và 3 thẻ tóm tắt dạt sang 3 cột ở slide tiếp theo",
            bg_color=p["bg"],
            elements=[
                SlideElement(
                    id="s1_badge",
                    type="badge",
                    content="EXOTICMORPH AI ENGINE",
                    x=6.0, y=10.0, width=28.0, height=6.0,
                    bg_color=p["accent1"],
                    text_color="#FFFFFF",
                    morph_id="badge_header",
                    font_size=11,
                ),
                SlideElement(
                    id="s1_card_main",
                    type="card",
                    content=title,
                    label="TỔNG QUAN CHIẾN LƯỢC",
                    sub_text="Chuyển đổi số & Tự động hóa bài thuyết trình bằng Generative AI",
                    x=6.0, y=20.0, width=88.0, height=36.0,
                    bg_color=p["card1"],
                    text_color=p["text"],
                    morph_id="morph_card_main",
                    font_size=24,
                ),
                SlideElement(
                    id="s1_card_sub1",
                    type="card",
                    content="Tăng trưởng +45%",
                    label="Mục tiêu cốt lõi",
                    x=6.0, y=60.0, width=27.0, height=28.0,
                    bg_color=p["card2"],
                    text_color=p["text"],
                    morph_id="morph_col_1",
                    font_size=16,
                ),
                SlideElement(
                    id="s1_card_sub2",
                    type="card",
                    content="Kiến trúc Microservices",
                    label="Giải pháp kỹ thuật",
                    x=36.5, y=60.0, width=27.0, height=28.0,
                    bg_color=p["card2"],
                    text_color=p["text"],
                    morph_id="morph_col_2",
                    font_size=16,
                ),
                SlideElement(
                    id="s1_card_sub3",
                    type="card",
                    content="Go-to-Market Q4",
                    label="Lộ trình thương mại",
                    x=67.0, y=60.0, width=27.0, height=28.0,
                    bg_color=p["card2"],
                    text_color=p["text"],
                    morph_id="morph_col_3",
                    font_size=16,
                ),
            ]
        )
    )
    
    # ==================== SLIDE 2: EXPANDED COLUMNS ====================
    if num_slides >= 2:
        slides.append(
            Slide(
                slide_number=2,
                title="Phân Tích Chi Tiết 3 Trụ Cột Trọng Tâm",
                subtitle="Dữ liệu và giải pháp chuyển đổi liền mạch từ tổng quan",
                morph_description="3 Thẻ nhỏ ở đáy Slide 1 mở rộng toàn màn hình thành 3 cột chi tiết tại Slide 2",
                bg_color=p["bg"],
                elements=[
                    SlideElement(
                        id="s2_badge",
                        type="badge",
                        content="TRỤ CỘT CHIẾN LƯỢC",
                        x=6.0, y=10.0, width=24.0, height=6.0,
                        bg_color=p["accent2"],
                        text_color="#FFFFFF",
                        morph_id="badge_header",
                        font_size=11,
                    ),
                    SlideElement(
                        id="s2_card_1",
                        type="card",
                        content="Chỉ Số Tăng Trưởng & Traction",
                        label="TRỤ CỘT 01",
                        sub_text="• Doanh thu ARR đạt $12.5M (+45% YoY)\n• 1,200+ Doanh nghiệp Enterprise\n• Retention Rate duy trì mức 128%",
                        x=6.0, y=20.0, width=27.0, height=68.0,
                        bg_color=p["card1"],
                        text_color=p["text"],
                        morph_id="morph_col_1",  # CÙNG ID VỚI SLIDE 1
                        font_size=15,
                    ),
                    SlideElement(
                        id="s2_card_2",
                        type="card",
                        content="Kiến Trúc Hệ Thống & AI Core",
                        label="TRỤ CỘT 02",
                        sub_text="• Khả năng chịu tải 100K TPS\n• Tự động khớp tọa độ Morph XML\n• Pipeline biên dịch OpenXML < 3s",
                        x=36.5, y=20.0, width=27.0, height=68.0,
                        bg_color=p["card1"],
                        text_color=p["text"],
                        morph_id="morph_col_2",  # CÙNG ID VỚI SLIDE 1
                        font_size=15,
                    ),
                    SlideElement(
                        id="s2_card_3",
                        type="card",
                        content="Kế Hoạch Triển Khai & Phân Phối",
                        label="TRỤ CỘT 03",
                        sub_text="• Mở rộng thị trường APAC & US\n• Tích hợp trực tiếp Microsoft Office\n• Đào tạo chuyển giao công nghệ",
                        x=67.0, y=20.0, width=27.0, height=68.0,
                        bg_color=p["card1"],
                        text_color=p["text"],
                        morph_id="morph_col_3",  # CÙNG ID VỚI SLIDE 1
                        font_size=15,
                    ),
                ]
            )
        )
        
    # ==================== SLIDE 3: METRIC FOCUS & HIGHLIGHT ====================
    if num_slides >= 3:
        slides.append(
            Slide(
                slide_number=3,
                title="Đột Phá Hiệu Suất Vận Hành & ROI",
                subtitle="Cột 1 thu về góc trái và khối số liệu trọng tâm phóng đại toàn diện",
                morph_description="Cột số 1 biến đổi thành thẻ chỉ số khổng lồ bên phải màn hình",
                bg_color=p["bg"],
                elements=[
                    SlideElement(
                        id="s3_badge",
                        type="badge",
                        content="HIỆU QUẢ ĐẦU TƯ",
                        x=6.0, y=10.0, width=22.0, height=6.0,
                        bg_color=p["accent3"],
                        text_color="#FFFFFF",
                        morph_id="badge_header",
                        font_size=11,
                    ),
                    SlideElement(
                        id="s3_sidebar",
                        type="card",
                        content="Tổng Kết Các Lợi Thế",
                        label="TÓM LƯỢC NHANH",
                        sub_text="• Tốc độ tạo slide x10\n• Không cần plugin add-in\n• File tương thích 100%",
                        x=6.0, y=20.0, width=27.0, height=68.0,
                        bg_color=p["card1"],
                        text_color=p["text"],
                        morph_id="morph_col_1",  # CÙNG ID VỚI SLIDE 1 & 2
                        font_size=15,
                    ),
                    SlideElement(
                        id="s3_giant_kpi",
                        type="metric",
                        content="99.995%",
                        label="ĐỘ SẴN SÀNG HỆ THỐNG SLA",
                        sub_text="Vận hành liên tục đa vùng (Multi-Region Active-Active) với độ trễ phản hồi dưới 5ms.",
                        x=36.5, y=20.0, width=57.5, height=32.0,
                        bg_color=p["card2"],
                        text_color=p["accent2"],
                        morph_id="morph_card_main",  # CÙNG ID VỚI SLIDE 1
                        font_size=36,
                    ),
                    SlideElement(
                        id="s3_sub_kpi",
                        type="card",
                        content="Tiết kiệm 65% Chi phí Vận hành",
                        label="TỐI ƯU HÓA NGUỒN LỰC",
                        sub_text="Giảm thiểu 80% thời gian thiết kế thủ công cho đội ngũ Sales & Marketing.",
                        x=36.5, y=56.0, width=57.5, height=32.0,
                        bg_color=p["card1"],
                        text_color=p["text"],
                        morph_id="morph_col_2",  # CÙNG ID VỚI SLIDE 2
                        font_size=18,
                    ),
                ]
            )
        )
        
    # ==================== SLIDE 4 & 5 (NẾU YÊU CẦU >= 4) ====================
    if num_slides >= 4:
        slides.append(
            Slide(
                slide_number=4,
                title="Lộ Trình Triển Khai Chi Tiết (Roadmap)",
                subtitle="Các mốc thời gian chuyển đổi từ Pilot sang Enterprise Scale",
                morph_description="Các khối thông tin sắp xếp lại thành dòng thời gian 4 giai đoạn nối tiếp",
                bg_color=p["bg"],
                elements=[
                    SlideElement(
                        id="s4_stage1",
                        type="card",
                        content="Giai đoạn 1: Q1/2025",
                        label="HOÀN THIỆN MVP",
                        sub_text="Ra mắt phiên bản Web App & Morph XML Compiler",
                        x=6.0, y=24.0, width=20.5, height=60.0,
                        bg_color=p["card1"],
                        text_color=p["text"],
                        morph_id="roadmap_s1",
                        font_size=14,
                    ),
                    SlideElement(
                        id="s4_stage2",
                        type="card",
                        content="Giai đoạn 2: Q2/2025",
                        label="TÍCH HỢP LLM AGENTS",
                        sub_text="Hỗ trợ GPT-4o, Gemini và tối ưu hóa chuyển động 60fps",
                        x=28.5, y=24.0, width=20.5, height=60.0,
                        bg_color=p["card2"],
                        text_color=p["text"],
                        morph_id="roadmap_s2",
                        font_size=14,
                    ),
                    SlideElement(
                        id="s4_stage3",
                        type="card",
                        content="Giai đoạn 3: Q3/2025",
                        label="MỞ RỘNG THƯƠNG MẠI",
                        sub_text="Mở rộng gói Enterprise và tích hợp Google Slides / Figma",
                        x=51.0, y=24.0, width=20.5, height=60.0,
                        bg_color=p["card1"],
                        text_color=p["text"],
                        morph_id="roadmap_s3",
                        font_size=14,
                    ),
                    SlideElement(
                        id="s4_stage4",
                        type="card",
                        content="Giai đoạn 4: Q4/2025",
                        label="HỆ SINH THÁI TOÀN CẦU",
                        sub_text="Cung cấp API cho bên thứ 3 và kho Template Marketplace",
                        x=73.5, y=24.0, width=20.5, height=60.0,
                        bg_color=p["card2"],
                        text_color=p["text"],
                        morph_id="roadmap_s4",
                        font_size=14,
                    ),
                ]
            )
        )
        
    if num_slides >= 5:
        slides.append(
            Slide(
                slide_number=5,
                title="Tổng Kết & Kêu Gọi Hành Động (Call to Action)",
                subtitle="Sẵn sàng kiến tạo những bài thuyết trình ấn tượng cùng ExoticMorph",
                morph_description="Tất cả các khối hội tụ về trung tâm tạo nên thẻ kết luận mạnh mẽ",
                bg_color=p["bg"],
                elements=[
                    SlideElement(
                        id="s5_badge",
                        type="badge",
                        content="SẴN SÀNG HỢP TÁC",
                        x=35.0, y=14.0, width=30.0, height=6.0,
                        bg_color=p["accent1"],
                        text_color="#FFFFFF",
                        morph_id="badge_header",
                        font_size=12,
                    ),
                    SlideElement(
                        id="s5_main_cta",
                        type="card",
                        content="Bắt Đầu Trải Nghiệm ExoticMorph Ngay Hôm Nay",
                        label="HÀNH ĐỘNG NGAY",
                        sub_text="Truy cập https://github.com/Exotic08/ExoticMorph để xem mã nguồn và tài liệu đầy đủ.",
                        x=15.0, y=24.0, width=70.0, height=60.0,
                        bg_color=p["card1"],
                        text_color=p["text"],
                        morph_id="morph_card_main",  # CÙNG ID VỚI SLIDE 1 & 3
                        font_size=24,
                    ),
                ]
            )
        )
        
    # Tạo thêm slide nếu người dùng yêu cầu 6-10 slide
    if num_slides > 5:
        for s_idx in range(6, num_slides + 1):
            slides.append(
                Slide(
                    slide_number=s_idx,
                    title=f"Chuyên Đề Mở Rộng #{s_idx - 5}: Phân Tích Kỹ Thuật",
                    subtitle="Đào sâu vào các chi tiết cấu trúc và số liệu cụ thể",
                    morph_description=f"Slide {s_idx} tiếp nối chuyển động từ slide trước",
                    bg_color=p["bg"],
                    elements=[
                        SlideElement(
                            id=f"s{s_idx}_c1",
                            type="card",
                            content=f"Thông số vận hành Module {s_idx - 5}",
                            label="DỮ LIỆU CHUYÊN SÂU",
                            sub_text="Tự động phân tích và tối ưu hóa ma trận chuyển đổi tọa độ OpenXML.",
                            x=6.0, y=24.0, width=42.0, height=60.0,
                            bg_color=p["card1"],
                            text_color=p["text"],
                            morph_id=f"extra_card_{s_idx}_1",
                            font_size=16,
                        ),
                        SlideElement(
                            id=f"s{s_idx}_c2",
                            type="card",
                            content="Độ tin cậy & SLA",
                            label="TIÊU CHUẨN ĐÁNH GIÁ",
                            sub_text="Đạt chuẩn kiểm định tương thích Microsoft Office OpenXML.",
                            x=52.0, y=24.0, width=42.0, height=60.0,
                            bg_color=p["card2"],
                            text_color=p["text"],
                            morph_id=f"extra_card_{s_idx}_2",
                            font_size=16,
                        ),
                    ]
                )
            )

    return PresentationResponse(
        topic=req.prompt,
        style=req.style,
        aspect_ratio=req.aspect_ratio,
        total_slides=len(slides),
        slides=slides,
        morph_strategy="Liên kết đối tượng xuyên suốt các slide bằng Morph ID đồng bộ hóa tọa độ hình học."
    )


async def generate_presentation_with_llm(req: GenerateRequest) -> PresentationResponse:
    """Gọi LLM (OpenAI GPT-4o hoặc Google Gemini) với Structured Output để sinh dữ liệu.
    Tự động fallback về generator nội bộ nếu không có API key hoặc xảy ra lỗi.
    """
    provider = settings.LLM_PROVIDER.lower()
    
    # 1. Thử gọi OpenAI GPT-4o nếu có cấu hình
    if provider == "openai" and settings.OPENAI_API_KEY:
        try:
            logger.info("Đang gọi OpenAI Model %s với JSON Mode...", settings.OPENAI_MODEL)
            from openai import AsyncOpenAI
            client = AsyncOpenAI(api_key=settings.OPENAI_API_KEY)
            
            user_content = f"""YÊU CẦU CỦA NGƯỜI DÙNG:
Chủ đề: {req.prompt}
Số lượng slide: {req.num_slides}
Phong cách: {req.style}
Tỉ lệ khung hình: {req.aspect_ratio}
Ngôn ngữ: {req.language}

Hãy tính toán chính xác tọa độ Morphing và trả về JSON PresentationResponse đầy đủ."""

            response = await client.chat.completions.create(
                model=settings.OPENAI_MODEL,
                messages=[
                    {"role": "system", "content": SYSTEM_PROMPT},
                    {"role": "user", "content": user_content},
                ],
                response_format={"type": "json_object"},
                temperature=0.7,
            )
            
            content = response.choices[0].message.content
            if content:
                data_dict = json.loads(content)
                parsed = PresentationResponse.model_validate(data_dict)
                logger.info("OpenAI đã sinh thành công %d slide!", len(parsed.slides))
                return parsed
        except Exception as e:
            logger.warning("Lỗi khi gọi OpenAI API: %s. Đang chuyển sang Fallback Generator...", str(e))
            
    # 2. Thử gọi Google Gemini nếu có cấu hình
    elif provider == "gemini" and settings.GEMINI_API_KEY:
        try:
            logger.info("Đang gọi Google Gemini Model %s...", settings.GEMINI_MODEL)
            import google.generativeai as genai
            genai.configure(api_key=settings.GEMINI_API_KEY)
            
            model = genai.GenerativeModel(
                model_name=settings.GEMINI_MODEL,
                generation_config={"response_mime_type": "application/json"}
            )
            
            prompt_full = f"{SYSTEM_PROMPT}\n\nYêu cầu: {req.prompt}\nSố lượng: {req.num_slides}\nPhong cách: {req.style}"
            response = await model.generate_content_async(prompt_full)
            
            if response.text:
                data_dict = json.loads(response.text)
                parsed = PresentationResponse.model_validate(data_dict)
                logger.info("Google Gemini đã sinh thành công %d slide!", len(parsed.slides))
                return parsed
        except Exception as e:
            logger.warning("Lỗi khi gọi Gemini API: %s. Đang chuyển sang Fallback Generator...", str(e))

    # 3. Fallback Heuristic Generator (Luôn đảm bảo hoạt động an toàn & tin cậy)
    return generate_fallback_presentation(req)
