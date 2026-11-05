from typing import Literal

from pydantic import BaseModel


class HealthResponse(BaseModel):
    status: Literal["ok", "ready", "not_ready"]
    service: str = "peclaw-api"
    version: str = "0.1.0"
    checks: dict[str, Literal["ok", "error"]] = {}
