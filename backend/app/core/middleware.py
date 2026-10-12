from uuid import uuid4
import logging
from fastapi import Request
from starlette.middleware.base import BaseHTTPMiddleware
from starlette.responses import JSONResponse
from app.core.config import get_settings

logger = logging.getLogger(__name__)


class TraceIdMiddleware(BaseHTTPMiddleware):
    async def dispatch(self, request: Request, call_next):
        trace_id = request.headers.get("X-Trace-Id") or f"req-{uuid4().hex[:16]}"
        request.state.trace_id = trace_id
        try:
            response = await call_next(request)
        except Exception:
            logger.exception("未处理异常 trace_id=%s", trace_id)
            response = JSONResponse(
                status_code=500,
                content={"code": 50000, "message": "服务器内部错误", "data": None, "trace_id": trace_id},
            )
            origin = request.headers.get("origin")
            if origin and origin in get_settings().cors_origins:
                response.headers["Access-Control-Allow-Origin"] = origin
                response.headers["Access-Control-Allow-Credentials"] = "true"
        response.headers["X-Trace-Id"] = trace_id
        return response
