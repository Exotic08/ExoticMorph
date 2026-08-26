"""Regression tests for the heuristic fallback generator.

Covers:
- The historical production 502 (titles built from raw prompt violating word
  constraints) — fallback must never raise and must always fit the schema.
- The new Executive Design contract: specific-message titles, two-part cards,
  narrative arc sections, adaptive layouts and no cliché labels.
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
    _extract_prompt_facts,
    _extract_topic_core,
    _fit_title,
    _topic_phrase,
    generate_fallback_presentation,
    generate_presentation_with_llm,
)

# Cụm sáo rỗng bị cấm tuyệt đối trong tiêu đề (đối chiếu với STRICT BAN LIST).
BANNED_PHRASES = [
    "giới thiệu chủ đề", "điểm nổi bật", "cấu trúc bài", "yếu tố cốt lõi",
    "tổng quan", "phân tích chuyên sâu", "dữ liệu & bằng chứng", "giải pháp/công nghệ",
    "tác động chính", "chỉ số đo lường", "đặc điểm", "thành phần",
    "lộ trình triển khai", "kết luận và bước tiếp theo",
]

ARC_VI_5 = [
    "VẤN ĐỀ", "NGUYÊN NHÂN GỐC RỄ", "GIẢI PHÁP THỰC THI",
    "KẾT QUẢ KỲ VỌNG", "HÀNH ĐỘNG TIẾP THEO",
]


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
                2 <= len(title_words) <= 10,
                f"title {card.content!r} has {len(title_words)} words",
            )
            test.assertTrue(
                20 <= len(body_words) <= 60,
                f"description for {card.content!r} has {len(body_words)} words",
            )
            test.assertTrue(
                120 <= len(card.sub_text or "") <= 520,
                f"description for {card.content!r} has {len(card.sub_text or '')} chars",
            )
            test.assertTrue(
                card.accent_color and card.accent_color.startswith("#"),
                f"card {card.content!r} lacks a valid accent color",
            )


def _assert_no_cliches(test: unittest.TestCase, presentation) -> None:
    for slide in presentation.slides:
        haystack = (slide.title or "").lower()
        for card in slide.elements:
            if card.type == "card":
                haystack += " " + (card.content or "").lower()
        for phrase in BANNED_PHRASES:
            test.assertNotIn(phrase, haystack, f"cliché '{phrase}' in slide {slide.slide_number}")


class FallbackGeneratorTests(unittest.TestCase):
    def test_extracts_topic_from_vietnamese_request(self) -> None:
        prompt = "tạo bài thuyết trình về solar system"
        self.assertEqual(_extract_topic_core(prompt), "solar system")
        self.assertEqual(_topic_phrase(prompt), "solar system")
        self.assertEqual(_fit_title(f"Bối cảnh {_topic_phrase(prompt)}"), "Bối cảnh solar system")

    def test_extracts_facts_from_prompt(self) -> None:
        facts = _extract_prompt_facts(
            "Doanh thu đạt 12.5 triệu USD (+35% QoQ) trong quý 3/2024, CAC giảm 18%"
        )
        self.assertEqual(facts["money"], "12.5 triệu USD")
        self.assertEqual(facts["percent"], "35%")
        self.assertEqual(facts["year"], "2024")

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
        _assert_no_cliches(self, presentation)

    def test_english_create_presentation_prefix(self) -> None:
        req = GenerateRequest(
            prompt="create a presentation about climate change impacts",
            num_slides=3,
            style="Minimal",
            language="en",
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

    def test_narrative_arc_sections_for_five_slides(self) -> None:
        req = GenerateRequest(
            prompt="báo cáo doanh thu quý 3 tăng trưởng 35%",
            num_slides=5,
            style="Corporate",
        )
        presentation = generate_fallback_presentation(req)
        sections = [s.section for s in presentation.slides]
        self.assertEqual(sections, ARC_VI_5)

    def test_layout_diversity(self) -> None:
        req = GenerateRequest(
            prompt="báo cáo doanh thu quý 3 tăng trưởng 35%",
            num_slides=5,
            style="Corporate",
        )
        presentation = generate_fallback_presentation(req)
        layouts = {s.layout_type for s in presentation.slides}
        # 5-slide deck: 4 "features" + 1 "roadmap" => ít nhất 2 loại bố cục.
        self.assertIn("roadmap", layouts)
        self.assertGreaterEqual(len(layouts), 2)

        roadmap = [s for s in presentation.slides if s.layout_type == "roadmap"][0]
        step_circles = [e for e in roadmap.elements if e.type == "badge" and e.shape_type == "oval"]
        connectors = [e for e in roadmap.elements if e.type == "accent"]
        self.assertEqual(len(step_circles), 4)
        self.assertEqual(len(connectors), 3)

    def test_every_slide_has_consistent_identity(self) -> None:
        req = GenerateRequest(
            prompt="chiến lược AI doanh nghiệp",
            num_slides=4,
            style="Minimal",
        )
        presentation = generate_fallback_presentation(req)
        for slide in presentation.slides:
            ids = {e.morph_id for e in slide.elements}
            self.assertIn("badge_header", ids)
            self.assertIn("section_kicker", ids)
            self.assertIn("title_slide", ids)
            self.assertIn("footer_topic", ids)
            self.assertIn("footer_page", ids)


if __name__ == "__main__":
    unittest.main()
