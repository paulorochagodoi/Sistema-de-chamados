"""Cálculo de prazos de SLA por contrato (janela de atendimento e feriados)."""

from __future__ import annotations

from datetime import datetime

from fastapi import APIRouter, HTTPException, status
from pydantic import BaseModel, Field

from .. import sla as sla_engine
from ..models import BusinessHours, SLARequest, SLAResponse

router = APIRouter(prefix="/api/sla", tags=["sla"])


class AtRiskRequest(BaseModel):
    due_at: datetime
    now: datetime | None = None
    threshold_minutes: int = Field(default=60, gt=0)
    business_hours: BusinessHours = Field(default_factory=BusinessHours)


class AtRiskResponse(BaseModel):
    at_risk: bool
    breached: bool
    business_minutes_remaining: int


@router.post(
    "/deadline",
    response_model=SLAResponse,
    summary="Calcula prazos de resposta e resolução a partir da abertura",
)
def deadline(request: SLARequest) -> SLAResponse:
    try:
        return sla_engine.compute(request)
    except ValueError as exc:
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_ENTITY, detail=str(exc)
        ) from exc


@router.post(
    "/at-risk",
    response_model=AtRiskResponse,
    summary="Informa se um prazo está a vencer (gatilho de escalonamento)",
)
def at_risk(request: AtRiskRequest) -> AtRiskResponse:
    now = request.now or datetime.now()
    try:
        remaining = sla_engine.business_minutes_between(now, request.due_at, request.business_hours)
        risk = sla_engine.is_at_risk(
            request.due_at, now, request.threshold_minutes, request.business_hours
        )
    except ValueError as exc:
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_ENTITY, detail=str(exc)
        ) from exc
    return AtRiskResponse(
        at_risk=risk,
        breached=request.due_at <= now,
        business_minutes_remaining=remaining,
    )
