"""
ExoticMorph XML Helper Module
~~~~~~~~~~~~~~~~~~~~~~~~~~~~~
Module chuyên trách can thiệp trực tiếp vào cấu trúc OpenXML (PresentationML)
để kích hoạt hiệu ứng chuyển động Morph và liên kết các đối tượng bằng tiền tố '!!'.
"""

from typing import Optional, Union, Literal
import lxml.etree as etree
from pptx.slide import Slide
from pptx.shapes.base import BaseShape
from pptx.oxml.xmlchemy import OxmlElement

# ==============================================================================
# OpenXML Namespaces Definition
# ==============================================================================
P_NS = "http://schemas.openxmlformats.org/presentationml/2006/main"
A_NS = "http://schemas.openxmlformats.org/drawingml/2006/main"
R_NS = "http://schemas.openxmlformats.org/officeDocument/2006/relationships"
P14_NS = "http://schemas.microsoft.com/office/powerpoint/2010/main"
P15_NS = "http://schemas.microsoft.com/office/powerpoint/2012/main"
P16_NS = "http://schemas.microsoft.com/office/powerpoint/2015/main"

# Mapping namespace prefixes for XPath queries
XMLNS_MAP = {
    "p": P_NS,
    "a": A_NS,
    "r": R_NS,
    "p14": P14_NS,
    "p15": P15_NS,
    "p16": P16_NS,
}

MorphOptionType = Literal["byObject", "byWord", "byChar"]


def format_morph_name(raw_name: str) -> str:
  """Chuẩn hóa tên đối tượng Morph với tiền tố bắt buộc '!!'.

  Ví dụ:
      - 'DemoBox' -> '!!DemoBox'
      - '!!DemoBox' -> '!!DemoBox'
      - '!! Morph_Card' -> '!!Morph_Card'

  :param raw_name: Tên gốc hoặc ID mong muốn gán cho đối tượng.
  :return: Chuỗi định dạng chuẩn '!!{id}'.
  """
  clean = raw_name.strip()
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
  """Kích hoạt hiệu ứng chuyển cảnh Morph trong tệp XML của Slide (`slide{n}.xml`).

  Cấu trúc XML sinh ra:
  ```xml
  <p:transition spd="med" advClick="1">
      <p:morph option="byObject"/>
  </p:transition>
  ```

  Vị trí chèn tuân thủ nghiêm ngặt OpenXML Schema (`CT_Slide` sequence):
      `<p:cSld>` -> `<p:transition>` -> `<p:clrMapOvr>` -> `<p:timing>` ->
      `<p:extLst>`
  Chèn ngay trước `<p:clrMapOvr>` để file PPTX không bị báo lỗi Corrupted khi mở
  trên Microsoft Office PowerPoint 2019/365/WPS.

  :param slide: Đối tượng slide từ python-pptx.
  :param duration_ms: Thời lượng hiệu ứng chuyển cảnh (mặc định 1250ms ~
  1.25s).
  :param morph_option: Chế độ morph ('byObject': theo hình khối, 'byWord': theo
  từ ngữ, 'byChar': theo từng ký tự).
  :param advance_on_click: Cho phép click chuột để chuyển slide.
  :return: Node `<p:transition>` vừa được chèn vào cây XML.
  """
  slide_elem = slide._element

  # 1. Xóa transition cũ nếu đã tồn tại để tránh trùng lặp tag XML
  existing_trans = slide_elem.find(f"{{{P_NS}}}transition")
  if existing_trans is not None:
    slide_elem.remove(existing_trans)

  # 2. Khởi tạo node <p:transition>
  transition = etree.Element(f"{{{P_NS}}}transition")
  if advance_on_click:
    transition.set("advClick", "1")

  # Tùy chọn tốc độ chuyển cảnh (spd="med" tương đương standard 1.25s)
  if duration_ms <= 800:
    transition.set("spd", "fast")
  elif duration_ms >= 2000:
    transition.set("spd", "slow")
  else:
    transition.set("spd", "med")

  # 3. Khởi tạo node con <p:morph> bên trong <p:transition>
  morph = etree.SubElement(transition, f"{{{P_NS}}}morph")
  if morph_option in ("byObject", "byWord", "byChar"):
    morph.set("option", morph_option)
  else:
    morph.set("option", "byObject")

  # 4. Chèn vào đúng vị trí theo quy định OpenXML Schema
  # Ưu tiên chèn ngay trước thẻ <p:clrMapOvr>
  clr_map_ovr = slide_elem.find(f"{{{P_NS}}}clrMapOvr")
  if clr_map_ovr is not None:
    clr_map_ovr.addprevious(transition)
  else:
    # Nếu không có clrMapOvr, kiểm tra timing hoặc extLst
    timing_elem = slide_elem.find(f"{{{P_NS}}}timing")
    ext_lst_elem = slide_elem.find(f"{{{P_NS}}}extLst")

    if timing_elem is not None:
      timing_elem.addprevious(transition)
    elif ext_lst_elem is not None:
      ext_lst_elem.addprevious(transition)
    else:
      slide_elem.append(transition)

  return transition


def set_shape_morph_id(shape: BaseShape, morph_id: str) -> str:
  """Đổi tên đối tượng trong thuộc tính `name` của tag `<p:cNvPr>` thành tiền tố

  '!!{morph_id}'.

  Cơ chế Morph Matching của PowerPoint:
  Khi 2 shape ở 2 slide kế tiếp nhau có cùng tên bắt đầu bằng hai dấu chấm than
  '!!'
  (ví dụ: '!!MyBox'), PowerPoint sẽ nội suy chuyển động (vị trí X/Y, kích thước
  W/H,
  màu sắc Fill/Stroke, độ xoay Rotation) từ Shape 1 sang Shape 2.

  :param shape: Đối tượng shape (hình khối, textbox, hình ảnh, group...).
  :param morph_id: Tên hoặc định danh dùng để liên kết morph giữa các slide.
  :return: Tên đầy đủ sau khi gán tiền tố (ví dụ: '!!MyBox').
  """
  formatted_name = format_morph_name(morph_id)

  # Cập nhật thông qua python-pptx property
  shape.name = formatted_name

  # Đồng thời kiểm tra can thiệp trực tiếp vào XML cNvPr để đảm bảo 100% chính xác
  try:
    c_nv_pr = shape._element.xpath(".//p:cNvPr", namespaces=XMLNS_MAP)
    if c_nv_pr:
      c_nv_pr[0].set("name", formatted_name)
  except Exception:
    # Fallback nếu xpath chưa compile được namespace
    for child in shape._element.iter():
      if child.tag.endswith("cNvPr"):
        child.set("name", formatted_name)
        break

  return formatted_name


def get_shape_morph_id(shape: BaseShape) -> Optional[str]:
  """Lấy ID morph của shape (nếu có bắt đầu bằng '!!').

  :param shape: Đối tượng shape cần kiểm tra.
  :return: Chuỗi ID (đã bỏ '!!') hoặc None nếu không phải shape morph.
  """
  name = shape.name.strip()
  if name.startswith("!!"):
    return name[2:].strip()
  return None


def has_morph_transition(slide: Slide) -> bool:
  """Kiểm tra xem slide đã được cấu hình hiệu ứng Morph XML hay chưa.

  :param slide: Đối tượng slide.
  :return: True nếu có thẻ <p:transition><p:morph/></p:transition>, ngược lại
  False.
  """
  slide_elem = slide._element
  trans = slide_elem.find(f"{{{P_NS}}}transition")
  if trans is not None:
    morph = trans.find(f"{{{P_NS}}}morph")
    return morph is not None
  return False
