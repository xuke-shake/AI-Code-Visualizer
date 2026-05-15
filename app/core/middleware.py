from uuid import uuid4
from fastapi import Request
from starlette.middleware.base import BaseHTTPMiddleware


class TraceIdMiddleware(BaseHTTPMiddleware):
    async def dispatch(self, request: Request, call_next):
        trace_id = request.headers.get("X-Trace-Id") or f"req-{uuid4().hex[:16]}"
        request.state.trace_id = trace_id
        response = await call_next(request)
        response.headers["X-Trace-Id"] = trace_id
        return response
