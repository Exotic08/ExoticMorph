"""
ExoticMorph Application Configuration
~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~
Quản lý cấu hình môi trường, API keys (OpenAI / Gemini), CORS origins và thiết lập máy chủ
thông qua pydantic-settings.

Nâng cấp trong đợt rework:
- Bỏ "*" khỏi ALLOWED_ORIGINS mặc định (secure-by-default); wildcard chỉ kích hoạt
  khi chủ động set biến môi trường ALLOWED_ORIGINS=*.
- PORT đọc tự nhiên qua pydantic-settings (bỏ hack os.environ), có validator
  xử lý chuỗi rỗng mà Render/Docker hay truyền.
"""

import json
from typing import List, Literal, Optional, Union

from pydantic import field_validator
from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    """Cấu hình toàn cục cho ExoticMorph Backend."""

    model_config = SettingsConfigDict(
        env_file=".env",
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
