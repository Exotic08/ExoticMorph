"""
ExoticMorph XML Helper Module (OpenXML PresentationML & MS-PPTX Extensions)
~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~
Can thiệp trực tiếp lên cây XML OpenXML của slide để:
- Kích hoạt hiệu ứng chuyển cảnh Morph (<p16:morph/>) đúng chuẩn ECMA-376.
- Đặt tên shape dạng '!!name' để PowerPoint Morph Engine tự động khớp đối tượng
  giữa 2 slide liên tiếp.

Điểm sửa lỗi quan trọng (schema order):
  Thứ tự con của <p:sld> theo ECMA-376 (CT_Slide) là BẮT BUỘC:
      p:cSld -> p:clrMapOvr -> p:transition -> p:timing -> p:extLst
  Bản cũ chèn transition TRƯỚC clrMapOvr => sai schema, PowerPoint có thể hiện
  hộp thoại "Repair" hoặc âm thầm bỏ mất hiệu ứng Morph. Bản này chèn transition
  (được bọc trong <mc:AlternateContent>) NGAY SAU clrMapOvr và TRƯỚC timing.
"""

import re
from typing import Optional, Literal

import lxml.etree as etree
from pptx.slide import Slide
from pptx.shapes.base import BaseShape

P_NS = "http://schemas.openxmlformats.org/presentationml/2006/main"
A_NS = "http://schemas.openxmlformats.org/drawingml/2006/main"
R_NS = "http://schemas.openxmlformats.org/officeDocument/2006/relationships"
MC_NS = "http://schemas.openxmlformats.org/markup-compatibility/2006"
P14_NS = "http://schemas.microsoft.com/office/powerpoint/2010/main"
P15_NS = "http://schemas.microsoft.com/office/powerpoint/2012/main"
P16_NS = "http://schemas.microsoft.com/office/powerpoint/2015/09/main"

XMLNS_MAP = {
    "p": P_NS, "a": A_NS, "r": R_NS, "mc": MC_NS,
    "p14": P14_NS, "p15": P15_NS, "p16": P16_NS,
}

MorphOptionType = Literal["byObject", "byWord", "byChar"]

# Các ký tự điều khiển (control chars) không hợp lệ trong XML attribute.
# LLM đôi khi trả về morph_id dính ký tự ẩn => lxml sẽ raise ValueError khi
# serialize, làm hỏng toàn bộ file .pptx. Ta loại bỏ trước khi gán name.
_XML_CTRL_CHARS = re.compile(r"[\x00-\x1f\x7f]")


def format_morph_name(raw_name: str) -> str:
    """Chuẩn hóa tên shape về dạng '!!<tên sạch>' — quy ước PowerPoint dùng để
    khớp đối tượng morph (hai shape cùng tên '!!x' ở 2 slide sẽ nội suy lẫn nhau)."""
    clean = _XML_CTRL_CHARS.sub("", raw_name.strip())
    while clean.startswith("!"):
        clean = clean[1:].strip()
    if not clean:
        clean = "MorphObject"
    return f"!!{clean}"


def enable_morph_transition(
    slide: Slide,
    duration_ms: int = 1250,
    morph_option: MorphOptionType = "byObject",
    advance_on_click: bool = True,
) -> etree._Element:
    """Chèn transition Morph vào slide, đúng vị trí schema ECMA-376.

    Cấu trúc sinh ra (PowerPoint 2019/365 hiểu Choice, bản cũ đọc Fallback fade):
      <mc:AlternateContent>
        <mc:Choice Requires="p16">
          <p:transition spd="..." p14:dur="..." advClick="...">
            <p16:morph option="byObject"/>
          </p:transition>
        </mc:Choice>
        <mc:Fallback>
          <p:transition spd="..."><p:fade/></p:transition>
        </mc:Fallback>
      </mc:AlternateContent>

    Hàm này là idempotent: gọi nhiều lần vẫn chỉ có MỘT transition trên slide
    (bản cũ nếu có sẽ bị gỡ bỏ trước khi chèn lại) — tránh rò rỉ node XML khi
    build lại slide trong cùng một Presentation.
    """
    slide_elem = slide._element

    # 1) Dọn transition / AlternateContent cũ (chỉ các node con TRỰC TIẾP của
    #    p:sld — không đụng tới XML bên trong p:cSld/spTree).
    for child in list(slide_elem):
        if child.tag == f"{{{MC_NS}}}AlternateContent" or child.tag == f"{{{P_NS}}}transition":
            slide_elem.remove(child)

    # 2) Chặn giá trị vô lý của duration (ms) để không sinh attribute lỗi schema.
    duration_ms = max(200, min(int(duration_ms), 60_000))

    spd = "med"
    if duration_ms <= 800:
        spd = "fast"
    elif duration_ms >= 2000:
        spd = "slow"

    adv_click_str = "1" if advance_on_click else "0"
    valid_option = morph_option if morph_option in ("byObject", "byWord", "byChar") else "byObject"

    # Lưu ý: tiền tố namespace (p16) là tùy ý, quan trọng là namespace URI của
    # Morph (2015/09) khớp với giá trị của thuộc tính Requires trên mc:Choice.
    xml_string = f"""<mc:AlternateContent xmlns:mc="{MC_NS}">
  <mc:Choice xmlns:p16="{P16_NS}" Requires="p16">
    <p:transition xmlns:p="{P_NS}" xmlns:p14="{P14_NS}" spd="{spd}" p14:dur="{duration_ms}" advClick="{adv_click_str}">
      <p16:morph option="{valid_option}"/>
    </p:transition>
  </mc:Choice>
  <mc:Fallback xmlns:p="{P_NS}">
    <p:transition spd="{spd}" advClick="{adv_click_str}">
      <p:fade/>
    </p:transition>
  </mc:Fallback>
</mc:AlternateContent>"""

    alt_content = etree.fromstring(xml_string)

    # 3) Chèn đúng thứ tự CT_Slide: sau clrMapOvr, trước timing/extLst.
    #    (python-pptx luôn tạo <p:clrMapOvr> cho slide mới nên nhánh chính là
    #    clrMapOvr.addnext; các nhánh còn lại chỉ là phòng thủ.)
    clr_map_ovr = slide_elem.find(f"{{{P_NS}}}clrMapOvr")
    if clr_map_ovr is not None:
        clr_map_ovr.addnext(alt_content)
        return alt_content

    timing_elem = slide_elem.find(f"{{{P_NS}}}timing")
    if timing_elem is not None:
        timing_elem.addprevious(alt_content)
        return alt_content

    ext_lst_elem = slide_elem.find(f"{{{P_NS}}}extLst")
    if ext_lst_elem is not None:
        ext_lst_elem.addprevious(alt_content)
        return alt_content

    slide_elem.append(alt_content)
    return alt_content


def set_shape_morph_id(shape: BaseShape, morph_id: str) -> str:
    """Gán tên '!!<morph_id>' cho shape ở CẢ hai nơi:
    - Thuộc tính Python `shape.name` (python-pptx tự đồng bộ vào <p:cNvPr>).
    - Trực tiếp attribute `name` của node <p:cNvPr> trong XML (belt-and-braces
      cho các loại shape đặc biệt mà setter của python-pptx không phủ hết).
    """
    formatted_name = format_morph_name(morph_id)

    # Setter chính: python-pptx ghi name vào p:nvSpPr/p:cNvPr@name.
    shape.name = formatted_name

    # Phòng thủ: đảm node <p:cNvPr> ĐẦU TIÊN (của chính shape này, không phải
    # shape con trong group) thực sự mang tên '!!...'.
    # Lưu ý: BaseOxmlElement.xpath() của python-pptx KHÔNG nhận kwargs
    # `namespaces` (dùng nsmap nội bộ sẵn có) — bản cũ gọi sai chữ ký này và
    # chỉ thoát lỗi nhờ `except Exception` quá rộng.
    try:
        c_nv_pr_list = shape._element.xpath(".//p:cNvPr")
        if c_nv_pr_list:
            c_nv_pr_list[0].set("name", formatted_name)
    except (TypeError, etree.XPathError):
        # Fallback cuối cùng: quét tay cây XML tìm node kết thúc bằng 'cNvPr'.
        for child in shape._element.iter():
            if child.tag.endswith("cNvPr"):
                child.set("name", formatted_name)
                break
    return formatted_name


def get_shape_morph_id(shape: BaseShape) -> Optional[str]:
    """Đọc morph_id (nếu có) từ tên shape dạng '!!<id>'."""
    name = (shape.name or "").strip()
    if name.startswith("!!"):
        return name[2:].strip()
    return None


def has_morph_transition(slide: Slide) -> bool:
    """Kiểm tra slide đã có transition Morph (namespace p16) hay chưa."""
    slide_elem = slide._element
    alt_content = slide_elem.find(f"{{{MC_NS}}}AlternateContent")
    if alt_content is not None:
        choice = alt_content.find(f"{{{MC_NS}}}Choice")
        if choice is not None:
            morph = choice.find(f".//{{{P16_NS}}}morph")
            return morph is not None
    return False
