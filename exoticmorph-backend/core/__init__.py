"""
ExoticMorph Backend Core Module (Legacy Shim)
~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~
Thư mục `core/` này từng là bản NHÂN BẢN của `app/core/` — hai bản sao song song
dễ gây "code drift" (sửa bên này quên bên kia, bug tái xuất hiện). Từ đợt rework
này, các module chỉ forward sang `app.core` (một nguồn sự thật duy nhất) để giữ
tương thích ngược cho `test_morph.py` và các script cũ import `core.*`.
"""

from app.core.xml_helper import (  # noqa: F401
    P_NS,
    A_NS,
    R_NS,
    MC_NS,
    P14_NS,
    P15_NS,
    P16_NS,
    XMLNS_MAP,
    MorphOptionType,
    format_morph_name,
    enable_morph_transition,
    set_shape_morph_id,
    get_shape_morph_id,
    has_morph_transition,
)
from app.core.ppt_builder import (  # noqa: F401
    create_demo_morph_presentation,
    MorphPresentationBuilder,
)

__all__ = [
    "P_NS",
    "A_NS",
    "R_NS",
    "MC_NS",
    "P14_NS",
    "P15_NS",
    "P16_NS",
    "XMLNS_MAP",
    "MorphOptionType",
    "format_morph_name",
    "enable_morph_transition",
    "set_shape_morph_id",
    "get_shape_morph_id",
    "has_morph_transition",
    "create_demo_morph_presentation",
    "MorphPresentationBuilder",
]
