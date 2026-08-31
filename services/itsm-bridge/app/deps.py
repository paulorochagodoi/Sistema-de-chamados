"""Dependências compartilhadas pelas rotas (injetáveis nos testes)."""

from __future__ import annotations

from collections.abc import AsyncIterator

import httpx
from fastapi import Depends, HTTPException, Request, status

from .auth import AuthError, decode_token
from .config import Settings, get_settings
from .glpi import GLPIClient
from .models import PortalUser
from .portal import StatusCache
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


def get_http_client(request: Request) -> httpx.AsyncClient:
    return request.app.state.http_client


def get_probe_client(request: Request) -> httpx.AsyncClient:
    """Cliente das sondas do painel (aceita o TLS interno auto-assinado)."""
    return request.app.state.probe_client


def get_status_cache(request: Request) -> StatusCache:
    return request.app.state.status_cache


def get_current_user(request: Request, settings: Settings = Depends(get_config)) -> PortalUser:
    """Identifica quem está usando o painel; 401 se ninguém."""
    header = request.headers.get("Authorization", "")
    scheme, _, token = header.partition(" ")
    if scheme.lower() == "bearer" and token:
        try:
            return decode_token(token.strip(), settings.portal_signing_key)
        except AuthError as exc:
            raise HTTPException(
                status_code=status.HTTP_401_UNAUTHORIZED,
                detail=str(exc),
                headers={"WWW-Authenticate": "Bearer"},
            ) from exc

    if settings.portal_trust_forwarded_auth:
        forwarded = request.headers.get(settings.portal_forwarded_user_header, "").strip()
        if forwarded:
            return PortalUser(
                username=forwarded,
                full_name=request.headers.get(
                    settings.portal_forwarded_name_header, ""
                ).strip()
                or forwarded,
                source="sso",
            )

    raise HTTPException(
        status_code=status.HTTP_401_UNAUTHORIZED,
        detail="autenticação necessária",
        headers={"WWW-Authenticate": "Bearer"},
    )
