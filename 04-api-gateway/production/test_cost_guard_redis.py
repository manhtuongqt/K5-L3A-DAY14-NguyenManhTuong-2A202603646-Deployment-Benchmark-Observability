"""
Test cho cost_guard_redis.py - cần một Redis thật.

    docker run -d --rm --name k5-redis-test -p 127.0.0.1:6380:6379 redis:7-alpine
    REDIS_URL=redis://127.0.0.1:6380/0 python test_cost_guard_redis.py
"""
import os
import sys
import threading
import time
import uuid
from datetime import datetime, timezone

import redis

from cost_guard_redis import RedisBudgetGuard, GRACE_SECONDS

REDIS_URL = os.getenv("REDIS_URL", "redis://127.0.0.1:6380/0")
r = redis.Redis.from_url(REDIS_URL, decode_responses=True)
guard = RedisBudgetGuard(r)  # $10/tháng


def uid(prefix: str) -> str:
    return f"{prefix}-{uuid.uuid4().hex[:8]}"  # user id riêng cho mỗi test, không cần FLUSHDB


def naive_check_budget(user_id: str, estimated_cost: float) -> bool:
    """Lời giải mẫu trong CODE_LAB: GET -> so sánh -> INCRBYFLOAT (KHÔNG nguyên tử)."""
    key = guard.key(user_id)
    current = float(r.get(key) or 0)
    if current + estimated_cost > 10:
        return False
    r.incrbyfloat(key, estimated_cost)
    r.expire(key, 32 * 24 * 3600)
    return True


def hammer(fn, user_id: str, n_threads: int, cost: float) -> int:
    """n_threads thread cùng gọi fn(user_id, cost) vào cùng một thời điểm (Barrier)."""
    barrier = threading.Barrier(n_threads)
    results = []

    def worker():
        barrier.wait()
        results.append(fn(user_id, cost))

    threads = [threading.Thread(target=worker) for _ in range(n_threads)]
    for t in threads:
        t.start()
    for t in threads:
        t.join()
    return sum(results)


def test_sequential_until_exceeded():
    u = uid("seq")
    steps = [(3.0, True), (3.0, True), (3.0, True), (1.5, False), (1.0, True), (0.000001, False)]
    print("  cost    kết quả   tổng đã chi sau bước đó")
    for cost, expected in steps:
        got = guard.check_budget(u, cost)
        print(f"  {cost:<8}{str(got):<10}{guard.spent_usd(u):.6f}")
        assert got is expected, (cost, got, expected)
    assert guard.spent_usd(u) == 10.0  # chạm đúng $10 vẫn được (so sánh '>' chứ không phải '>=')


def test_key_and_ttl():
    u = uid("ttl")
    assert guard.check_budget(u, 0.5)
    month = datetime.now(timezone.utc).strftime("%Y-%m")
    key = f"budget:{u}:{month}"
    ttl = r.ttl(key)
    now = datetime.now(timezone.utc)
    y, m = (now.year + 1, 1) if now.month == 12 else (now.year, now.month + 1)
    secs_to_next_month = int(datetime(y, m, 1, tzinfo=timezone.utc).timestamp() - time.time())
    print(f"  key  = {key}")
    print(f"  GET  = {r.get(key)}  (micro-USD, = $0.5)")
    print(f"  TTL  = {ttl}s  (còn {secs_to_next_month}s tới đầu tháng sau, +{GRACE_SECONDS}s đệm)")
    assert r.exists(key) == 1
    assert key == guard.key(u)
    # dung sai 2s vì TTL và đồng hồ được đọc ở hai thời điểm khác nhau
    assert secs_to_next_month - 2 < ttl <= secs_to_next_month + GRACE_SECONDS + 2


def test_isolated_users_and_months():
    a, b = uid("a"), uid("b")
    assert guard.check_budget(a, 10.0) and not guard.check_budget(a, 0.01)
    assert guard.check_budget(b, 5.0)  # user khác không bị ảnh hưởng

    # Đồng hồ giả: nhảy sang tháng sau => key mới => budget được reset
    future = time.time() + 10 * 24 * 3600  # +10 ngày: từ 25/11 sang tháng 12
    g_next = RedisBudgetGuard(r, clock=lambda: future)
    print(f"  tháng này key = {guard.key(a)}")
    print(f"  tháng sau key = {g_next.key(a)}")
    assert g_next.key(a) != guard.key(a)
    assert g_next.check_budget(a, 10.0)


def test_reconcile():
    u = uid("rec")
    assert guard.check_budget(u, 2.0)          # giữ chỗ ước tính $2
    assert guard.reconcile(u, 2.0, 0.75) == 0.75  # thực tế chỉ $0.75 -> trả lại $1.25
    assert guard.reconcile(u, 0.75, 0.0) == 0.0   # LLM lỗi -> hoàn hết
    assert guard.reconcile(u, 5.0, 0.0) == 0.0    # không bao giờ xuống dưới 0
    assert guard.check_budget(u, 10.0)


def test_invalid_input():
    u = uid("bad")
    for bad in (-1.0, float("nan"), float("inf")):
        try:
            guard.check_budget(u, bad)
        except ValueError:
            continue
        raise AssertionError(f"cost={bad} phải bị từ chối")
    assert guard.spent_usd(u) == 0.0


def test_concurrency_atomic_vs_naive():
    n_threads, cost = 50, 0.5  # 50 x $0.5 = $25 yêu cầu, budget $10 => đúng 20 request được qua
    u = uid("conc-atomic")
    ok = hammer(guard.check_budget, u, n_threads, cost)
    print(f"  [Lua atomic] {n_threads} thread x ${cost}: True = {ok}, đã chi = ${guard.spent_usd(u):.2f}")
    assert ok == 20 and guard.spent_usd(u) == 10.0

    print("  [Naive GET->INCRBYFLOAT] cùng bài test, 5 lần chạy:")
    worst = 0.0
    for i in range(1, 6):
        un = uid("conc-naive")
        okn = hammer(naive_check_budget, un, n_threads, cost)
        spent = float(r.get(guard.key(un)))
        worst = max(worst, spent)
        print(f"    lần {i}: True = {okn:>2}, đã chi = ${spent:.2f}  {'<-- VƯỢT BUDGET' if spent > 10 else ''}")
    print(f"  => naive chi tối đa ${worst:.2f} trên budget $10.00")
    return worst


if __name__ == "__main__":
    print(f"Redis: {REDIS_URL}  ping={r.ping()}  version={r.info('server')['redis_version']}")
    tests = [
        ("Chạy tuần tự cho tới khi vượt budget", test_sequential_until_exceeded),
        ("Key theo tháng + TTL", test_key_and_ttl),
        ("Tách theo user / reset khi sang tháng", test_isolated_users_and_months),
        ("Reconcile với chi phí thật", test_reconcile),
        ("Từ chối cost không hợp lệ", test_invalid_input),
        ("Đồng thời 50 thread x $0.5 (atomic vs naive)", test_concurrency_atomic_vs_naive),
    ]
    failed = 0
    for name, fn in tests:
        print(f"\n== {name}")
        try:
            fn()
            print("  PASS")
        except AssertionError as e:
            failed += 1
            print(f"  FAIL {e!r}")
    print(f"\n{len(tests) - failed}/{len(tests)} test PASS")
    sys.exit(1 if failed else 0)
