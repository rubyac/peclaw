from fastapi import APIRouter
from fastapi.responses import JSONResponse

from app.schemas.health import HealthResponse
from app.services.dependencies import dependency_checks

router = APIRouter(prefix="/api/v1/health", tags=["health"])


@router.get("/live", response_model=HealthResponse)
def live() -> HealthResponse:
    return HealthResponse(status="ok")


@router.get("/ready", response_model=HealthResponse, responses={503: {"model": HealthResponse}})
def ready():
    checks = dependency_checks()
    is_ready = all(value == "ok" for value in checks.values())
    payload = HealthResponse(status="ready" if is_ready else "not_ready", checks=checks)
    return JSONResponse(status_code=200 if is_ready else 503, content=payload.model_dump())
