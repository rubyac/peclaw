import logging
from uuid import uuid4

from fastapi import FastAPI, Request
from fastapi.exceptions import RequestValidationError
from fastapi.responses import JSONResponse
from starlette.exceptions import HTTPException

from app.api.agents import router as agent_router
from app.api.auth import router as auth_router
from app.api.catalog import router as catalog_router
from app.api.evaluation import router as evaluation_router
from app.api.health import router as health_router
from app.api.knowledge import router as knowledge_router
from app.api.organizations import router as organization_router
from app.api.projects import router as project_router
from app.api.reports import router as report_router

logger = logging.getLogger("peclaw")


def create_app() -> FastAPI:
    app = FastAPI(title="PEClaw API", version="0.1.0")

    @app.middleware("http")
    async def request_id(request: Request, call_next):
        request.state.request_id = str(uuid4())
        response = await call_next(request)
        response.headers["X-Request-ID"] = request.state.request_id
        if not request.url.path.startswith("/api/v1/health"):
            response.headers["Cache-Control"] = "no-store"
        response.headers["X-Content-Type-Options"] = "nosniff"
        return response

    def error(request: Request, status: int, code: str, message: str) -> JSONResponse:
        trace = getattr(request.state, "request_id", str(uuid4()))
        return JSONResponse(
            status_code=status,
            content={"error": {"code": code, "message": message, "request_id": trace}},
            headers={"X-Request-ID": trace},
        )

    @app.exception_handler(HTTPException)
    async def http_error(request: Request, exc: HTTPException):
        detail = exc.detail if isinstance(exc.detail, dict) else {}
        messages = {
            401: "登录已失效或凭据错误",
            403: "没有执行此操作的权限",
            404: "资源不存在",
            409: "操作与当前资源状态冲突",
            429: "登录尝试过于频繁，请稍后再试",
        }
        return error(
            request,
            exc.status_code,
            detail.get("code", f"HTTP_{exc.status_code}"),
            detail.get("message", messages.get(exc.status_code, "请求的资源不可用")),
        )

    @app.exception_handler(RequestValidationError)
    async def validation_error(request: Request, exc: RequestValidationError):
        return error(request, 422, "VALIDATION_ERROR", "请求参数格式不正确")

    @app.exception_handler(Exception)
    async def internal_error(request: Request, exc: Exception):
        logger.error(
            "request_failed request_id=%s type=%s",
            getattr(request.state, "request_id", "unknown"),
            type(exc).__name__,
        )
        return error(request, 500, "INTERNAL_ERROR", "服务暂时不可用")

    app.include_router(health_router)
    app.include_router(auth_router)
    app.include_router(organization_router)
    app.include_router(project_router)
    app.include_router(catalog_router)
    app.include_router(knowledge_router)
    app.include_router(agent_router)
    app.include_router(report_router)
    app.include_router(evaluation_router)
    return app


app = create_app()
