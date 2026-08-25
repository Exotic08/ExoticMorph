"""
ExoticMorph XML Helper Module (OpenXML PresentationML & MS-PPTX Extensions)
"""
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

def format_morph_name(raw_name: str) -> str:
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
    slide_elem = slide._element

    for child in list(slide_elem):
        if child.tag == f"{{{MC_NS}}}AlternateContent" or child.tag == f"{{{P_NS}}}transition":
            slide_elem.remove(child)

    spd = "med"
    if duration_ms <= 800:
        spd = "fast"
    elif duration_ms >= 2000:
        spd = "slow"

    adv_click_str = "1" if advance_on_click else "0"
    valid_option = morph_option if morph_option in ("byObject", "byWord", "byChar") else "byObject"

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

    clr_map_ovr = slide_elem.find(f"{{{P_NS}}}clrMapOvr")
    if clr_map_ovr is not None:
        clr_map_ovr.addprevious(alt_content)
    else:
        timing_elem = slide_elem.find(f"{{{P_NS}}}timing")
        ext_lst_elem = slide_elem.find(f"{{{P_NS}}}extLst")
        if timing_elem is not None:
            timing_elem.addprevious(alt_content)
        elif ext_lst_elem is not None:
            ext_lst_elem.addprevious(alt_content)
        else:
            slide_elem.append(alt_content)

    return alt_content

def set_shape_morph_id(shape: BaseShape, morph_id: str) -> str:
    formatted_name = format_morph_name(morph_id)
    shape.name = formatted_name
    try:
        c_nv_pr = shape._element.xpath(".//p:cNvPr", namespaces=XMLNS_MAP)
        if c_nv_pr:
            c_nv_pr[0].set("name", formatted_name)
    except Exception:
        for child in shape._element.iter():
            if child.tag.endswith("cNvPr"):
                child.set("name", formatted_name)
                break
    return formatted_name
