from fastapi import FastAPI, Request
from fastapi.exceptions import RequestValidationError
from fastapi.middleware.cors import CORSMiddleware
from fastapi.staticfiles import StaticFiles
from fastapi.encoders import jsonable_encoder
from starlette.responses import JSONResponse
from app.api.router import api_router
from app.core.config import get_settings
from app.core.exceptions import AppException
from app.core.middleware import TraceIdMiddleware
from app.core.responses import fail

settings = get_settings()


def create_app() -> FastAPI:
    app = FastAPI(title=settings.app_name, debug=settings.debug)
    app.add_middleware(TraceIdMiddleware)
    app.add_middleware(
        CORSMiddleware,
        allow_origins=settings.cors_origins,
        allow_credentials=True,
        allow_methods=["*"],
        allow_headers=["*"],
    )
    app.include_router(api_router)
    app.mount("/static", StaticFiles(directory=str(settings.storage_path)), name="static")

    @app.get("/health")
    def health():
        return {"status": "ok", "app": settings.app_name}

    @app.exception_handler(AppException)
    async def app_exception_handler(request: Request, exc: AppException):
        trace_id = getattr(request.state, "trace_id", None)
        return JSONResponse(status_code=exc.status_code, content=fail(exc.code, exc.message, trace_id=trace_id))

    @app.exception_handler(RequestValidationError)
    async def validation_exception_handler(request: Request, exc: RequestValidationError):
        trace_id = getattr(request.state, "trace_id", "")
        return JSONResponse(
            status_code=422,
            content=jsonable_encoder(
                fail(
                    42200,
                    "参数校验失败",
                    trace_id=trace_id,
                    data=exc.errors(),
                )
            ),
        )
    @app.exception_handler(Exception)
    async def unhandled_exception_handler(request: Request, exc: Exception):
        trace_id = getattr(request.state, "trace_id", None)
        message = str(exc) if settings.debug else "服务器内部错误"
        return JSONResponse(status_code=500, content=fail(50000, message, trace_id=trace_id))

    return app


app = create_app()
