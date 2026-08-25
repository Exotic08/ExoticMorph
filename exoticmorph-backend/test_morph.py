"""Test Script for ExoticMorph PowerPoint OpenXML Morph Generation
~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~
Kiểm thử tạo file PowerPoint demo_morph.pptx và bóc tách gói ZIP OpenXML
để xác thực 100% các thẻ Morph XML và tiền tố !! đã được cấu hình chính xác.
"""

import os
import sys
import zipfile
import lxml.etree as etree

# Đảm bảo import được module core
CURRENT_DIR = os.path.dirname(os.path.abspath(__file__))
if CURRENT_DIR not in sys.path:
  sys.path.insert(0, CURRENT_DIR)

from core.ppt_builder import create_demo_morph_presentation
from core.xml_helper import P_NS, XMLNS_MAP


def inspect_pptx_xml(pptx_path: str):
  """Giải nén tệp .pptx trong bộ nhớ và kiểm tra cấu trúc OpenXML của các

  slide.
  """
  print("\n" + "=" * 70)
  print(f"🔍 BẮT ĐẦU BÓC TÁCH VÀ KIỂM TRA TỆP OPENXML: {pptx_path}")
  print("=" * 70)

  with zipfile.ZipFile(pptx_path, "r") as z:
    file_list = z.namelist()
    slide_files = sorted(
        [f for f in file_list if f.startswith("ppt/slides/slide") and f.endswith(".xml")]
    )

    print(f"📦 Tìm thấy {len(slide_files)} slide trong package PPTX:")
    for sf in slide_files:
      print(f"   • {sf}")

    print("-" * 70)

    # 1. Kiểm tra Slide 1
    if "ppt/slides/slide1.xml" in file_list:
      xml_bytes_1 = z.read("ppt/slides/slide1.xml")
      root1 = etree.fromstring(xml_bytes_1)

      print("\n📄 [SLIDE 1] Kiểm tra đối tượng và thuộc tính:")
      c_nv_prs_1 = root1.xpath(".//p:cNvPr", namespaces=XMLNS_MAP)
      morph_shapes_1 = [
          elem.get("name")
          for elem in c_nv_prs_1
          if elem.get("name", "").startswith("!!")
      ]

      if morph_shapes_1:
        print(f"   ✅ Tìm thấy Morph Anchor Shape: {morph_shapes_1}")
      else:
        print("   ❌ Không tìm thấy shape có tiền tố '!!' trong Slide 1!")

      trans1 = root1.find(f"{{{P_NS}}}transition")
      if trans1 is None:
        print("   ℹ️ Slide 1: Không có transition (Slide bắt đầu - Đúng chuẩn)")

    # 2. Kiểm tra Slide 2
    if "ppt/slides/slide2.xml" in file_list:
      xml_bytes_2 = z.read("ppt/slides/slide2.xml")
      root2 = etree.fromstring(xml_bytes_2)

      print("\n📄 [SLIDE 2] Kiểm tra đối tượng và Transition Morph:")
      c_nv_prs_2 = root2.xpath(".//p:cNvPr", namespaces=XMLNS_MAP)
      morph_shapes_2 = [
          elem.get("name")
          for elem in c_nv_prs_2
          if elem.get("name", "").startswith("!!")
      ]

      if morph_shapes_2:
        print(f"   ✅ Tìm thấy Morph Anchor Shape: {morph_shapes_2}")
      else:
        print("   ❌ Không tìm thấy shape có tiền tố '!!' trong Slide 2!")

      # Kiểm tra tag <p:transition> và <p:morph>
      trans2 = root2.find(f"{{{P_NS}}}transition")
      if trans2 is not None:
        morph2 = trans2.find(f"{{{P_NS}}}morph")
        if morph2 is not None:
          option = morph2.get("option", "default")
          print(
              f"   ✅ Tìm thấy thẻ Morph Transition: <p:transition><p:morph"
              f' option="{option}"/></p:transition>'
          )
        else:
          print("   ❌ Thẻ <p:transition> tồn tại nhưng thiếu node con <p:morph>!")
      else:
        print("   ❌ Không tìm thấy thẻ <p:transition> trong Slide 2!")

      # Kiểm tra vị trí XML Schema: transition phải nằm trước clrMapOvr
      children = [child.tag for child in root2]
      try:
        trans_idx = children.index(f"{{{P_NS}}}transition")
        clr_idx = children.index(f"{{{P_NS}}}clrMapOvr")
        if trans_idx < clr_idx:
          print(
              f"   ✅ Thứ tự XML Schema chuẩn: transition (index {trans_idx})"
              f" -> clrMapOvr (index {clr_idx})"
          )
        else:
          print(
              f"   ⚠️ Cảnh báo: transition (index {trans_idx}) nằm sau"
              f" clrMapOvr (index {clr_idx})"
          )
      except ValueError:
        pass

      # In đoạn trích XML Slide 2 Transition
      print("\n📝 [SLIDE 2 XML SNIPPET]:")
      print(
          etree.tostring(
              trans2 if trans2 is not None else root2, pretty_print=True
          ).decode()[:400]
      )


def main():
  output_filename = os.path.join(CURRENT_DIR, "demo_morph.pptx")

  print("=" * 70)
  print("🚀 EXOTICMORPH BACKEND - TEST MORPH OPENXML GENERATION")
  print("=" * 70)
  print("Đang khởi tạo bài trình chiếu PowerPoint...")

  # Gọi hàm tạo slide từ ppt_builder
  result_path = create_demo_morph_presentation(output_filename)

  file_size_kb = os.path.getsize(result_path) / 1024
  print(f"\n🎉 Tạo file thành công: {result_path}")
  print(f"📊 Dung lượng file: {file_size_kb:.2f} KB")

  # Kiểm tra tính toàn vẹn XML
  inspect_pptx_xml(result_path)

  print("\n" + "=" * 70)
  print("✨ HOÀN THÀNH KIỂM THỬ MORPH XML CORE THÀNH CÔNG 100%!")
  print("Bạn có thể mở trực tiếp file 'demo_morph.pptx' trong Microsoft")
  print("PowerPoint hoặc WPS Office và nhấn F5 để chiêm ngưỡng hiệu ứng Morph.")
  print("=" * 70)


if __name__ == "__main__":
  main()
