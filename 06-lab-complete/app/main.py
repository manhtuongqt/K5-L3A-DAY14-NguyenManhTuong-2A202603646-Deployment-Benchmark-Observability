"""
Production AI Agent — Part 6 Final Project

Chạy:  uvicorn app.main:app --workers 2
Thứ tự xử lý /ask: auth → rate limit → budget → LLM → ghi chi phí.
"""
import json
import logging
import time
from contextlib import asynccontextmanager
from datetime import datetime, timezone

from fastapi import Depends, FastAPI, HTTPException, Request
from fastapi.responses import JSONResponse
from pydantic import BaseModel, Field
from redis.exceptions import RedisError

from app.auth import verify_api_key
from app.config import settings
from app.cost_guard import check_budget, estimate_tokens, record_cost
from app.rate_limiter import check_rate_limit
from app.redis_client import close_redis, redis_healthy
from utils.mock_llm import ask as llm_ask

APP_VERSION = "1.0.0"
START_TIME = time.time()


# ─────────────────────────────────────────────────────────
# Structured logging: mỗi dòng log là đúng 1 JSON object.
# Cấu hình root logger NGAY ĐÂY, trước khi có bất kỳ dòng log nào,
# vì logging.basicConfig() sẽ không làm gì nếu root logger đã có handler.
# ─────────────────────────────────────────────────────────
class JsonFormatter(logging.Formatter):
    def format(self, record: logging.LogRecord) -> str:
        data = {
            "ts": datetime.fromtimestamp(record.created, timezone.utc).isoformat(),
            "lvl": record.levelname,
            "event": record.getMessage(),
        }
        data.update(getattr(record, "fields", {}))  # các field thêm vào qua log_event()
        if record.exc_info:
            data["exception"] = self.formatException(record.exc_info)  # chỉ ghi vào log, không gửi cho client
        return json.dumps(data, ensure_ascii=False)  # json.dumps cả record → luôn là JSON hợp lệ


_handler = logging.StreamHandler()
_handler.setFormatter(JsonFormatter())
_root = logging.getLogger()
_root.handlers = [_handler]
_root.setLevel(settings.log_level)

logger = logging.getLogger("agent")


def log_event(event: str, level: int = logging.INFO, **fields) -> None:
    """Ghi 1 dòng log JSON: log_event("request", path="/ask", status=200)."""
    logger.log(level, event, extra={"fields": fields})


# ─────────────────────────────────────────────────────────
# App + lifespan (startup / shutdown)
# ─────────────────────────────────────────────────────────
@asynccontextmanager
async def lifespan(app: FastAPI):
    log_event("startup", environment=settings.environment, version=APP_VERSION)
    if not settings.agent_api_key:
        log_event("AGENT_API_KEY is empty: every request will be rejected with 401",
                  level=logging.WARNING, environment=settings.environment)
    yield
    # Chạy sau khi uvicorn nhận SIGTERM và đã xử lý xong các request đang chạy.
    log_event("shutdown")
    close_redis()


# Ở production tắt /docs, /redoc, /openapi.json để không công khai toàn bộ API schema.
_docs_enabled = settings.environment != "production"
app = FastAPI(
    title="Production AI Agent",
    version=APP_VERSION,
    lifespan=lifespan,
    docs_url="/docs" if _docs_enabled else None,
    redoc_url="/redoc" if _docs_enabled else None,
    openapi_url="/openapi.json" if _docs_enabled else None,
)


@app.middleware("http")
async def log_requests(request: Request, call_next):
    """Mỗi request một dòng log: method, path, status, ms. Không bao giờ log header (có API key)."""
    start = time.perf_counter()
    status = 500  # nếu có exception chưa được bắt thì client sẽ nhận 500
    try:
        response = await call_next(request)
        status = response.status_code
        return response
    finally:
        log_event("request", method=request.method, path=request.url.path,
                  status=status, ms=round((time.perf_counter() - start) * 1000, 1))


# ─────────────────────────────────────────────────────────
# Xử lý lỗi: client chỉ thấy thông báo ngắn, chi tiết nằm trong log
# (HTTPException 401/402/429/503 và lỗi validate 422 vẫn dùng handler mặc định của FastAPI)
# ─────────────────────────────────────────────────────────
@app.exception_handler(RedisError)
async def redis_error_handler(request: Request, exc: RedisError):
    log_event("redis_error", level=logging.ERROR, path=request.url.path, error=type(exc).__name__)
    return JSONResponse(status_code=503, content={"detail": "Service temporarily unavailable"})


@app.exception_handler(Exception)
async def unhandled_error_handler(request: Request, exc: Exception):
    logger.error("unhandled_exception", exc_info=exc, extra={"fields": {"path": request.url.path}})
    return JSONResponse(status_code=500, content={"detail": "Internal server error"})


# ─────────────────────────────────────────────────────────
# Endpoints
# ─────────────────────────────────────────────────────────
class AskRequest(BaseModel):
    question: str = Field(..., min_length=1, max_length=2000)
    user_id: str | None = None


@app.get("/health")
async def health():
    """Liveness: process còn sống thì 200. KHÔNG gọi Redis, để Redis chết không làm platform restart app."""
    return {
        "status": "ok",
        "version": APP_VERSION,
        "environment": settings.environment,
        "uptime_seconds": round(time.time() - START_TIME, 1),
    }


# `def` (không phải `async def`): redis client là blocking, FastAPI sẽ chạy hàm trong threadpool
# để không chặn event loop. Các endpoint bên dưới cũng vậy.
@app.get("/ready")
def ready():
    """Readiness: 200 khi Redis dùng được, 503 khi không → platform ngừng gửi traffic vào instance này."""
    if not redis_healthy():
        raise HTTPException(status_code=503, detail="Not ready: Redis unavailable")
    return {"status": "ready"}


@app.post("/ask")
def ask(body: AskRequest, api_key: str = Depends(verify_api_key)):
    check_rate_limit(api_key)  # 429 nếu vượt giới hạn
    check_budget()             # 402 nếu hết budget
    answer = llm_ask(body.question)
    input_tokens = estimate_tokens(body.question)
    output_tokens = estimate_tokens(answer)
    cost = record_cost(input_tokens, output_tokens)
    return {
        "question": body.question,
        "answer": answer,
        "user_id": body.user_id,
        "usage": {"input_tokens": input_tokens, "output_tokens": output_tokens},
        "cost_usd": round(cost, 8),
    }
