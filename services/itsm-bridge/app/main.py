"""itsm-bridge — cola entre o núcleo ITSM (GLPI) e os demais serviços.

Responsabilidades:

* receber alertas do RMM e abrir/atualizar chamados (monitoramento proativo);
* espelhar conversas do Chatwoot como chamados (omnichannel);
* calcular prazos de SLA respeitando a janela de atendimento do contrato;
* calcular faturas a partir dos apontamentos de horas;
* servir a API do painel unificado (catálogo de serviços, status e chamados);
* publicar métricas de negócio para o Prometheus.
"""

from __future__ import annotations

import asyncio
import contextlib
import logging
from collections.abc import AsyncIterator
from contextlib import asynccontextmanager
from datetime import datetime

import httpx
from fastapi import FastAPI
from fastapi.responses import PlainTextResponse
from prometheus_client import CONTENT_TYPE_LATEST, generate_latest

from . import metrics
from .config import get_settings
from .glpi import SEARCH_OPTION_TICKET_TIME_TO_RESOLVE, GLPIClient
from .models import BusinessHours
from .portal import StatusCache
from .routers import billing, health, portal, sla, webhooks
from .sla import is_at_risk
from .store import build_store

logger = logging.getLogger(__name__)


async def _refresh_sla_gauge(app: FastAPI) -> None:
    """Atualiza a métrica de chamados com SLA em risco consultando o GLPI."""
    settings = get_settings()
    client = GLPIClient(
        base_url=settings.glpi_api_url,
        app_token=settings.glpi_app_token,
        user_token=settings.glpi_user_token,
        timeout=settings.glpi_timeout_seconds,
        client=app.state.http_client,
    )
    hours = BusinessHours(around_the_clock=True)  # o prazo do GLPI já é tempo corrido
    async with client.session():
        tickets = await client.open_tickets_with_deadline()

    now = datetime.now()
    at_risk = 0
    for ticket in tickets:
        raw_due = ticket.get(str(SEARCH_OPTION_TICKET_TIME_TO_RESOLVE))
        if not raw_due:
            continue
        try:
            due = datetime.fromisoformat(str(raw_due))
        except ValueError:
            continue
        if is_at_risk(due, now, settings.sla_at_risk_threshold_minutes, hours):
            at_risk += 1
    metrics.sla_at_risk.set(at_risk)


async def _sla_poller(app: FastAPI) -> None:
    settings = get_settings()
    while True:
        try:
            await _refresh_sla_gauge(app)
        except asyncio.CancelledError:
            raise
        except Exception as exc:
            metrics.sla_poll_errors.inc()
            logger.warning("coleta de SLA em risco falhou: %s", exc)
        await asyncio.sleep(settings.sla_poll_interval_seconds)


@asynccontextmanager
async def lifespan(app: FastAPI) -> AsyncIterator[None]:
    settings = get_settings()
    logging.basicConfig(
        level=settings.log_level.upper(),
        format="%(asctime)s %(levelname)s %(name)s %(message)s",
    )
    app.state.http_client = httpx.AsyncClient(timeout=settings.glpi_timeout_seconds)
    # Sondas do painel: os serviços internos falam HTTP puro ou TLS
    # auto-assinado (MeshCentral), então a verificação de certificado só
    # produziria falso negativo aqui.
    app.state.probe_client = httpx.AsyncClient(
        timeout=settings.portal_probe_timeout_seconds, verify=False
    )
    app.state.status_cache = StatusCache(settings.portal_status_ttl_seconds)
    app.state.store = build_store(settings.redis_url)

    poller: asyncio.Task | None = None
    if settings.sla_poll_enabled and settings.glpi_configured:
        poller = asyncio.create_task(_sla_poller(app))
    else:
        logger.info("coletor de SLA desabilitado (sem credenciais do GLPI ou desligado)")

    try:
        yield
    finally:
        if poller is not None:
            poller.cancel()
            with contextlib.suppress(asyncio.CancelledError):
                await poller
        await app.state.store.close()
        await app.state.probe_client.aclose()
        await app.state.http_client.aclose()


def create_app() -> FastAPI:
    app = FastAPI(
        title="itsm-bridge",
        version="1.0.0",
        summary="Integrações do sistema ITSM containerizado",
        lifespan=lifespan,
    )
    app.include_router(health.router)
    app.include_router(webhooks.router)
    app.include_router(billing.router)
    app.include_router(sla.router)
    app.include_router(portal.router)

    @app.get("/metrics", include_in_schema=False)
    def prometheus_metrics() -> PlainTextResponse:
        return PlainTextResponse(generate_latest(), media_type=CONTENT_TYPE_LATEST)

    return app


app = create_app()
