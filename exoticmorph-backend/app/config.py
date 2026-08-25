"""
ExoticMorph Application Configuration
~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~
Quản lý cấu hình môi trường, API keys (OpenAI / Gemini), CORS origins và thiết lập máy chủ
thông qua pydantic-settings.
"""

import os
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
    PORT: int = int(os.environ.get("PORT", 8000))
    DEBUG: bool = False

    # Danh sách tên miền được phép truy cập (CORS)
    # Hỗ trợ cả chuỗi phân tách bởi dấu phẩy hoặc List JSON
    ALLOWED_ORIGINS: Union[List[str], str] = [
        "http://localhost:3000",
        "http://127.0.0.1:3000",
        "http://0.0.0.0:3000",
        "https://*.vercel.app",
        "*",
    ]

    @field_validator("ALLOWED_ORIGINS", mode="before")
    @classmethod
    def parse_allowed_origins(cls, value: Union[str, List[str]]) -> List[str]:
        """Cho phép truyền chuỗi phân tách bởi dấu phẩy trong biến môi trường Render/Docker."""
        if isinstance(value, str):
            clean_str = value.strip()
            if clean_str.startswith("[") and clean_str.endswith("]"):
                import json
                try:
                    return json.loads(clean_str)
                except json.JSONDecodeError:
                    pass
            # Tách bằng dấu phẩy
            return [origin.strip() for origin in clean_str.split(",") if origin.strip()]
        return value


settings = Settings()
