"""Sondas de saúde e prontidão."""

from __future__ import annotations

from fastapi import APIRouter, Depends, Response, status

from ..config import Settings
from ..deps import get_config

router = APIRouter(tags=["infra"])


@router.get("/healthz", summary="Liveness — o processo está de pé")
def healthz() -> dict[str, str]:
    return {"status": "ok"}


@router.get("/readyz", summary="Readiness — o serviço pode receber tráfego")
def readyz(response: Response, settings: Settings = Depends(get_config)) -> dict[str, object]:
    checks = {"glpi_credentials": settings.glpi_configured}
    ready = all(checks.values())
    if not ready:
        response.status_code = status.HTTP_503_SERVICE_UNAVAILABLE
    return {"ready": ready, "checks": checks}
