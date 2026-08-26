"""
ExoticMorph Application Configuration
~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~
Quản lý cấu hình môi trường, API keys (OpenAI / Gemini), CORS origins và thiết lập máy chủ
thông qua pydantic-settings.

Nâng cấp v5 (Debug LLM Connection):
- **Validator API key chống "chuỗi rỗng giả dạng"**: strip khoảng trắng và
  chuyển "", "   " → None. Render/Docker rất hay inject biến rỗng khiến key
  "tồn tại" nhưng vô dụng và gây lỗi 401 khó hiểu.
- **Phát hiện file .env bền vững**: ưu tiên ``./.env`` (CWD); nếu không có thì
  dò ``<backend_root>/.env`` (thư mục chứa package ``app``) — tránh lỗi chạy
  lệnh từ thư mục khác khiến .env bị bỏ qua lặng lẽ và app rơi vào 503.
- **log_llm_status()**: in trạng thái key đã mask (VD ``AIza...**** (39 ký tự)``)
  ra console khi startup — lập trình viên thấy ngay key có được nạp hay không
  mà không rò rỉ secret.
"""

import logging
import os
from pathlib import Path
from typing import List, Literal, Optional, Union

from pydantic import field_validator
from pydantic_settings import BaseSettings, SettingsConfigDict

logger = logging.getLogger("exoticmorph.config")


def _discover_env_file() -> Optional[str]:
    """Tìm file .env: ưu tiên CWD, sau đó thư mục backend (cha của package app)."""
    cwd_env = Path.cwd() / ".env"
    if cwd_env.is_file():
        return str(cwd_env)
    backend_env = Path(__file__).resolve().parents[1] / ".env"  # exoticmorph-backend/.env
    if backend_env.is_file():
        return str(backend_env)
    return None  # Không có file .env — chỉ dùng biến môi trường hệ thống


_ENV_FILE = _discover_env_file()


class Settings(BaseSettings):
    """Cấu hình toàn cục cho ExoticMorph Backend."""

    model_config = SettingsConfigDict(
        env_file=_ENV_FILE,
        env_file_encoding="utf-8",
        extra="ignore",
    )

    # Nhà cung cấp LLM mặc định
    LLM_PROVIDER: Literal["openai", "gemini", "mock"] = "openai"

    # Cấu hình OpenAI
    OPENAI_API_KEY: Optional[str] = None
    OPENAI_MODEL: str = "gpt-4o"

    # Cấu hình Google Gemini
    GEMINI_API_KEY: Optional[str] = None
    GEMINI_MODEL: str = "gemini-1.5-pro"

    # Cấu hình Máy chủ & Mạng (Render sẽ cung cấp biến PORT)
    HOST: str = "0.0.0.0"
    PORT: int = 8000
    DEBUG: bool = False

    # Danh sách tên miền được phép truy cập (CORS).
    # Lưu ý: KHÔNG đặt "*" mặc định — muốn mở toàn bộ thì set biến môi trường
    # ALLOWED_ORIGINS=* một cách chủ động. Domain *.vercel.app động do
    # allow_origin_regex ở main.py đảm nhiệm.
    ALLOWED_ORIGINS: Union[List[str], str] = [
        "http://localhost:3000",
        "http://127.0.0.1:3000",
    ]

    @field_validator("OPENAI_API_KEY", "GEMINI_API_KEY", mode="before")
    @classmethod
    def normalize_api_key(cls, value: Union[str, None]) -> Optional[str]:
        """Chống key rỗng giả dạng: strip + chuyển ''/'   ' thành None.

        Bắt đúng bệnh phổ biến trên Render/Docker: biến môi trường được khai
        báo nhưng để trống → SDK nhận chuỗi rỗng → 401 khó hiểu, trong khi
        logic bool(key) có thể bị đánh lừa bởi chuỗi chỉ gồm khoảng trắng.
        """
        if value is None:
            return None
        if not isinstance(value, str):
            value = str(value)
        cleaned = value.strip()
        if not cleaned:
            return None
        return cleaned

    @field_validator("PORT", mode="before")
    @classmethod
    def parse_port(cls, value: Union[str, int]) -> int:
        """Render/Docker đôi khi truyền PORT rỗng -> dùng default 8000 thay vì crash."""
        if isinstance(value, str) and not value.strip():
            return 8000
        return value

    @field_validator("ALLOWED_ORIGINS", mode="before")
    @classmethod
    def parse_allowed_origins(cls, value: Union[str, List[str]]) -> List[str]:
        """Cho phép truyền chuỗi phân tách bởi dấu phẩy trong biến môi trường Render/Docker."""
        if isinstance(value, str):
            clean_str = value.strip()
            if clean_str.startswith("[") and clean_str.endswith("]"):
                try:
                    import json

                    return json.loads(clean_str)
                except json.JSONDecodeError:
                    pass
            # Tách bằng dấu phẩy
            return [origin.strip() for origin in clean_str.split(",") if origin.strip()]
        return value

    @field_validator("DEBUG", mode="before")
    @classmethod
    def parse_debug(cls, value: Union[str, bool]) -> bool:
        """Chấp nhận cả "true"/"false" chữ thường từ biến môi trường."""
        if isinstance(value, str):
            return value.strip().lower() in ("1", "true", "yes", "on")
        return value


settings = Settings()


# =============================================================================
# STARTUP DIAGNOSTICS — KHÔNG BAO GIỜ log nguyên key (chỉ mask)
# =============================================================================

def mask_secret(key: Optional[str]) -> str:
    """Mask API key: chỉ lộ 4 ký tự đầu + độ dài, phần còn lại che bằng ****."""
    if not key:
        return "<trống>"
    key = key.strip()
    if len(key) <= 8:
        return f"{key[:2]}**** ({len(key)} ký tự)"
    return f"{key[:4]}...**** ({len(key)} ký tự)"


def describe_key_status(env_name: str, key: Optional[str]) -> str:
    """Mô tả trạng thái nạp của một biến môi trường API key."""
    raw_env = os.environ.get(env_name)
    if key:
        suffix = "từ OS env" if raw_env == key else "từ .env/mặc định"
        return f"{env_name}: ✅ ĐÃ NẠP {mask_secret(key)} [{suffix}]"
    if raw_env is not None:
        # Biến tồn tại trong môi trường nhưng sau strip thành rỗng
        return f"{env_name}: ⚠️ BIẾN TỒN TẠI NHƯNG RỖNG/khoảng trắng — key KHÔNG được nạp"
    return f"{env_name}: ❌ CHƯA KHAI BÁO"


def log_llm_status() -> dict:
    """In báo cáo trạng thái cấu hình LLM ra console (an toàn, đã mask key).

    Được gọi 1 lần khi app khởi động (main.py) để lập trình viên thấy ngay:
      - File .env có được đọc hay không
      - Provider đang chọn + model
      - Từng API key: đã nạp (masked) / rỗng / chưa khai báo
    Trả về dict status dùng cho /health hoặc test.
    """
    status = {
        "env_file": _ENV_FILE or "<không tìm thấy — chỉ dùng OS env>",
        "llm_provider": settings.LLM_PROVIDER,
        "openai_model": settings.OPENAI_MODEL,
        "gemini_model": settings.GEMINI_MODEL,
        "openai_configured": bool(settings.OPENAI_API_KEY),
        "gemini_configured": bool(settings.GEMINI_API_KEY),
    }

    lines = [
        "=" * 72,
        "🔍 EXOTICMORPH LLM STARTUP DIAGNOSTICS",
        f"  .env file đọc được : {status['env_file']}",
        f"  LLM_PROVIDER       : {settings.LLM_PROVIDER}",
        f"  OPENAI_MODEL       : {settings.OPENAI_MODEL}",
        f"  GEMINI_MODEL       : {settings.GEMINI_MODEL}",
        f"  {describe_key_status('OPENAI_API_KEY', settings.OPENAI_API_KEY)}",
        f"  {describe_key_status('GEMINI_API_KEY', settings.GEMINI_API_KEY)}",
    ]
    if not settings.OPENAI_API_KEY and not settings.GEMINI_API_KEY:
        lines.append(
            "  ⛔ CẢNH BÁO: Không có API key nào được nạp — mọi request sinh slide "
            "sẽ trả HTTP 503. Hãy khai báo GEMINI_API_KEY hoặc OPENAI_API_KEY."
        )
    lines.append("=" * 72)

    for line in lines:
        logger.warning(line)  # WARNING để in ra console kể cả khi chưa basicConfig

    return status
