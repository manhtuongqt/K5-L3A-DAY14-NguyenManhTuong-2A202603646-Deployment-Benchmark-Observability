"""
Cost guard (tiêu chí 8).

  • Cộng dồn chi phí LLM (tính theo token) vào Redis
  • Tổng chi phí vượt DAILY_BUDGET_USD (hoặc MONTHLY_BUDGET_USD) → HTTP 402

Giới hạn đã biết: check_budget() (đọc) và record_cost() (ghi) là hai bước riêng,
nên vài request đang chạy cùng lúc đều có thể qua bước kiểm tra rồi cùng ghi chi phí
→ tổng có thể vượt budget một chút. Muốn chặn tuyệt đối thì kiểm tra + cộng trong
một script Lua duy nhất (xem Part 4).
"""
from datetime import datetime, timezone

from fastapi import HTTPException

from app.config import settings
from app.redis_client import r

# Giá USD / 1K tokens (tham khảo gpt-4o-mini)
PRICE_INPUT_PER_1K = 0.00015
PRICE_OUTPUT_PER_1K = 0.0006

DAILY_TTL = 2 * 24 * 3600      # key ngày sống 2 ngày
MONTHLY_TTL = 32 * 24 * 3600   # key tháng sống 32 ngày


def estimate_tokens(text: str) -> int:
    """Mock LLM không trả số token, nên ước lượng: ~4 ký tự = 1 token (quy tắc gần đúng)."""
    return max(1, len(text) // 4)


def _keys() -> tuple[str, str]:
    """Tên key Redis theo ngày / tháng (giờ UTC)."""
    now = datetime.now(timezone.utc)
    return f"cost:daily:{now:%Y-%m-%d}", f"cost:monthly:{now:%Y-%m}"


def check_budget() -> None:
    """Gọi TRƯỚC khi gọi LLM. Hết budget → HTTP 402."""
    daily_key, monthly_key = _keys()
    daily_spent = float(r.get(daily_key) or 0)
    if daily_spent >= settings.daily_budget_usd:
        raise HTTPException(status_code=402, detail="Daily budget exceeded")
    if settings.monthly_budget_usd is not None:
        monthly_spent = float(r.get(monthly_key) or 0)
        if monthly_spent >= settings.monthly_budget_usd:
            raise HTTPException(status_code=402, detail="Monthly budget exceeded")


def record_cost(input_tokens: int, output_tokens: int) -> float:
    """Gọi SAU khi gọi LLM. Cộng chi phí của request vào tổng, trả về chi phí request (USD)."""
    cost = (input_tokens / 1000) * PRICE_INPUT_PER_1K + (output_tokens / 1000) * PRICE_OUTPUT_PER_1K
    daily_key, monthly_key = _keys()
    pipe = r.pipeline(transaction=True)
    pipe.incrbyfloat(daily_key, cost)  # INCRBYFLOAT là nguyên tử: nhiều worker cộng cùng lúc vẫn đúng
    pipe.expire(daily_key, DAILY_TTL)
    pipe.incrbyfloat(monthly_key, cost)
    pipe.expire(monthly_key, MONTHLY_TTL)
    pipe.execute()
    return cost
