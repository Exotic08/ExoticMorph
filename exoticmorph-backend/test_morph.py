"""Test Script for ExoticMorph PowerPoint OpenXML Morph Generation
~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~
Kiểm thử tạo file PowerPoint demo_morph.pptx và bóc tách gói ZIP OpenXML
để xác thực 100% các thẻ Morph XML và tiền tố !! đã được cấu hình chính xác.

Đợt rework đã sửa 2 khẳng định SAI của bản cũ:
- Thứ tự schema chuẩn ECMA-376 (CT_Slide): cSld -> clrMapOvr -> transition
  -> timing -> extLst. Nghĩa là transition phải nằm SAU clrMapOvr (bản cũ
  kiểm tra ngược và sinh XML sai thứ tự).
- Transition Morph nằm trong wrapper <mc:AlternateContent> (Choice/Fallback)
  nên phải tìm bằng XPath hậu duệ (.//p:transition), không phải con trực tiếp.

Script trả exit code 0 (đạt) / 1 (lỗi) để chạy được trong CI.
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
from core.xml_helper import P_NS, MC_NS, XMLNS_MAP

# Thứ tự con hợp lệ của <p:sld> theo ECMA-376 (CT_Slide)
SLIDE_CHILD_ORDER = ["cSld", "clrMapOvr", "transition", "AlternateContent", "timing", "extLst"]
_ORDER_RANK = {name: idx for idx, name in enumerate(SLIDE_CHILD_ORDER)}


def _inspect_slide(z: zipfile.ZipFile, slide_file: str) -> bool:
    """Kiểm tra cấu trúc OpenXML của một slide. Trả True nếu hợp lệ."""
    print(f"\n📄 [{slide_file.upper()}] Kiểm tra đối tượng và Transition Morph:")
    root = etree.fromstring(z.read(slide_file))

    # 1) Kiểm tra shape có tên bắt đầu bằng '!!' (Morph Anchor)
    c_nv_prs = root.xpath(".//p:cNvPr", namespaces=XMLNS_MAP)
    morph_shapes = [
        elem.get("name")
        for elem in c_nv_prs
        if (elem.get("name") or "").startswith("!!")
    ]
    if morph_shapes:
        print(f"   ✅ Tìm thấy Morph Anchor Shape: {morph_shapes}")
    else:
        print("   ❌ Không tìm thấy shape có tiền tố '!!'!")
        return False

    # 2) Tìm transition (nằm trong mc:AlternateContent hoặc trực tiếp)
    transitions = root.xpath(".//p:transition", namespaces=XMLNS_MAP)
    if not transitions:
        print("   ℹ️ Slide này không có transition (slide đầu tiên — đúng chuẩn).")
        return True

    trans = transitions[0]
    morph_nodes = [
        child for child in trans
        if etree.QName(child).localname == "morph"
    ]
    if morph_nodes:
        option = morph_nodes[0].get("option", "byObject")
        morph_ns = etree.QName(morph_nodes[0]).namespace
        print(
            f'   ✅ Morph Transition hợp lệ: <p:transition ...><...morph option="{option}"/></p:transition>'
        )
        print(f"      (morph namespace: {morph_ns})")
    else:
        print("   ❌ Thẻ <p:transition> tồn tại nhưng thiếu node con morph!")
        return False

    # 3) KIỂM TRA THỨ TỰ SCHEMA (điểm từng bị làm sai trước đây):
    #    transition/AlternateContent phải đứng SAU clrMapOvr và TRƯỚC timing.
    child_names = [etree.QName(c).localname for c in root if isinstance(c.tag, str)]
    ranks = [_ORDER_RANK.get(name, 99) for name in child_names]
    clr_idx = child_names.index("clrMapOvr") if "clrMapOvr" in child_names else -1
    trans_slot = min(
        (i for i, n in enumerate(child_names) if n in ("transition", "AlternateContent")),
        default=-1,
    )

    if ranks != sorted(ranks):
        print(f"   ❌ Thứ tự thẻ con <p:sld> sai schema ECMA-376: {child_names}")
        return False
    if clr_idx != -1 and trans_slot != -1 and trans_slot < clr_idx:
        print(
            f"   ❌ transition (index {trans_slot}) nằm TRƯỚC clrMapOvr (index {clr_idx}) — sai chuẩn!"
        )
        return False
    print(
        f"   ✅ Thứ tự XML Schema chuẩn: {child_names} (transition sau clrMapOvr)"
    )
    return True


def inspect_pptx_xml(pptx_path: str) -> bool:
    """Giải nén tệp .pptx trong bộ nhớ và kiểm tra cấu trúc OpenXML."""
    print("\n" + "=" * 70)
    print(f"🔍 BẮT ĐẦU BÓC TÁCH VÀ KIỂM TRA TỆP OPENXML: {pptx_path}")
    print("=" * 70)

    all_ok = True
    with zipfile.ZipFile(pptx_path, "r") as z:
        file_list = z.namelist()
        slide_files = sorted(
            f for f in file_list
            if f.startswith("ppt/slides/slide") and f.endswith(".xml")
        )
        print(f"📦 Tìm thấy {len(slide_files)} slide trong package PPTX:")
        for sf in slide_files:
            print(f"   • {sf}")
        print("-" * 70)

        for sf in slide_files:
            all_ok &= _inspect_slide(z, sf)

        # In đoạn trích XML transition của slide cuối để quan sát bằng mắt
        if slide_files:
            root = etree.fromstring(z.read(slide_files[-1]))
            alt = root.find(f"{{{MC_NS}}}AlternateContent")
            if alt is not None:
                print("\n📝 [XML SNIPPET - Transition của slide cuối]:")
                print(etree.tostring(alt, pretty_print=True).decode()[:600])

    return all_ok


def main() -> int:
    output_filename = os.path.join(CURRENT_DIR, "demo_morph.pptx")

    print("=" * 70)
    print("🚀 EXOTICMORPH BACKEND - TEST MORPH OPENXML GENERATION")
    print("=" * 70)
    print("Đang khởi tạo bài trình chiếu PowerPoint...")

    result_path = create_demo_morph_presentation(output_filename)

    file_size_kb = os.path.getsize(result_path) / 1024
    print(f"\n🎉 Tạo file thành công: {result_path}")
    print(f"📊 Dung lượng file: {file_size_kb:.2f} KB")

    # Kiểm tra tính toàn vẹn XML
    passed = inspect_pptx_xml(result_path)

    print("\n" + "=" * 70)
    if passed:
        print("✨ HOÀN THÀNH KIỂM THỨ MORPH XML CORE THÀNH CÔNG 100%!")
        print("Bạn có thể mở trực tiếp file 'demo_morph.pptx' trong Microsoft")
        print("PowerPoint hoặc WPS Office và nhấn F5 để chiêm ngưỡng hiệu ứng Morph.")
    else:
        print("❌ KIỂM THỬ THẤT BẠI — cấu trúc XML Morph chưa đúng chuẩn!")
    print("=" * 70)
    return 0 if passed else 1


if __name__ == "__main__":
    sys.exit(main())
