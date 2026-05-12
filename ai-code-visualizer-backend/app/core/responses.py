from typing import Any
from fastapi import Request
from pydantic import BaseModel, ConfigDict


class ApiResponse(BaseModel):
    code: int = 0
    message: str = "success"
    data: Any = None
    trace_id: str | None = None

    model_config = ConfigDict(arbitrary_types_allowed=True)


def success(data: Any = None, message: str = "success", trace_id: str | None = None) -> dict[str, Any]:
    return {"code": 0, "message": message, "data": data, "trace_id": trace_id}


def fail(code: int, message: str, trace_id: str | None = None, data: Any = None) -> dict[str, Any]:
    return {"code": code, "message": message, "data": data, "trace_id": trace_id}


def request_trace_id(request: Request | None) -> str | None:
    if request is None:
        return None
    return getattr(request.state, "trace_id", None)
