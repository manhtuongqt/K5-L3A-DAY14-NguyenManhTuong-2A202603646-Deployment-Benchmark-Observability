"""
API Key authentication (tiêu chí 6).

  • Client gửi header  X-API-Key: <key>
  • Key phải trùng biến môi trường AGENT_API_KEY
  • Thiếu hoặc sai key → HTTP 401
"""
import secrets

from fastapi import HTTPException, Security
from fastapi.security import APIKeyHeader

from app.config import settings

# auto_error=False: thiếu header thì FastAPI KHÔNG tự trả lỗi,
# để hàm bên dưới tự trả 401 (nếu không sẽ ra 403/422).
api_key_header = APIKeyHeader(name="X-API-Key", auto_error=False)


def verify_api_key(api_key: str | None = Security(api_key_header)) -> str:
    """Dependency cho FastAPI — dùng trong /ask: Depends(verify_api_key)."""
    expected = settings.agent_api_key
    # Server chưa cấu hình key (rỗng) → từ chối tất cả, không bao giờ coi key rỗng là hợp lệ.
    # compare_digest so sánh trong thời gian không đổi (chống đoán key qua thời gian phản hồi);
    # .encode() để header có ký tự non-ASCII không làm compare_digest văng lỗi.
    if not expected or not api_key or not secrets.compare_digest(api_key.encode(), expected.encode()):
        raise HTTPException(
            status_code=401,
            detail="Invalid or missing API key. Send header: X-API-Key",
            headers={"WWW-Authenticate": "ApiKey"},
        )
    return api_key
