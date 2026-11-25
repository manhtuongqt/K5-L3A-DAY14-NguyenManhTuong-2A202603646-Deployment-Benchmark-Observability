"""
Rate limiting (tiêu chí 7) — sliding window 60 giây cho mỗi API key.

State nằm trong Redis (sorted set) nên mọi worker dùng chung và còn nguyên
sau khi restart agent.
"""
import hashlib
import math
import time
import uuid

from fastapi import HTTPException

from app.config import settings
from app.redis_client import r

WINDOW_SECONDS = 60


def check_rate_limit(key: str) -> None:
    """Vượt RATE_LIMIT_PER_MINUTE trong 60 giây → HTTP 429 + header Retry-After."""
    # Không đưa API key thật vào tên key Redis: dùng 16 ký tự đầu của hash.
    redis_key = "rate:" + hashlib.sha256(key.encode()).hexdigest()[:16]
    now = time.time()
    member = f"{now}-{uuid.uuid4().hex[:8]}"  # mỗi request một member duy nhất

    # Pipeline (MULTI/EXEC): 4 lệnh chạy liền nhau, không request nào chen vào giữa.
    # Thêm request này TRƯỚC rồi mới đếm, nên 2 worker không thể cùng "lọt" khi chỉ còn 1 slot
    # (kiểu đếm trước, thêm sau thì sẽ bị race).
    pipe = r.pipeline(transaction=True)
    pipe.zremrangebyscore(redis_key, 0, now - WINDOW_SECONDS)  # xoá request cũ hơn 60 giây
    pipe.zadd(redis_key, {member: now})                        # ghi request này
    pipe.zcard(redis_key)                                      # đếm request trong cửa sổ
    pipe.zrange(redis_key, 0, 0, withscores=True)              # request cũ nhất (để tính Retry-After)
    pipe.expire(redis_key, WINDOW_SECONDS)                     # key tự xoá khi im lặng
    _, _, count, oldest, _ = pipe.execute()

    if count > settings.rate_limit_per_minute:
        r.zrem(redis_key, member)  # request bị từ chối không chiếm slot của cửa sổ
        # Slot đầu tiên trống lại khi request cũ nhất trượt ra khỏi cửa sổ.
        retry_after = max(1, math.ceil(oldest[0][1] + WINDOW_SECONDS - now))
        raise HTTPException(
            status_code=429,
            detail=f"Rate limit exceeded: {settings.rate_limit_per_minute} requests/minute",
            headers={"Retry-After": str(retry_after)},
        )
