"""
Kết nối Redis dùng chung cho rate limiter và cost guard.

  • Đọc REDIS_URL từ config
  • App vẫn KHỞI ĐỘNG ĐƯỢC khi Redis chưa sẵn sàng
  • redis_healthy() dùng cho GET /ready
"""
import redis

from app.config import settings

# from_url chỉ tạo client + connection pool, CHƯA mở kết nối (không ping lúc import).
# Kết nối thật chỉ xảy ra ở lệnh Redis đầu tiên.
# Timeout ngắn để /ready và request lỗi trả lời nhanh khi Redis chết.
r = redis.from_url(
    settings.redis_url,
    decode_responses=True,
    socket_connect_timeout=1,
    socket_timeout=2,
)


def redis_healthy() -> bool:
    """PING Redis; bất kỳ lỗi Redis nào (mất kết nối, timeout...) → False."""
    try:
        return bool(r.ping())
    except redis.RedisError:
        return False


def close_redis() -> None:
    """Đóng connection pool khi app tắt (gọi trong lifespan)."""
    r.close()
