"""Legacy shim → `app.core.xml_helper` (giữ tương thích import `core.xml_helper`)."""
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
]
