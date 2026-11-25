"""
Config — 12-Factor: mọi cấu hình đọc từ biến môi trường.

Không có giá trị mặc định cho secret: AGENT_API_KEY mặc định là chuỗi rỗng,
và khi key rỗng thì auth từ chối MỌI request (xem auth.py).
"""
import os
from dataclasses import dataclass, field


def _optional_float(name: str):
    """Đọc biến số thực; chưa đặt hoặc để trống thì trả None (= không giới hạn)."""
    value = os.getenv(name, "").strip()
    return float(value) if value else None


@dataclass
class Settings:
    # default_factory: đọc env lúc tạo Settings(), không phải lúc định nghĩa class
    port: int = field(default_factory=lambda: int(os.getenv("PORT", "8000")))
    environment: str = field(default_factory=lambda: os.getenv("ENVIRONMENT", "development"))
    agent_api_key: str = field(default_factory=lambda: os.getenv("AGENT_API_KEY", ""))
    redis_url: str = field(default_factory=lambda: os.getenv("REDIS_URL", "redis://localhost:6379/0"))
    rate_limit_per_minute: int = field(default_factory=lambda: int(os.getenv("RATE_LIMIT_PER_MINUTE", "10")))
    daily_budget_usd: float = field(default_factory=lambda: float(os.getenv("DAILY_BUDGET_USD", "1.0")))
    monthly_budget_usd: float | None = field(default_factory=lambda: _optional_float("MONTHLY_BUDGET_USD"))
    log_level: str = field(default_factory=lambda: os.getenv("LOG_LEVEL", "INFO").upper())


settings = Settings()
