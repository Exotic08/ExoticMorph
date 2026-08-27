"""Regression tests for the v5 LLM-only pipeline (no silent fallback).

Covers the fix for "văn mẫu B2B rác" leaking into generated slides:
- The heuristic fallback generator is GONE from llm_service (no more
  "Nhu cầu {topic} đang tăng tốc" / "Điểm nghẽn kìm hãm" template strings).
- Entry point raises LLMConfigurationError / LLMGenerationError with a clear,
  user-facing diagnosis instead of returning low-quality slides.
- Parse/validation retry uses a temperature LADDER (0.4 -> 0.2 -> 0.7) and
  re-asks the LLM with the previous error as feedback.
- Content violating the STRICT BAN template list is rejected and re-generated.
"""

from __future__ import annotations

import asyncio
import os
import sys
import unittest
from unittest import mock

BACKEND_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if BACKEND_ROOT not in sys.path:
    sys.path.insert(0, BACKEND_ROOT)

from app.config import (  # noqa: E402
    Settings,
    describe_key_status,
    log_llm_status,
    mask_secret,
    settings,
)
from app.schemas.slide_schema import (  # noqa: E402
    GenerateRequest,
    LLMOutput,
    LayoutType,
    SlideData,
)
from app.services import llm_service  # noqa: E402
from app.services.llm_service import (  # noqa: E402
    LLMConfigurationError,
    LLMGenerationError,
    REASON_API_KEY_INVALID,
    REASON_NETWORK_TIMEOUT,
    REASON_OUTPUT_INVALID,
    REASON_PERMISSION_DENIED,
    REASON_QUOTA_EXCEEDED,
    SYSTEM_PROMPT,
    TEMPERATURE_LADDER,
    _content_smell_check,
    _diagnose_exception,
    _extract_json_object,
    _parse_with_retry,
    _temperature_for_attempt,
    generate_presentation_with_llm,
)


def _valid_payload(num_slides: int = 2) -> dict:
    """Payload JSON hợp lệ tuyệt đối theo LLMOutput strict schema."""
    desc = (
        "Thuỷ tinh quay quanh Mặt Trời trong 88 ngày Trái Đất, là hành tinh "
        "nhỏ nhất và gần Mặt Trời nhất hệ mặt trời với quỹ đạo elip rất dẹt. "
        "Nhiệt độ bề mặt dao động từ -173 độ C ban đêm tới 427 độ C ban ngày."
    )
    slides = []
    for i in range(1, num_slides + 1):
        slides.append({
            "slide_number": i,
            "section": "CẤU TẠO" if i == 1 else "CƠ CHẾ",
            "slide_title": f"Khám phá chuyên sâu hành tinh số {i}",
            "cards": [
                {
                    "morph_id": "card_1",
                    "title": f"Thuỷ tinh hoàn thành quỹ đạo trong 88 ngày {i}",
                    "description": desc,
                    "color_theme": "#8B5CF6",
                    "order": 0,
                }
            ],
        })
    return {"topic": "Hệ Mặt Trời", "slides": slides}


class NoFallbackContractTests(unittest.TestCase):
    def test_fallback_generators_removed(self) -> None:
        """Văn mẫu heuristic B2B phải bị xoá sạch khỏ module."""
        self.assertFalse(hasattr(llm_service, "generate_fallback_presentation"))
        self.assertFalse(hasattr(llm_service, "_build_fallback_presentation"))
        self.assertFalse(hasattr(llm_service, "_emergency_presentation"))
        self.assertFalse(hasattr(llm_service, "_extract_prompt_facts"))

    def test_system_prompt_enforces_dynamic_persona(self) -> None:
        for needle in (
            "NHẬP VAI",
            "DYNAMIC ROLEPLAY",
            "NHÀ THIÊN VĂN HỌC",
            "Robusta",
            "Buôn Ma Thuột",
            "DOMAIN VOCABULARY",
            "STRICT BAN",
            "ưu tiên số 1",
            "Nhu cầu",
            "Điểm nghẽn",
            "Cái giá của việc chần chừ",
        ):
            self.assertIn(needle, SYSTEM_PROMPT)

    def test_user_prompt_wraps_topic_with_delimiters(self) -> None:
        req = GenerateRequest(prompt="giải thích hệ mặt trời", num_slides=3)
        text = llm_service._build_user_prompt(req)
        self.assertIn("=== USER TOPIC TO GENERATE ===", text)
        self.assertIn("=== END OF USER TOPIC ===", text)
        self.assertIn("giải thích hệ mặt trời", text)

    def test_user_prompt_explains_auto_style_contract(self) -> None:
        req = GenerateRequest(prompt="báo cáo y học về vaccine mRNA", num_slides=3, style="AUTO")
        text = llm_service._build_user_prompt(req)
        self.assertIn("Phong cách thiết kế: AUTO", text)
        self.assertIn("top-level `style`", text)
        self.assertIn("không được trả AUTO", text)

    def test_llm_output_rejects_auto_as_resolved_style(self) -> None:
        payload = _valid_payload()
        payload["style"] = "AUTO"
        with self.assertRaises(Exception):
            LLMOutput.model_validate(payload)


class TemperatureLadderTests(unittest.TestCase):
    def test_ladder_values(self) -> None:
        self.assertEqual(TEMPERATURE_LADDER, (0.4, 0.2, 0.7))

    def test_temperature_for_attempt(self) -> None:
        self.assertEqual(
            [_temperature_for_attempt(a) for a in (1, 2, 3, 99)],
            [0.4, 0.2, 0.7, 0.7],
        )


class DiagnosisTests(unittest.TestCase):
    def _fake_exc(self, *, status=None, name="FakeError", msg=""):
        fake_cls = type(name, (Exception,), {})  # class động mô phỏng SDK errors
        exc = fake_cls(msg)
        exc.status_code = status
        return exc

    def test_401_maps_to_api_key_invalid(self) -> None:
        reason, _ = _diagnose_exception(self._fake_exc(status=401), "gemini")
        self.assertEqual(reason, REASON_API_KEY_INVALID)

    def test_403_maps_to_permission(self) -> None:
        reason, _ = _diagnose_exception(self._fake_exc(status=403), "openai")
        self.assertEqual(reason, REASON_PERMISSION_DENIED)

    def test_429_maps_to_quota(self) -> None:
        reason, hint = _diagnose_exception(
            self._fake_exc(status=429, msg="rate limit exceeded"), "gemini"
        )
        self.assertEqual(reason, REASON_QUOTA_EXCEEDED)
        self.assertTrue(hint)  # hint phải có hướng dẫn khắc phục

    def test_api_key_hint_names_env_variable(self) -> None:
        reason, hint = _diagnose_exception(self._fake_exc(status=401), "gemini")
        self.assertEqual(reason, REASON_API_KEY_INVALID)
        self.assertIn("GEMINI_API_KEY", hint)

    def test_gemini_unauthenticated_class_name(self) -> None:
        reason, _ = _diagnose_exception(
            self._fake_exc(name="Unauthenticated", msg="API key not valid"),
            "gemini",
        )
        self.assertEqual(reason, REASON_API_KEY_INVALID)

    def test_gemini_resource_exhausted(self) -> None:
        reason, _ = _diagnose_exception(
            self._fake_exc(name="ResourceExhausted", msg="Quota exceeded"),
            "gemini",
        )
        self.assertEqual(reason, REASON_QUOTA_EXCEEDED)

    def test_network_timeout(self) -> None:
        reason, _ = _diagnose_exception(
            self._fake_exc(name="APITimeoutError", msg="request timed out"),
            "openai",
        )
        self.assertEqual(reason, REASON_NETWORK_TIMEOUT)

    def test_parse_failure_maps_to_output_invalid(self) -> None:
        reason, _ = _diagnose_exception(
            ValueError("Không tìm thấy JSON object hợp lệ"), "gemini"
        )
        self.assertEqual(reason, REASON_OUTPUT_INVALID)


class ParseRetryTests(unittest.TestCase):
    def _req(self) -> GenerateRequest:
        return GenerateRequest(prompt="giải thích hệ mặt trời", num_slides=2)

    def test_retry_uses_temperature_ladder_and_recovers(self) -> None:
        import json

        calls: list[float] = []
        good = json.dumps(_valid_payload(), ensure_ascii=False)

        async def getter(messages, temperature):
            calls.append(temperature)
            if len(calls) < 3:
                return "đây không phải JSON"  # 2 lần parse fail đầu
            return good

        async def main():
            with mock.patch("asyncio.sleep", new=mock.AsyncMock()):
                return await _parse_with_retry(
                    getter, lambda t: [t], self._req(), "FakeLLM"
                )
        result = asyncio.run(main())
        self.assertIsInstance(result, LLMOutput)
        self.assertEqual(calls, [0.4, 0.2, 0.7])

    def test_retry_passes_error_feedback_into_prompt(self) -> None:
        seen_prompts: list[str] = []

        async def getter(messages, temperature):
            seen_prompts.append(messages[0])
            if len(seen_prompts) < 2:
                return "không phải json"
            import json
            return json.dumps(_valid_payload(), ensure_ascii=False)

        async def main():
            with mock.patch("asyncio.sleep", new=mock.AsyncMock()):
                return await _parse_with_retry(
                    getter, lambda t: [t], self._req(), "FakeLLM"
                )
        asyncio.run(main())
        self.assertEqual(len(seen_prompts), 2)
        self.assertIn("LỖI LẦN TRƯỚC", seen_prompts[1])

    def test_retry_exhaustion_raises_value_error(self) -> None:
        async def getter(messages, temperature):
            return "vẫn không phải json"

        async def main():
            with mock.patch("asyncio.sleep", new=mock.AsyncMock()):
                await _parse_with_retry(getter, lambda t: [t], self._req(), "FakeLLM")

        with self.assertRaises(ValueError):
            asyncio.run(main())

    def test_banned_template_content_triggers_rewrite(self) -> None:
        """Nội dung dính văn mẫu bị cấm phải bị reject + viết lại (không chấp nhận âm thầm)."""
        import json

        banned = _valid_payload()
        banned["slides"][0]["cards"][0]["title"] = "Nhu cầu hệ mặt trời đang tăng tốc"

        calls: list[float] = []

        async def getter(messages, temperature):
            calls.append(temperature)
            payload = banned if len(calls) < 2 else _valid_payload()
            return json.dumps(payload, ensure_ascii=False)

        async def main():
            with mock.patch("asyncio.sleep", new=mock.AsyncMock()):
                return await _parse_with_retry(
                    getter, lambda t: [t], self._req(), "FakeLLM"
                )
        result = asyncio.run(main())
        self.assertEqual(
            result.slides[0].cards[0].title,
            "Thuỷ tinh hoàn thành quỹ đạo trong 88 ngày 1",
        )
        self.assertEqual(len(calls), 2)

    def test_extract_json_tolerates_fences_and_prose(self) -> None:
        obj = _extract_json_object('```json\n{"a": 1}\n```')
        self.assertEqual(obj, {"a": 1})
        obj = _extract_json_object('chữ linh tinh {"a": {"b": "x{}"}} hậu tố')
        self.assertEqual(obj, {"a": {"b": "x{}"}})
        with self.assertRaises(ValueError):
            _extract_json_object("không có json nào")


class SmellCheckTests(unittest.TestCase):
    def test_flags_banned_b2b_templates(self) -> None:
        payload = _valid_payload()
        payload["slides"][0]["cards"][0]["title"] = "Nhu cầu hệ mặt trời đang tăng tốc"
        result = LLMOutput.model_validate(payload)
        violations = _content_smell_check(result, "hệ mặt trời")
        self.assertTrue(any("nhu cầu" in v or "tăng tốc" in v for v in violations))

    def test_clean_content_passes(self) -> None:
        result = LLMOutput.model_validate(_valid_payload())
        self.assertEqual(_content_smell_check(result, "hệ mặt trời solar system"), [])


class MaskingTests(unittest.TestCase):
    def test_masks_key_query_param(self) -> None:
        masked = llm_service._mask_sensitive(
            "https://generativelanguage.googleapis.com/v1/models?key=AIzaSyDeAdBeEfGhIjKlMnOpQrSt"
        )
        self.assertNotIn("AIzaSyDeAdBeEfGhIjKlMnOpQrSt", masked)
        self.assertIn("key=****", masked)

    def test_masks_configured_key_inside_error(self) -> None:
        saved = settings.GEMINI_API_KEY
        settings.GEMINI_API_KEY = "AIzaSECRETKEY123456789"
        try:
            masked = llm_service._mask_sensitive(
                "400 API key not valid: AIzaSECRETKEY123456789 passed"
            )
        finally:
            settings.GEMINI_API_KEY = saved
        self.assertNotIn("AIzaSECRETKEY123456789", masked)
        self.assertIn("AIza...****", masked)

    def test_summarize_exc_flattens_and_truncates(self) -> None:
        exc = Exception("lỗi\nnhiều\ndòng " + "x" * 500)
        out = llm_service._summarize_exc(exc, limit=100)
        self.assertNotIn("\n", out)
        self.assertLessEqual(len(out), 100)
        self.assertTrue(out.startswith("Exception:"))


class ConfigValidatorTests(unittest.TestCase):
    def test_whitespace_only_key_becomes_none(self) -> None:
        s = Settings(GEMINI_API_KEY="   ", _env_file=None)
        self.assertIsNone(s.GEMINI_API_KEY)

    def test_empty_key_becomes_none(self) -> None:
        s = Settings(OPENAI_API_KEY="", _env_file=None)
        self.assertIsNone(s.OPENAI_API_KEY)

    def test_valid_key_is_stripped_and_kept(self) -> None:
        s = Settings(GEMINI_API_KEY="  AIzaValidKey123  ", _env_file=None)
        self.assertEqual(s.GEMINI_API_KEY, "AIzaValidKey123")

    def test_mask_secret_never_leaks_full_key(self) -> None:
        for key in ("AIzaSyDeAdBeEfGhIjKlMnOpQrStUvWxYz12345", "short", None, ""):
            masked = mask_secret(key if key else None)
            if key:
                self.assertNotEqual(masked, key)
                self.assertIn("****", masked)

    def test_describe_key_status_reports_empty_env_var(self) -> None:
        # Giả lập biến môi trường tồn tại nhưng rỗng (bệnh hay gặp trên Render)
        with mock.patch.dict(os.environ, {"GEMINI_API_KEY": ""}):
            text = describe_key_status("GEMINI_API_KEY", None)
        self.assertIn("RỖNG", text)

    def test_log_llm_status_returns_report_without_crash(self) -> None:
        report = log_llm_status()
        for key in ("env_file", "llm_provider", "openai_configured", "gemini_configured"):
            self.assertIn(key, report)


class GeminiSchemaSanitizerTests(unittest.TestCase):
    """Fix 'Unknown field for Schema: maxLength' — schema gửi Gemini phải thuần proto."""

    def test_sanitizer_strips_unsupported_fields(self) -> None:
        node = {
            "type": "object",
            "title": "LLMOutput",
            "additionalProperties": False,
            "properties": {
                "topic": {"type": "string", "minLength": 1, "maxLength": 300},
                "order": {"type": "integer", "minimum": 0, "maximum": 20, "default": 0},
            },
            "required": ["topic"],
        }
        out = llm_service._sanitize_for_gemini(node)
        self.assertEqual(out["type"], "OBJECT")
        self.assertNotIn("title", out)
        self.assertNotIn("additionalProperties", out)
        self.assertNotIn("maxLength", out["properties"]["topic"])
        self.assertNotIn("minLength", out["properties"]["topic"])
        self.assertNotIn("minimum", out["properties"]["order"])
        self.assertEqual(out["required"], ["topic"])

    def test_refs_are_resolved(self) -> None:
        schema = {
            "type": "object",
            "properties": {"slide": {"$ref": "#/$defs/Slide"}},
            "$defs": {"Slide": {"type": "object", "properties": {"n": {"type": "integer"}}}},
        }
        out = llm_service._sanitize_for_gemini(llm_service._resolve_json_refs(schema, schema["$defs"]))
        self.assertIn("n", out["properties"]["slide"]["properties"])

    def test_real_llmoutput_schema_is_proto_compatible(self) -> None:
        schema = llm_service._gemini_response_schema()
        self.assertIsNotNone(schema)
        self.assertEqual(schema.get("type"), "OBJECT")
        banned_keys = {"minLength", "maxLength", "pattern", "$ref", "$defs",
                       "additionalProperties", "maxItems", "minItems", "title"}

        def walk(n):
            if isinstance(n, dict):
                for k, v in n.items():
                    if k == "properties" and isinstance(v, dict):
                        # key dưới "properties" là tên FIELD (hợp lệ, vd "title"),
                        # không phải metadata JSON Schema → chỉ duyệt bên trong.
                        for sub in v.values():
                            walk(sub)
                        continue
                    self.assertNotIn(k, banned_keys, f"schema còn trường cấm: {k}")
                    walk(v)
            elif isinstance(n, list):
                for i in n:
                    walk(i)
        walk(schema)
        # cấu trúc sâu phải duỗi phẳng tới ContentCard
        slides = schema["properties"]["slides"]
        self.assertEqual(slides["type"], "ARRAY")
        cards = slides["items"]["properties"]["cards"]
        self.assertIn("morph_id", cards["items"]["properties"])


class ProviderPrecheckTests(unittest.TestCase):
    def setUp(self) -> None:
        self._saved = (settings.GEMINI_API_KEY, settings.OPENAI_API_KEY)

    def tearDown(self) -> None:
        settings.GEMINI_API_KEY, settings.OPENAI_API_KEY = self._saved

    def test_gemini_whitespace_key_raises_config_error_early(self) -> None:
        settings.GEMINI_API_KEY = "   "
        req = GenerateRequest(prompt="giải thích hệ mặt trờ", num_slides=2)
        with self.assertRaises(LLMConfigurationError) as ctx:
            asyncio.run(llm_service._generate_with_gemini(req))
        self.assertIn("GEMINI_API_KEY", str(ctx.exception))

    def test_provider_ready_rejects_whitespace(self) -> None:
        settings.GEMINI_API_KEY = "   "
        settings.OPENAI_API_KEY = "sk-test-123"
        self.assertFalse(llm_service._provider_ready("gemini"))
        self.assertTrue(llm_service._provider_ready("openai"))


class EntryPointTests(unittest.TestCase):
    def setUp(self) -> None:
        self._saved = (
            settings.LLM_PROVIDER, settings.OPENAI_API_KEY, settings.GEMINI_API_KEY,
        )

    def tearDown(self) -> None:
        settings.LLM_PROVIDER, settings.OPENAI_API_KEY, settings.GEMINI_API_KEY = self._saved

    def _req(self) -> GenerateRequest:
        return GenerateRequest(prompt="giải thích hệ mặt trời", num_slides=3)

    def test_no_api_key_raises_configuration_error(self) -> None:
        settings.LLM_PROVIDER = "gemini"
        settings.OPENAI_API_KEY = None
        settings.GEMINI_API_KEY = None
        with self.assertRaises(LLMConfigurationError) as ctx:
            asyncio.run(generate_presentation_with_llm(self._req()))
        self.assertIn("GEMINI_API_KEY", str(ctx.exception))

    def test_mock_provider_is_rejected(self) -> None:
        settings.LLM_PROVIDER = "mock"
        with self.assertRaises(LLMConfigurationError) as ctx:
            asyncio.run(generate_presentation_with_llm(self._req()))
        self.assertIn("mock", str(ctx.exception).lower())

    def test_all_providers_fail_raises_generation_error_with_diagnosis(self) -> None:
        settings.LLM_PROVIDER = "gemini"
        settings.GEMINI_API_KEY = "fake-key"
        settings.OPENAI_API_KEY = None

        async def boom(req):
            exc = Exception("API key not valid")
            exc.status_code = 401
            raise exc

        with mock.patch.dict(
            llm_service._PROVIDER_FUNCS, {"gemini": boom}, clear=True
        ):
            with self.assertRaises(LLMGenerationError) as ctx:
                asyncio.run(generate_presentation_with_llm(self._req()))
        msg = str(ctx.exception)
        self.assertIn("Gemini", msg)
        self.assertIn(REASON_API_KEY_INVALID, msg)
        self.assertIn("fallback", msg.lower())  # giải thích đã tắt fallback
        # v5: message phải kèm LỖI GỐC từ provider (debug connection requirement)
        self.assertIn("Lỗi gốc", msg)
        self.assertIn("API key not valid", msg)


class RoutesMappingTests(unittest.TestCase):
    """Endpoint phải map exception LLM sang HTTP 502/503 với message rõ ràng."""

    def setUp(self) -> None:
        self._saved = (
            settings.LLM_PROVIDER, settings.OPENAI_API_KEY, settings.GEMINI_API_KEY,
        )
        settings.LLM_PROVIDER = "gemini"
        settings.OPENAI_API_KEY = None
        settings.GEMINI_API_KEY = None

    def tearDown(self) -> None:
        settings.LLM_PROVIDER, settings.OPENAI_API_KEY, settings.GEMINI_API_KEY = self._saved

    def _req(self) -> GenerateRequest:
        return GenerateRequest(prompt="giải thích hệ mặt trời", num_slides=3)

    def test_generate_json_returns_503_without_config(self) -> None:
        from fastapi import HTTPException

        from app.api.routes import generate_presentation_json

        with self.assertRaises(HTTPException) as ctx:
            asyncio.run(generate_presentation_json(self._req()))
        self.assertEqual(ctx.exception.status_code, 503)
        self.assertIn("GEMINI_API_KEY", ctx.exception.detail)

    def test_health_endpoint_reports_masked_key_status(self) -> None:
        from app.api.routes import health_check

        settings.GEMINI_API_KEY = "AIzaTestKey123456789"
        data = asyncio.run(health_check())
        self.assertTrue(data["gemini_configured"])
        self.assertNotIn("AIzaTestKey123456789", data["gemini_key_status"])
        self.assertIn("****", data["gemini_key_status"])
        self.assertIn("openai_key_status", data)

    def test_generate_returns_502_with_diagnosis(self) -> None:
        from fastapi import HTTPException

        from app.api import routes

        settings.GEMINI_API_KEY = "fake-key"

        async def boom(req):
            exc = Exception("429 quota exceeded")
            exc.status_code = 429
            raise exc

        with mock.patch.dict(llm_service._PROVIDER_FUNCS, {"gemini": boom}, clear=True):
            with self.assertRaises(HTTPException) as ctx:
                asyncio.run(routes.generate_pptx_presentation(self._req()))
        self.assertEqual(ctx.exception.status_code, 502)
        self.assertIn(REASON_QUOTA_EXCEEDED, ctx.exception.detail)


class DynamicLayoutDiversityTests(unittest.TestCase):
    """Kiểm thử tính năng Dynamic Layout Diversity (5 kiểu layout + không trùng lặp liên tiếp)."""

    def test_layout_type_enum_values(self) -> None:
        self.assertEqual(LayoutType.CARDS_ROW.value, "CARDS_ROW")
        self.assertEqual(LayoutType.SPLIT_HERO.value, "SPLIT_HERO")
        self.assertEqual(LayoutType.STAT_GRID.value, "STAT_GRID")
        self.assertEqual(LayoutType.TIMELINE_STEPS.value, "TIMELINE_STEPS")
        self.assertEqual(LayoutType.GRID_2X2.value, "GRID_2X2")

    def test_slide_data_layout_type_coercion(self) -> None:
        from app.schemas.slide_schema import ContentCard
        desc = "Thủy tinh quay quanh Mặt Trời trong 88 ngày với quỹ đạo elip dẹt. Nhiệt độ cực hạn -173 đến 427 độ C."
        s1 = SlideData(
            slide_number=1,
            section="MỤC",
            slide_title="Tiêu đề",
            layout_type="split-hero",
            cards=[ContentCard(morph_id="c1", title="Tiêu đề 1", description=desc, color_theme="#8B5CF6", order=0)],
        )
        self.assertEqual(s1.layout_type, LayoutType.SPLIT_HERO)

    def test_split_hero_geometry(self) -> None:
        from app.services.layout_engine import _calculate_cards_geometry_inches
        boxes = _calculate_cards_geometry_inches(LayoutType.SPLIT_HERO, 3)
        self.assertEqual(len(boxes), 3)
        # Thẻ 0 (Hero) ở bên trái
        self.assertAlmostEqual(boxes[0][0], 0.8)
        # Thẻ 1 và 2 ở bên phải, cùng hoành độ x
        self.assertAlmostEqual(boxes[1][0], boxes[2][0])
        # Thẻ 1 ở trên thẻ 2
        self.assertLess(boxes[1][1], boxes[2][1])
        # Thẻ 0 rộng hơn thẻ 1
        self.assertGreater(boxes[0][2], boxes[1][2])

    def test_grid_2x2_geometry(self) -> None:
        from app.services.layout_engine import _calculate_cards_geometry_inches
        boxes = _calculate_cards_geometry_inches(LayoutType.GRID_2X2, 4)
        self.assertEqual(len(boxes), 4)
        # Thẻ 0 và 2 cùng hoành độ x trái
        self.assertAlmostEqual(boxes[0][0], boxes[2][0])
        # Thẻ 1 và 3 cùng hoành độ x phải
        self.assertAlmostEqual(boxes[1][0], boxes[3][0])
        # Thẻ 0 và 1 cùng tung độ y trên
        self.assertAlmostEqual(boxes[0][1], boxes[1][1])
        # Thẻ 2 và 3 cùng tung độ y dưới
        self.assertAlmostEqual(boxes[2][1], boxes[3][1])

    def test_stat_grid_font_size(self) -> None:
        from app.services.layout_engine import _card_title_font_size
        self.assertEqual(_card_title_font_size(3, LayoutType.STAT_GRID), 32)
        self.assertEqual(_card_title_font_size(4, LayoutType.STAT_GRID), 28)

    def test_consecutive_duplicate_layout_prevention(self) -> None:
        from app.schemas.slide_schema import ContentCard
        from app.services.layout_engine import compute_layout
        desc = "Thủy tinh quay quanh Mặt Trời trong 88 ngày với quỹ đạo elip dẹt. Nhiệt độ cực hạn -173 đến 427 độ C."
        slides = [
            SlideData(
                slide_number=i,
                section="MỤC",
                slide_title=f"Tiêu đề {i}",
                layout_type=LayoutType.CARDS_ROW,
                cards=[ContentCard(morph_id=f"c_{j}", title=f"Thẻ {j}", description=desc, color_theme="#8B5CF6", order=j) for j in range(3)],
            )
            for i in range(1, 6)
        ]
        output = LLMOutput(topic="Chủ đề", slides=slides)
        req = GenerateRequest(prompt="Chủ đề", num_slides=5)
        pres = compute_layout(output, req)
        layouts = [s.layout_type for s in pres.slides]
        for i in range(len(layouts) - 1):
            self.assertNotEqual(
                layouts[i], layouts[i + 1],
                f"Phát hiện slide {i+1} và slide {i+2} có cùng layout_type '{layouts[i]}'",
            )

    def test_build_pptx_with_all_5_layouts(self) -> None:
        import zipfile
        from app.schemas.slide_schema import ContentCard
        from app.services.generator_service import build_pptx_from_schema
        from app.services.layout_engine import compute_layout
        desc = "Thủy tinh quay quanh Mặt Trời trong 88 ngày với quỹ đạo elip dẹt. Nhiệt độ cực hạn -173 đến 427 độ C."
        types = [
            LayoutType.SPLIT_HERO,
            LayoutType.STAT_GRID,
            LayoutType.TIMELINE_STEPS,
            LayoutType.GRID_2X2,
            LayoutType.CARDS_ROW,
        ]
        slides = [
            SlideData(
                slide_number=i + 1,
                section=f"MỤC {i + 1}",
                slide_title=f"Tiêu đề slide {i + 1}",
                layout_type=types[i],
                cards=[
                    ContentCard(morph_id=f"c_{j}", title=f"Luận điểm {j + 1}", description=desc, color_theme="#8B5CF6", order=j)
                    for j in range(4 if types[i] in (LayoutType.GRID_2X2, LayoutType.TIMELINE_STEPS) else 3)
                ],
            )
            for i in range(5)
        ]
        output = LLMOutput(topic="5 Kiểu Bố Cục", slides=slides)
        req = GenerateRequest(prompt="5 Kiểu Bố Cục", num_slides=5)
        pres = compute_layout(output, req)
        pptx_buf = build_pptx_from_schema(pres)
        self.assertGreater(len(pptx_buf.getvalue()), 1000)
        with zipfile.ZipFile(pptx_buf, "r") as z:
            slides_xml = [n for n in z.namelist() if n.startswith("ppt/slides/slide") and n.endswith(".xml")]
            self.assertEqual(len(slides_xml), 5)


if __name__ == "__main__":
    unittest.main()
