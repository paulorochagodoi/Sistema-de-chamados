"""Catálogo de serviços do painel unificado e sondagem de disponibilidade.

O painel é a única porta de entrada da stack: em vez de decorar uma URL por
serviço (glpi., sso., rmm., chat., n8n., bi., grafana., minio.), o operador
abre o portal e alcança tudo pelo mesmo menu.

Este módulo descreve *quais* serviços existem, onde ficam (URL pública, derivada
do domínio da stack) e como checá-los por dentro da rede do Compose — sem TLS,
sem passar pelo Traefik, para que a checagem continue funcionando quando o
certificado é auto-assinado.
"""

from __future__ import annotations

import asyncio
import time
from dataclasses import dataclass, field
from typing import Literal

import httpx

from .models import PortalService, ServiceHealth

ProbeKind = Literal["http", "tcp"]


@dataclass(frozen=True)
class ServiceDefinition:
    """Um serviço da stack e como o painel deve tratá-lo."""

    slug: str
    name: str
    description: str
    category: Literal["itsm", "operacao", "plataforma"]
    profile: str
    subdomain: str | None
    icon: str
    # Alguns serviços recusam ser embutidos (X-Frame-Options próprio ou fluxo de
    # login que não sobrevive ao iframe): esses abrem em nova aba. O painel
    # também cai para nova aba sozinho se o navegador bloquear o quadro.
    embeddable: bool = False
    path: str = "/"
    probe: ProbeKind = "http"
    probe_url: str = ""
    probe_host: str = ""
    probe_port: int = 0
    # Códigos HTTP que contam como "de pé" (consoles costumam responder 302/403)
    healthy_status: tuple[int, ...] = field(
        default=(200, 201, 204, 301, 302, 303, 307, 308, 401, 403)
    )


CATALOG: tuple[ServiceDefinition, ...] = (
    ServiceDefinition(
        slug="glpi",
        name="GLPI",
        description="Chamados, ativos (CMDB), contratos e base de conhecimento.",
        category="itsm",
        profile="core",
        subdomain="glpi",
        icon="ticket",
        embeddable=True,
        probe_url="http://glpi/",
    ),
    ServiceDefinition(
        slug="meshcentral",
        name="MeshCentral",
        description="RMM e acesso remoto não supervisionado às estações.",
        category="operacao",
        profile="rmm",
        subdomain="rmm",
        icon="monitor",
        embeddable=True,
        probe_url="https://meshcentral/",
    ),
    ServiceDefinition(
        slug="rustdesk",
        name="RustDesk",
        description="Acesso remoto sob demanda (relay TCP, fora do navegador).",
        category="operacao",
        profile="rmm",
        subdomain=None,
        icon="cast",
        probe="tcp",
        probe_host="rustdesk-hbbs",
        probe_port=21116,
    ),
    ServiceDefinition(
        slug="chatwoot",
        name="Chatwoot",
        description="Atendimento omnichannel: chat do site, WhatsApp e e-mail.",
        category="operacao",
        profile="omnichannel",
        subdomain="chat",
        icon="messages",
        embeddable=True,
        probe_url="http://chatwoot-web:3000/api",
    ),
    ServiceDefinition(
        slug="n8n",
        name="n8n",
        description="Automações: escalonamento de SLA, faturamento, integrações.",
        category="operacao",
        profile="automation",
        subdomain="n8n",
        icon="workflow",
        embeddable=True,
        probe_url="http://n8n:5678/healthz",
    ),
    ServiceDefinition(
        slug="metabase",
        name="Metabase",
        description="BI sobre os dados de chamados, contratos e faturamento.",
        category="operacao",
        profile="bi",
        subdomain="bi",
        icon="chart",
        probe_url="http://metabase:3000/api/health",
    ),
    ServiceDefinition(
        slug="grafana",
        name="Grafana",
        description="Painéis de infraestrutura, SLA e logs (Loki).",
        category="plataforma",
        profile="observability",
        subdomain="grafana",
        icon="activity",
        embeddable=True,
        probe_url="http://grafana:3000/api/health",
    ),
    ServiceDefinition(
        slug="keycloak",
        name="Keycloak",
        description="Identidade única (SSO), papéis e MFA.",
        category="plataforma",
        profile="core",
        subdomain="sso",
        icon="key",
        path="/admin/",
        probe_url="http://keycloak:9000/health/ready",
        healthy_status=(200,),
    ),
    ServiceDefinition(
        slug="minio",
        name="MinIO",
        description="Armazenamento de anexos e backups compatível com S3.",
        category="plataforma",
        profile="core",
        subdomain="minio",
        icon="database",
        probe_url="http://minio:9000/minio/health/live",
    ),
    ServiceDefinition(
        slug="bridge",
        name="itsm-bridge",
        description="API de integrações: RMM, omnichannel, SLA e faturamento.",
        category="plataforma",
        profile="core",
        subdomain="bridge",
        icon="plug",
        embeddable=True,
        path="/docs",
        probe_url="http://localhost:8000/healthz",
        healthy_status=(200,),
    ),
)

BY_SLUG = {service.slug: service for service in CATALOG}


def public_url(definition: ServiceDefinition, domain: str) -> str | None:
    if definition.subdomain is None:
        return None
    return f"https://{definition.subdomain}.{domain}{definition.path}"


def catalog(domain: str, profiles: set[str] | None = None) -> list[PortalService]:
    """Serviços que o painel deve listar, filtrados pelos perfis ativos."""
    return [
        PortalService(
            slug=item.slug,
            name=item.name,
            description=item.description,
            category=item.category,
            profile=item.profile,
            url=public_url(item, domain),
            icon=item.icon,
            embeddable=item.embeddable,
        )
        for item in CATALOG
        if profiles is None or item.profile in profiles
    ]


async def _probe_http(
    definition: ServiceDefinition, client: httpx.AsyncClient, timeout: float
) -> ServiceHealth:
    started = time.perf_counter()
    try:
        response = await client.get(definition.probe_url, timeout=timeout)
    except httpx.HTTPError as exc:
        return ServiceHealth(slug=definition.slug, status="offline", detail=str(exc)[:120])
    latency = int((time.perf_counter() - started) * 1000)
    if response.status_code in definition.healthy_status:
        return ServiceHealth(slug=definition.slug, status="online", latency_ms=latency)
    return ServiceHealth(
        slug=definition.slug,
        status="offline",
        latency_ms=latency,
        detail=f"HTTP {response.status_code}",
    )


async def _probe_tcp(definition: ServiceDefinition, timeout: float) -> ServiceHealth:
    started = time.perf_counter()
    writer = None
    try:
        _, writer = await asyncio.wait_for(
            asyncio.open_connection(definition.probe_host, definition.probe_port), timeout
        )
    except (TimeoutError, OSError) as exc:
        return ServiceHealth(slug=definition.slug, status="offline", detail=str(exc)[:120])
    finally:
        if writer is not None:
            writer.close()
    return ServiceHealth(
        slug=definition.slug,
        status="online",
        latency_ms=int((time.perf_counter() - started) * 1000),
    )


async def probe(
    definitions: list[ServiceDefinition], client: httpx.AsyncClient, timeout: float
) -> list[ServiceHealth]:
    """Checa todos os serviços em paralelo — a página de status é uma só requisição."""

    async def one(definition: ServiceDefinition) -> ServiceHealth:
        try:
            if definition.probe == "tcp":
                return await _probe_tcp(definition, timeout)
            return await _probe_http(definition, client, timeout)
        except Exception as exc:  # nenhuma sonda pode derrubar a página inteira
            return ServiceHealth(slug=definition.slug, status="unknown", detail=str(exc)[:120])

    return list(await asyncio.gather(*(one(item) for item in definitions)))


class StatusCache:
    """Memoriza o resultado das sondas por alguns segundos.

    O painel faz polling; sem cache, cada aba aberta viraria uma rajada de
    requisições contra todos os serviços da stack.
    """

    def __init__(self, ttl_seconds: int) -> None:
        self.ttl_seconds = ttl_seconds
        self._value: list[ServiceHealth] = []
        self._expires_at = 0.0
        self._lock = asyncio.Lock()

    async def get(
        self,
        definitions: list[ServiceDefinition],
        client: httpx.AsyncClient,
        timeout: float,
    ) -> list[ServiceHealth]:
        async with self._lock:
            now = time.monotonic()
            if self._value and now < self._expires_at:
                return self._value
            self._value = await probe(definitions, client, timeout)
            self._expires_at = now + self.ttl_seconds
            return self._value
