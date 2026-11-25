"""
Cost Guard (Redis) - ngân sách theo THÁNG cho từng user, kiểm tra + trừ tiền NGUYÊN TỬ.

Exercise 4.4: check_budget(user_id, estimated_cost) -> bool
  - Mỗi user có budget $10/tháng.
  - Chi tiêu lưu trong Redis, key `budget:{user_id}:{YYYY-MM}` -> sang tháng mới là key mới,
    tức là tự "reset"; key của tháng cũ tự hết hạn nhờ TTL.

Khác với lời giải mẫu trong CODE_LAB (GET -> so sánh -> INCRBYFLOAT):
  1. Atomic: "đọc, so sánh, cộng" nằm trong MỘT Lua script nên Redis chạy trọn vẹn script
     đó, không request nào chen vào giữa. Lời giải mẫu có race: hai request cùng GET ra 9.8,
     cùng thấy 9.8 + 0.5 <= 10 ... rồi cùng cộng => tiêu quá budget.
  2. Lưu bằng số nguyên micro-USD (1 USD = 1_000_000) và dùng INCRBY, không dùng float,
     để không bị sai số khi cộng nhiều lần (0.1 + 0.2 != 0.3).
  3. TTL đặt bằng EXPIREAT tuyệt đối (đầu tháng sau + 1 ngày đệm), không phải "32 ngày"
     tính từ lần ghi cuối, nên key luôn hết hạn đúng lúc, không bị gia hạn mãi.
  4. Từ chối cost âm / NaN / inf (cost âm sẽ thành cách "hoàn tiền" để lách budget).

Cách dùng với LLM thật (ước tính trước, đối soát sau):
    est = estimate_cost(prompt)                 # ước tính theo độ dài prompt + max_tokens
    if not guard.check_budget(user, est):       # giữ chỗ (reserve) est ngay lập tức
        raise HTTPException(402, ...)
    try:
        answer, actual = call_llm(prompt)       # chi phí thật biết sau khi gọi xong
    except Exception:
        guard.reconcile(user, est, 0.0)         # LLM lỗi => trả lại phần đã giữ chỗ
        raise
    guard.reconcile(user, est, actual)          # chênh lệch (actual - est) được cộng/trừ
"""
from __future__ import annotations

import math
import os
import time
from datetime import datetime, timezone
from typing import Callable, Optional

import redis

MONTHLY_BUDGET_USD = 10.0
MICRO = 1_000_000          # 1 USD = 1_000_000 micro-USD (lưu số nguyên)
GRACE_SECONDS = 24 * 3600  # key sống thêm 1 ngày sau khi hết tháng (để còn đối soát / audit)

# Chạy nguyên tử trong Redis. KEYS[1] = key tháng của user.
# ARGV[1] = chi phí ước tính (micro-USD), ARGV[2] = budget (micro-USD), ARGV[3] = unix time hết hạn.
# Trả 1 nếu được phép (đã cộng vào chi tiêu), 0 nếu sẽ vượt budget (KHÔNG cộng gì cả).
_CHECK_AND_RESERVE_LUA = """
local spent = tonumber(redis.call('GET', KEYS[1]) or '0')
local cost  = tonumber(ARGV[1])
local budget = tonumber(ARGV[2])
if spent + cost > budget then
    return 0
end
redis.call('INCRBY', KEYS[1], cost)
redis.call('EXPIREAT', KEYS[1], tonumber(ARGV[3]))
return 1
"""

# Điều chỉnh sau khi biết chi phí thật. Không kiểm tra budget (tiền đã tiêu rồi),
# nhưng không để tổng chi tiêu xuống dưới 0.
_ADJUST_LUA = """
local spent = tonumber(redis.call('GET', KEYS[1]) or '0')
local new = spent + tonumber(ARGV[1])
if new < 0 then new = 0 end
redis.call('SET', KEYS[1], new)
redis.call('EXPIREAT', KEYS[1], tonumber(ARGV[2]))
return new
"""


def _to_micro(usd: float) -> int:
    if not isinstance(usd, (int, float)) or isinstance(usd, bool) or not math.isfinite(usd):
        raise ValueError(f"cost phải là số hữu hạn, nhận {usd!r}")
    return int(round(usd * MICRO))


class RedisBudgetGuard:
    def __init__(
        self,
        client: redis.Redis,
        monthly_budget_usd: float = MONTHLY_BUDGET_USD,
        clock: Callable[[], float] = time.time,
    ):
        self.r = client
        self.budget_micro = _to_micro(monthly_budget_usd)
        self._clock = clock  # tiêm được đồng hồ giả để test chuyển tháng
        self._reserve = client.register_script(_CHECK_AND_RESERVE_LUA)
        self._adjust = client.register_script(_ADJUST_LUA)

    # ---- helper về tháng / key / TTL ----------------------------------------
    def _month(self) -> str:
        return datetime.fromtimestamp(self._clock(), tz=timezone.utc).strftime("%Y-%m")

    def key(self, user_id: str) -> str:
        return f"budget:{user_id}:{self._month()}"

    def _expire_at(self) -> int:
        """Unix time của 00:00 UTC ngày đầu tháng sau, cộng 1 ngày đệm."""
        now = datetime.fromtimestamp(self._clock(), tz=timezone.utc)
        y, m = (now.year + 1, 1) if now.month == 12 else (now.year, now.month + 1)
        first_next = datetime(y, m, 1, tzinfo=timezone.utc)
        return int(first_next.timestamp()) + GRACE_SECONDS

    # ---- API chính -----------------------------------------------------------
    def check_budget(self, user_id: str, estimated_cost: float) -> bool:
        """True và GIỮ CHỖ estimated_cost nếu tổng chi tiêu tháng này + cost <= budget;
        False (không đổi gì) nếu sẽ vượt. Kiểm tra + cộng là một thao tác nguyên tử."""
        cost = _to_micro(estimated_cost)
        if cost < 0:
            raise ValueError("estimated_cost không được âm")
        ok = self._reserve(
            keys=[self.key(user_id)],
            args=[cost, self.budget_micro, self._expire_at()],
        )
        return bool(ok)

    def reconcile(self, user_id: str, estimated_cost: float, actual_cost: float) -> float:
        """Sau khi gọi LLM: thay phần đã giữ chỗ (estimated) bằng chi phí thật (actual).
        Trả về tổng chi tiêu tháng này (USD)."""
        est, actual = _to_micro(estimated_cost), _to_micro(actual_cost)
        if est < 0 or actual < 0:
            raise ValueError("estimated_cost / actual_cost không được âm")
        delta = actual - est
        new = self._adjust(keys=[self.key(user_id)], args=[delta, self._expire_at()])
        return int(new) / MICRO

    def spent_usd(self, user_id: str) -> float:
        return int(self.r.get(self.key(user_id)) or 0) / MICRO

    def remaining_usd(self, user_id: str) -> float:
        return max(0.0, (self.budget_micro - int(self.r.get(self.key(user_id)) or 0)) / MICRO)


# ---- Hàm cấp module đúng chữ ký đề bài: check_budget(user_id, estimated_cost) -> bool ----
_default_guard: Optional[RedisBudgetGuard] = None


def _guard() -> RedisBudgetGuard:
    global _default_guard
    if _default_guard is None:
        client = redis.Redis.from_url(
            os.getenv("REDIS_URL", "redis://localhost:6379/0"), decode_responses=True
        )
        _default_guard = RedisBudgetGuard(client)
    return _default_guard


def check_budget(user_id: str, estimated_cost: float) -> bool:
    return _guard().check_budget(user_id, estimated_cost)
