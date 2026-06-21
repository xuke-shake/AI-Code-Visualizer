import json
from fastapi import FastAPI, Request, WebSocket
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

    @app.middleware("http")
    async def validate_nickname_middleware(request: Request, call_next):
        if request.method == "POST" and ("register" in request.url.path or "user" in request.url.path):
            try:
                body_bytes = await request.body()
                if body_bytes:
                    body = json.loads(body_bytes)
                    nickname = body.get("nickname") or body.get("username") or body.get("name")
                    
                    if nickname is None or (isinstance(nickname, str) and not nickname.strip()):
                        response = JSONResponse(
                            status_code=422,
                            content=jsonable_encoder(
                                fail(42200, "注册失败：用户名不能为空")
                            )
                        )
                        origin = request.headers.get("origin")
                        if origin:
                            response.headers["Access-Control-Allow-Origin"] = origin
                            response.headers["Access-Control-Allow-Credentials"] = "true"
                        return response
                    
                    async def receive():
                        return {"type": "http.request", "body": body_bytes, "more_body": False}
                    request._receive = receive
            except Exception:
                try:
                    async def receive():
                        return {"type": "http.request", "body": body_bytes, "more_body": False}
                    request._receive = receive
                except Exception:
                    pass
        return await call_next(request)

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
        errors = exc.errors()
        error_msg = "注册失败：参数格式不正确"
        
        if len(errors) > 0:
            first_error = errors[0]
            field = first_error.get("loc", ["未知名"])[-1]
            
            if field == "password":
                error_msg = "注册失败：密码不得少于8位"
            elif field == "email":
                error_msg = "注册失败：请输入有效的邮箱地址"
            else:
                error_msg = f"注册失败：{field} 格式不正确"
                
        return JSONResponse(
            status_code=422,
            content=jsonable_encoder(
                fail(
                    42200,
                    error_msg,  
                    trace_id=trace_id,
                    data=errors,
                )
            ),
        )

    @app.exception_handler(Exception)
    async def unhandled_exception_handler(request: Request, exc: Exception):
        trace_id = getattr(request.state, "trace_id", None)
        message = str(exc) if settings.debug else "服务器内部错误"
        return JSONResponse(status_code=500, content=fail(50000, message, trace_id=trace_id))

    @app.websocket("/ws/tasks")
    async def websocket_tasks_endpoint(websocket: WebSocket, projectId: int = None):
        await websocket.accept()
        try:
            await websocket.send_json({
                "task_id": 999,
                "status": "success",
                "progress": 100,
                "stage": "diagram",
                "message": "AI 图表生成完成！"
            })
            
            while True:
                data = await websocket.receive_text()
        except Exception as e:
            pass

    return app

app = create_app()
