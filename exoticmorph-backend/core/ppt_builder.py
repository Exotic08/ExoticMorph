"""Legacy shim → `app.core.ppt_builder` (giữ tương thích import `core.ppt_builder`)."""
from app.core.ppt_builder import (  # noqa: F401
    create_demo_morph_presentation,
    MorphPresentationBuilder,
)

__all__ = ["create_demo_morph_presentation", "MorphPresentationBuilder"]
