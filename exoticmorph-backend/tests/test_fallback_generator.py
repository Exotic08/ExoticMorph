"""Regression tests for the heuristic fallback generator.

The production 502 on POST /api/v1/generate-json was caused by ContentCard
titles built from the raw user prompt (e.g. "Bối cảnh tạo bài thuyết trình về
solar system") violating the 3-6 word constraint. Fallback must never raise.
"""

from __future__ import annotations

import asyncio
import os
import sys
import unittest

BACKEND_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if BACKEND_ROOT not in sys.path:
    sys.path.insert(0, BACKEND_ROOT)

from app.schemas.slide_schema import GenerateRequest  # noqa: E402
from app.services.llm_service import (  # noqa: E402
    _extract_topic_core,
    _fit_title,
    _topic_phrase,
    generate_fallback_presentation,
    generate_presentation_with_llm,
)


def _assert_cards_valid(test: unittest.TestCase, presentation) -> None:
    test.assertGreaterEqual(presentation.total_slides, 1)
    test.assertEqual(len(presentation.slides), presentation.total_slides)
    for slide in presentation.slides:
        cards = [el for el in slide.elements if el.type == "card"]
        test.assertTrue(cards, f"slide {slide.slide_number} has no cards")
        for card in cards:
            title_words = (card.content or "").split()
            body_words = (card.sub_text or "").split()
            test.assertTrue(
                3 <= len(title_words) <= 6,
                f"title {card.content!r} has {len(title_words)} words",
            )
            test.assertTrue(
                30 <= len(body_words) <= 50,
                f"description for {card.content!r} has {len(body_words)} words",
            )
            test.assertTrue(
                150 <= len(card.sub_text or "") <= 450,
                f"description for {card.content!r} has {len(card.sub_text or '')} chars",
            )


class FallbackGeneratorTests(unittest.TestCase):
    def test_extracts_topic_from_vietnamese_request(self) -> None:
        prompt = "tạo bài thuyết trình về solar system"
        self.assertEqual(_extract_topic_core(prompt), "solar system")
        self.assertEqual(_topic_phrase(prompt), "solar system")
        self.assertEqual(_fit_title(f"Bối cảnh {_topic_phrase(prompt)}"), "Bối cảnh solar system")

    def test_reproduces_render_502_prompt(self) -> None:
        req = GenerateRequest(
            prompt="tạo bài thuyết trình về solar system",
            num_slides=5,
            style="Futuristic",
        )
        presentation = generate_fallback_presentation(req)
        self.assertEqual(presentation.total_slides, 5)
        self.assertEqual(presentation.topic, "solar system")
        _assert_cards_valid(self, presentation)

    def test_long_prompt_and_many_slides(self) -> None:
        req = GenerateRequest(
            prompt="Pitch Deck gọi vốn 1 triệu USD cho startup AI SaaS",
            num_slides=10,
            style="Corporate",
        )
        presentation = generate_fallback_presentation(req)
        self.assertEqual(presentation.total_slides, 10)
        _assert_cards_valid(self, presentation)

    def test_english_create_presentation_prefix(self) -> None:
        req = GenerateRequest(
            prompt="create a presentation about climate change impacts",
            num_slides=3,
            style="Minimal",
        )
        presentation = generate_fallback_presentation(req)
        self.assertEqual(presentation.topic, "climate change impacts")
        _assert_cards_valid(self, presentation)

    def test_entry_point_without_api_key_uses_fallback(self) -> None:
        req = GenerateRequest(
            prompt="tạo bài thuyết trình về solar system",
            num_slides=5,
            style="Futuristic",
        )
        presentation = asyncio.run(generate_presentation_with_llm(req))
        self.assertEqual(presentation.total_slides, 5)
        _assert_cards_valid(self, presentation)


if __name__ == "__main__":
    unittest.main()
