"""Dependências compartilhadas pelas rotas (injetáveis nos testes)."""

from __future__ import annotations

from collections.abc import AsyncIterator

from fastapi import Depends, HTTPException, Request, status

from .config import Settings, get_settings
from .glpi import GLPIClient
from .store import CorrelationStore


def get_config() -> Settings:
    return get_settings()


def get_store(request: Request) -> CorrelationStore:
    return request.app.state.store


async def get_glpi(
    request: Request, settings: Settings = Depends(get_config)
) -> AsyncIterator[GLPIClient]:
    """Entrega um cliente GLPI com sessão ativa, encerrada ao fim da requisição."""
    if not settings.glpi_configured:
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail="GLPI não configurado: defina BRIDGE_GLPI_APP_TOKEN e BRIDGE_GLPI_USER_TOKEN",
        )
    client = GLPIClient(
        base_url=settings.glpi_api_url,
        app_token=settings.glpi_app_token,
        user_token=settings.glpi_user_token,
        timeout=settings.glpi_timeout_seconds,
        client=getattr(request.app.state, "http_client", None),
    )
    async with client.session():
        yield client
