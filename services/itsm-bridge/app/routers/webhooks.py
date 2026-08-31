"""Webhooks de entrada: RMM (monitoramento) e Chatwoot (omnichannel)."""

from __future__ import annotations

import json
import logging

from fastapi import APIRouter, Depends, HTTPException, Request, status
from pydantic import ValidationError

from .. import metrics
from ..config import Settings
from ..deps import get_config, get_glpi, get_store
from ..glpi import GLPIClient, GLPIError
from ..handlers import handle_chatwoot_event, handle_rmm_alert
from ..models import ChatwootEvent, RMMAlert, WebhookResult
from ..security import SIGNATURE_HEADER, InvalidSignature, verify
from ..store import CorrelationStore

logger = logging.getLogger(__name__)
router = APIRouter(prefix="/webhooks", tags=["webhooks"])


async def _payload(request: Request, secret: str, source: str) -> dict:
    body = await request.body()
    try:
        verify(body, request.headers.get(SIGNATURE_HEADER), secret)
    except InvalidSignature as exc:
        metrics.webhook_rejected.labels(source=source, reason="signature").inc()
        logger.warning("webhook %s rejeitado: %s", source, exc)
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail=str(exc)) from exc

    try:
        return json.loads(body or b"{}")
    except json.JSONDecodeError as exc:
        metrics.webhook_rejected.labels(source=source, reason="json").inc()
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST, detail="corpo não é um JSON válido"
        ) from exc


@router.post(
    "/rmm/alert",
    response_model=WebhookResult,
    summary="Recebe alertas do RMM e abre/atualiza chamados no GLPI",
)
async def rmm_alert(
    request: Request,
    settings: Settings = Depends(get_config),
    glpi: GLPIClient = Depends(get_glpi),
    store: CorrelationStore = Depends(get_store),
) -> WebhookResult:
    with metrics.webhook_duration.labels(source="rmm").time():
        data = await _payload(request, settings.rmm_webhook_secret, "rmm")
        try:
            alert = RMMAlert.model_validate(data)
        except ValidationError as exc:
            metrics.webhook_rejected.labels(source="rmm", reason="schema").inc()
            raise HTTPException(
                status_code=status.HTTP_422_UNPROCESSABLE_ENTITY, detail=exc.errors()
            ) from exc

        try:
            return await handle_rmm_alert(alert, glpi, store, settings)
        except GLPIError as exc:
            logger.error("falha ao tratar alerta %s: %s", alert.alert_id, exc)
            raise HTTPException(
                status_code=status.HTTP_502_BAD_GATEWAY, detail=f"GLPI: {exc}"
            ) from exc


@router.post(
    "/chatwoot",
    response_model=WebhookResult,
    summary="Espelha conversas do Chatwoot como chamados",
)
async def chatwoot(
    request: Request,
    settings: Settings = Depends(get_config),
    glpi: GLPIClient = Depends(get_glpi),
    store: CorrelationStore = Depends(get_store),
) -> WebhookResult:
    with metrics.webhook_duration.labels(source="chatwoot").time():
        data = await _payload(request, settings.chatwoot_webhook_secret, "chatwoot")
        try:
            event = ChatwootEvent.model_validate(data)
        except ValidationError as exc:
            metrics.webhook_rejected.labels(source="chatwoot", reason="schema").inc()
            raise HTTPException(
                status_code=status.HTTP_422_UNPROCESSABLE_ENTITY, detail=exc.errors()
            ) from exc

        try:
            return await handle_chatwoot_event(event, glpi, store, settings)
        except GLPIError as exc:
            logger.error("falha ao tratar evento do Chatwoot: %s", exc)
            raise HTTPException(
                status_code=status.HTTP_502_BAD_GATEWAY, detail=f"GLPI: {exc}"
            ) from exc
