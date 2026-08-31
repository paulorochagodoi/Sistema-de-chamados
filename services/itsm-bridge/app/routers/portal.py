"""API do painel unificado: login, catálogo de serviços, status e chamados.

É o que faz a stack ter *uma* porta de entrada. Todo endpoint aqui (menos o
login) exige um usuário autenticado — o painel fica exposto na internet junto
com os demais serviços e lê dados de chamados.
"""

from __future__ import annotations

import logging
from datetime import datetime, timedelta

import httpx
from fastapi import APIRouter, Depends, HTTPException, Query, status

from .. import portal
from .. import tickets as ticket_mapper
from ..auth import AuthError, authenticate_with_glpi, issue_token
from ..config import Settings
from ..deps import (
    get_config,
    get_current_user,
    get_glpi,
    get_http_client,
    get_probe_client,
    get_status_cache,
)
from ..glpi import GLPIClient, GLPIError
from ..models import (
    LoginRequest,
    LoginResponse,
    NewFollowup,
    NewTicket,
    PortalService,
    PortalSummary,
    PortalTicket,
    PortalTicketDetail,
    PortalUser,
    ServiceHealth,
    TicketSolution,
)
from ..portal import StatusCache

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/api/portal", tags=["painel"])

# Quantos chamados o resumo lê para agregar os números do painel inicial.
SUMMARY_SAMPLE = 200
RECENT_IN_SUMMARY = 8
# formato de data/hora do GLPI, usado na comparação de prazos
GLPI_DATETIME = "%Y-%m-%d %H:%M:%S"


def _glpi_error(exc: GLPIError) -> HTTPException:
    logger.warning("operação no GLPI falhou: %s", exc)
    return HTTPException(status_code=status.HTTP_502_BAD_GATEWAY, detail=str(exc))


# ---------------------------------------------------------------------------
# Sessão
# ---------------------------------------------------------------------------
@router.post(
    "/auth/login",
    response_model=LoginResponse,
    summary="Autentica no painel com as credenciais do GLPI",
)
async def login(
    payload: LoginRequest,
    settings: Settings = Depends(get_config),
    client: httpx.AsyncClient = Depends(get_http_client),
) -> LoginResponse:
    if not settings.glpi_app_token:
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail="GLPI não configurado: defina BRIDGE_GLPI_APP_TOKEN",
        )
    try:
        user = await authenticate_with_glpi(
            username=payload.username,
            password=payload.password,
            api_url=settings.glpi_api_url,
            app_token=settings.glpi_app_token,
            client=client,
            timeout=settings.glpi_timeout_seconds,
        )
    except AuthError as exc:
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail=str(exc)) from exc

    token, expires_in = issue_token(
        user, settings.portal_signing_key, settings.portal_session_minutes
    )
    return LoginResponse(access_token=token, expires_in=expires_in, user=user)


@router.get("/auth/me", response_model=PortalUser, summary="Quem está autenticado")
def me(user: PortalUser = Depends(get_current_user)) -> PortalUser:
    return user


# ---------------------------------------------------------------------------
# Serviços da stack
# ---------------------------------------------------------------------------
@router.get(
    "/services",
    response_model=list[PortalService],
    summary="Catálogo de serviços acessíveis pelo painel",
)
def services(
    settings: Settings = Depends(get_config),
    _: PortalUser = Depends(get_current_user),
) -> list[PortalService]:
    return portal.catalog(settings.portal_domain, settings.portal_enabled_profiles)


@router.get(
    "/services/status",
    response_model=list[ServiceHealth],
    summary="Disponibilidade de cada serviço, checada por dentro da rede",
)
async def services_status(
    settings: Settings = Depends(get_config),
    cache: StatusCache = Depends(get_status_cache),
    client: httpx.AsyncClient = Depends(get_probe_client),
    _: PortalUser = Depends(get_current_user),
) -> list[ServiceHealth]:
    profiles = settings.portal_enabled_profiles
    definitions = [item for item in portal.CATALOG if item.profile in profiles]
    return await cache.get(definitions, client, settings.portal_probe_timeout_seconds)


# ---------------------------------------------------------------------------
# Chamados
# ---------------------------------------------------------------------------
@router.get("/tickets", response_model=list[PortalTicket], summary="Lista chamados do GLPI")
async def list_tickets(
    status_filter: str = Query(
        "notold",
        alias="status",
        description="id do status (1..6), notold (abertos), old (encerrados) ou all",
    ),
    search: str = Query("", description="Filtra pelo título"),
    entity_id: int | None = Query(None, description="Restringe a uma entidade do GLPI"),
    limit: int = Query(50, ge=1, le=200),
    offset: int = Query(0, ge=0),
    glpi: GLPIClient = Depends(get_glpi),
    _: PortalUser = Depends(get_current_user),
) -> list[PortalTicket]:
    try:
        rows = await glpi.list_tickets(
            status=status_filter, search=search, entity_id=entity_id, limit=limit, offset=offset
        )
    except GLPIError as exc:
        raise _glpi_error(exc) from exc
    return [ticket_mapper.from_search_row(row) for row in rows]


@router.get(
    "/summary",
    response_model=PortalSummary,
    summary="Números do painel inicial (status, prioridade, técnico, prazos)",
)
async def summary(
    settings: Settings = Depends(get_config),
    glpi: GLPIClient = Depends(get_glpi),
    _: PortalUser = Depends(get_current_user),
) -> PortalSummary:
    try:
        rows = await glpi.list_tickets(status="notold", limit=SUMMARY_SAMPLE)
    except GLPIError as exc:
        raise _glpi_error(exc) from exc

    items = [ticket_mapper.from_search_row(row) for row in rows]
    reference = datetime.now()
    now = reference.strftime(GLPI_DATETIME)
    soon = (reference + timedelta(minutes=settings.sla_at_risk_threshold_minutes)).strftime(
        GLPI_DATETIME
    )
    aggregate = ticket_mapper.summarize(items, now=now, soon=soon)
    return PortalSummary(**aggregate, recent=items[:RECENT_IN_SUMMARY])


@router.post(
    "/tickets",
    response_model=PortalTicket,
    status_code=status.HTTP_201_CREATED,
    summary="Abre um chamado em nome de quem está no painel",
)
async def create_ticket(
    payload: NewTicket,
    settings: Settings = Depends(get_config),
    glpi: GLPIClient = Depends(get_glpi),
    user: PortalUser = Depends(get_current_user),
) -> PortalTicket:
    entity_id = payload.entity_id if payload.entity_id is not None else settings.default_entity_id
    try:
        ticket_id = await glpi.create_ticket(
            name=payload.title,
            content=payload.content,
            entity_id=entity_id,
            urgency=payload.urgency,
            ticket_type=payload.type,
            requester_id=user.id or None,
        )
    except GLPIError as exc:
        raise _glpi_error(exc) from exc

    logger.info("chamado %s aberto pelo painel por %s", ticket_id, user.username)
    return PortalTicket(
        id=ticket_id,
        title=payload.title,
        status=1,
        status_label=ticket_mapper.STATUS_LABELS[1],
        priority=payload.urgency,
        priority_label=ticket_mapper.PRIORITY_LABELS.get(payload.urgency, ""),
        type=payload.type,
        type_label=ticket_mapper.TYPE_LABELS.get(payload.type, ""),
        requester=user.full_name or user.username,
    )


@router.get(
    "/tickets/{ticket_id}",
    response_model=PortalTicketDetail,
    summary="Detalhe do chamado com os acompanhamentos",
)
async def get_ticket(
    ticket_id: int,
    glpi: GLPIClient = Depends(get_glpi),
    _: PortalUser = Depends(get_current_user),
) -> PortalTicketDetail:
    try:
        item = await glpi.get_ticket(ticket_id)
        followups = await glpi.ticket_followups(ticket_id)
    except GLPIError as exc:
        raise _glpi_error(exc) from exc
    return ticket_mapper.from_item(item, followups)


@router.post(
    "/tickets/{ticket_id}/followups",
    response_model=PortalTicketDetail,
    summary="Registra um acompanhamento no chamado",
)
async def add_followup(
    ticket_id: int,
    payload: NewFollowup,
    glpi: GLPIClient = Depends(get_glpi),
    user: PortalUser = Depends(get_current_user),
) -> PortalTicketDetail:
    # O bridge fala com o GLPI pela conta de serviço: sem a assinatura, o
    # acompanhamento apareceria como se fosse do robô.
    content = f"{payload.content}\n\n-- {user.full_name or user.username} (painel)"
    try:
        await glpi.add_followup(ticket_id, content, is_private=payload.is_private)
        item = await glpi.get_ticket(ticket_id)
        followups = await glpi.ticket_followups(ticket_id)
    except GLPIError as exc:
        raise _glpi_error(exc) from exc
    return ticket_mapper.from_item(item, followups)


@router.post(
    "/tickets/{ticket_id}/solution",
    response_model=PortalTicketDetail,
    summary="Registra a solução e move o chamado para solucionado",
)
async def solve_ticket(
    ticket_id: int,
    payload: TicketSolution,
    glpi: GLPIClient = Depends(get_glpi),
    user: PortalUser = Depends(get_current_user),
) -> PortalTicketDetail:
    content = f"{payload.content}\n\n-- {user.full_name or user.username} (painel)"
    try:
        await glpi.solve_ticket(ticket_id, content)
        item = await glpi.get_ticket(ticket_id)
        followups = await glpi.ticket_followups(ticket_id)
    except GLPIError as exc:
        raise _glpi_error(exc) from exc
    return ticket_mapper.from_item(item, followups)
