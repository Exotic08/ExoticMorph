"""
ExoticMorph Backend Core Module
~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~
Xử lý OpenXML và tự động cấu hình hiệu ứng PowerPoint Morph cho slide.
"""

from .xml_helper import (
    P_NS,
    A_NS,
    R_NS,
    enable_morph_transition,
    set_shape_morph_id,
    get_shape_morph_id,
    has_morph_transition,
    format_morph_name,
)
from .ppt_builder import (
    create_demo_morph_presentation,
    MorphPresentationBuilder,
)

__all__ = [
    "P_NS",
    "A_NS",
    "R_NS",
    "enable_morph_transition",
    "set_shape_morph_id",
    "get_shape_morph_id",
    "has_morph_transition",
    "format_morph_name",
    "create_demo_morph_presentation",
    "MorphPresentationBuilder",
]
