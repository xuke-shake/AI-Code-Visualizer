import logging
from fastapi import FastAPI, HTTPException, Request
from fastapi.exceptions import RequestValidationError
from fastapi.middleware.cors import CORSMiddleware
from fastapi.encoders import jsonable_encoder
from starlette.responses import JSONResponse

from app.api.router import api_router
from app.core.config import get_settings
from app.core.exceptions import AppException
from app.core.middleware import TraceIdMiddleware
from app.core.responses import fail

settings = get_settings()
logger = logging.getLogger(__name__)


def _validation_message(exc: RequestValidationError) -> str:
    errors = exc.errors()
    if not errors:
        return "请求参数格式不正确"
    first = errors[0]
    field = first.get("loc", ["请求"])[-1]
    error_type = str(first.get("type", ""))
    if field == "name":
        if error_type in {"string_too_short", "value_error"}:
            return "项目名称不能为空"
        if error_type == "string_too_long":
            return "项目名称不能超过128个字符"
        return "项目名称格式不正确"
    if field == "repo_url":
        return "请输入有效的 GitHub HTTPS 仓库地址"
    if field == "upload_id":
        return "ZIP项目必须提供有效的上传文件"
    if field == "source_type":
        return "接入方式必须是 Git 或 ZIP"
    if error_type == "value_error" and "ZIP项目" in str(first.get("msg", "")):
        return str(first.get("msg"))
    if error_type == "value_error" and "Git项目" in str(first.get("msg", "")):
        return str(first.get("msg"))
    if field == "nickname":
        return "昵称不能为空"
    if field == "password":
        return "密码长度必须在8到128位之间"
    if field == "email":
        return "请输入有效的邮箱"
    if error_type == "extra_forbidden":
        return "请求包含不支持的字段"
    return "请求参数格式不正确"


def _http_error_code(status_code: int) -> int:
    return {
        400: 40000,
        401: 40100,
        403: 40300,
        404: 40400,
        409: 40900,
        422: 42200,
    }.get(status_code, 50000)

def create_app() -> FastAPI:
    app = FastAPI(title=settings.app_name, debug=settings.debug)
    app.add_middleware(
        CORSMiddleware,
        allow_origins=settings.cors_origins,
        allow_credentials=True,
        allow_methods=["*"],
        allow_headers=["*"],
    )
    app.add_middleware(TraceIdMiddleware)

    app.include_router(api_router)

    @app.get("/health")
    def health():
        return {"status": "ok", "app": settings.app_name}

    @app.exception_handler(AppException)
    async def app_exception_handler(request: Request, exc: AppException):
        trace_id = getattr(request.state, "trace_id", None)
        return JSONResponse(status_code=exc.status_code, content=fail(exc.code, exc.message, trace_id=trace_id))

    @app.exception_handler(HTTPException)
    async def http_exception_handler(request: Request, exc: HTTPException):
        trace_id = getattr(request.state, "trace_id", None)
        message = str(exc.detail) if exc.status_code < 500 else "服务器内部错误"
        if any(marker in message for marker in ("\\", "/", "stderr", "Traceback", "parse_full")):
            message = "请求处理失败"
        return JSONResponse(
            status_code=exc.status_code,
            content=fail(_http_error_code(exc.status_code), message, trace_id=trace_id),
        )

    @app.exception_handler(RequestValidationError)
    async def validation_exception_handler(request: Request, exc: RequestValidationError):
        trace_id = getattr(request.state, "trace_id", "")
        return JSONResponse(
            status_code=422,
            content=jsonable_encoder(
                fail(
                    42200,
                    _validation_message(exc),
                    trace_id=trace_id,
                )
            ),
        )

    @app.exception_handler(Exception)
    async def unhandled_exception_handler(request: Request, exc: Exception):
        trace_id = getattr(request.state, "trace_id", None)
        logger.exception("未处理异常 trace_id=%s", trace_id, exc_info=exc)
        return JSONResponse(status_code=500, content=fail(50000, "服务器内部错误", trace_id=trace_id))

    return app

app = create_app()
