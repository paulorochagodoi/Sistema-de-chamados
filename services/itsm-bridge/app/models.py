"""Schemas de entrada/saída do itsm-bridge."""

from __future__ import annotations

from datetime import date, datetime
from decimal import Decimal
from enum import StrEnum
from typing import Literal

from pydantic import BaseModel, Field, field_validator

from .glpi import TICKET_TYPE_INCIDENT

# ---------------------------------------------------------------------------
# Monitoramento proativo (RMM -> chamado)
# ---------------------------------------------------------------------------
Severity = Literal["critical", "high", "warning", "low", "info"]


class RMMAlert(BaseModel):
    """Alerta emitido pelo RMM (MeshCentral/Tactical) ou por qualquer coletor.

    O payload é propositalmente genérico: qualquer origem que consiga fazer um
    POST assinado consegue abrir chamado.
    """

    alert_id: str = Field(description="Identificador estável do alerta na origem")
    status: Literal["firing", "resolved"] = "firing"
    severity: Severity = "warning"
    hostname: str
    check: str = Field(description="Nome do monitor, ex.: disk-free, cpu, service-down")
    message: str = ""
    metric_value: float | None = None
    threshold: float | None = None
    asset_serial: str | None = None
    client_code: str | None = Field(
        default=None,
        description="Código do cliente; resolvido para uma entidade do GLPI",
    )
    entity_id: int | None = Field(
        default=None, description="Entidade GLPI explícita (tem precedência sobre client_code)"
    )
    occurred_at: datetime | None = None

    @field_validator("hostname", "check")
    @classmethod
    def _not_blank(cls, value: str) -> str:
        if not value.strip():
            raise ValueError("campo obrigatório não pode ser vazio")
        return value.strip()


class WebhookResult(BaseModel):
    status: Literal["created", "updated", "duplicate", "ignored", "closed"]
    ticket_id: int | None = None
    detail: str = ""


# ---------------------------------------------------------------------------
# Omnichannel (Chatwoot -> chamado)
# ---------------------------------------------------------------------------
class ChatwootEvent(BaseModel):
    """Subconjunto do payload de webhook do Chatwoot que nos interessa."""

    event: str
    id: int | None = None
    content: str | None = None
    message_type: str | None = None
    conversation: dict | None = None
    sender: dict | None = None
    account: dict | None = None

    @property
    def conversation_id(self) -> int | None:
        if self.conversation and "id" in self.conversation:
            return int(self.conversation["id"])
        if self.event.startswith("conversation") and self.id is not None:
            return int(self.id)
        return None

    @property
    def contact_name(self) -> str:
        if self.sender:
            name = self.sender.get("name") or self.sender.get("email")
            if name:
                return str(name)
        meta = (self.conversation or {}).get("meta", {})
        sender = meta.get("sender", {}) if isinstance(meta, dict) else {}
        return str(sender.get("name") or "Contato sem identificação")


# ---------------------------------------------------------------------------
# Contratos e faturamento
# ---------------------------------------------------------------------------
class BillingModel(StrEnum):
    HOURLY = "hourly"                # por hora apontada
    PER_TICKET = "per_ticket"        # por chamado encerrado
    PER_ASSET = "per_asset"          # por ativo monitorado
    FIXED = "fixed"                  # recorrência fixa
    FIXED_PLUS_HOURLY = "fixed_plus_hourly"  # franquia fixa + excedente por hora


class Contract(BaseModel):
    id: str
    client: str
    billing_model: BillingModel
    currency: str = "BRL"
    fixed_amount: Decimal = Decimal("0")
    hourly_rate: Decimal = Decimal("0")
    per_ticket_rate: Decimal = Decimal("0")
    per_asset_rate: Decimal = Decimal("0")
    included_hours: Decimal = Decimal("0")
    # Arredondamento do apontamento: mínimo cobrado e múltiplo (em minutos)
    minimum_billable_minutes: int = 0
    rounding_increment_minutes: int = 1
    discount_percent: Decimal = Decimal("0")
    tax_percent: Decimal = Decimal("0")
    valid_from: date | None = None
    valid_until: date | None = None

    @field_validator("rounding_increment_minutes")
    @classmethod
    def _increment_positive(cls, value: int) -> int:
        if value < 1:
            raise ValueError("rounding_increment_minutes deve ser >= 1")
        return value


class TimeEntry(BaseModel):
    """Apontamento de horas em um chamado."""

    ticket_id: int
    minutes: int = Field(ge=0)
    billable: bool = True
    technician: str = ""
    performed_at: date | None = None
    rate_override: Decimal | None = None
    description: str = ""


class InvoiceLine(BaseModel):
    kind: Literal["fixed", "hours", "overage_hours", "tickets", "assets", "discount", "tax"]
    description: str
    quantity: Decimal
    unit_price: Decimal
    amount: Decimal


class Invoice(BaseModel):
    contract_id: str
    client: str
    period_start: date
    period_end: date
    currency: str
    lines: list[InvoiceLine]
    subtotal: Decimal
    discount: Decimal
    tax: Decimal
    total: Decimal
    billable_minutes: int
    non_billable_minutes: int


class InvoiceRequest(BaseModel):
    contract: Contract
    period_start: date
    period_end: date
    time_entries: list[TimeEntry] = Field(default_factory=list)
    closed_tickets: int = 0
    monitored_assets: int = 0


# ---------------------------------------------------------------------------
# SLA
# ---------------------------------------------------------------------------
class BusinessHours(BaseModel):
    """Janela de atendimento usada no cálculo de prazos."""

    start: str = "08:00"
    end: str = "18:00"
    # 0 = segunda ... 6 = domingo
    workdays: list[int] = Field(default_factory=lambda: [0, 1, 2, 3, 4])
    holidays: list[date] = Field(default_factory=list)
    # 24x7 ignora janela e feriados (contratos de missão crítica)
    around_the_clock: bool = False


class SLARequest(BaseModel):
    opened_at: datetime
    response_minutes: int = Field(gt=0)
    resolution_minutes: int = Field(gt=0)
    business_hours: BusinessHours = Field(default_factory=BusinessHours)


class SLAResponse(BaseModel):
    opened_at: datetime
    response_due_at: datetime
    resolution_due_at: datetime
    business_minutes_to_response: int
    business_minutes_to_resolution: int


# ---------------------------------------------------------------------------
# Painel unificado (portal)
# ---------------------------------------------------------------------------
class PortalUser(BaseModel):
    """Quem está operando o painel."""

    id: int = 0
    username: str
    full_name: str = ""
    profile: str = ""
    # glpi = autenticado pelo formulário do painel; sso = identidade repassada
    # por um proxy OIDC à frente do painel
    source: Literal["glpi", "sso"] = "glpi"


class LoginRequest(BaseModel):
    username: str = Field(min_length=1)
    password: str = Field(min_length=1)


class LoginResponse(BaseModel):
    access_token: str
    token_type: Literal["bearer"] = "bearer"
    expires_in: int
    user: PortalUser


class PortalService(BaseModel):
    """Um serviço da stack, como o painel o apresenta."""

    slug: str
    name: str
    description: str
    category: Literal["itsm", "operacao", "plataforma"]
    profile: str
    url: str | None = None
    icon: str = "box"
    # o serviço aceita ser aberto dentro do painel (iframe) ou só em nova aba?
    embeddable: bool = False


class ServiceHealth(BaseModel):
    slug: str
    status: Literal["online", "offline", "unknown"]
    latency_ms: int | None = None
    detail: str = ""


class PortalTicket(BaseModel):
    id: int
    title: str = ""
    status: int = 0
    status_label: str = ""
    priority: int = 0
    priority_label: str = ""
    type: int = 0
    type_label: str = ""
    opened_at: str = ""
    due_at: str = ""
    requester: str = ""
    technician: str = ""
    entity: str = ""


class TicketFollowup(BaseModel):
    id: int
    content: str = ""
    created_at: str = ""
    author: str = ""
    is_private: bool = False


class PortalTicketDetail(PortalTicket):
    content: str = ""
    followups: list[TicketFollowup] = Field(default_factory=list)


class NewTicket(BaseModel):
    title: str = Field(min_length=1, max_length=255)
    content: str = Field(min_length=1)
    urgency: int = Field(default=3, ge=1, le=5)
    type: Literal[1, 2] = TICKET_TYPE_INCIDENT
    entity_id: int | None = None


class NewFollowup(BaseModel):
    content: str = Field(min_length=1)
    is_private: bool = False


class TicketSolution(BaseModel):
    content: str = Field(min_length=1)


class PortalSummary(BaseModel):
    """Números do painel inicial, agregados a partir dos chamados abertos."""

    total: int = 0
    open: int = 0
    unassigned: int = 0
    overdue: int = 0
    at_risk: int = 0
    by_status: dict[str, int] = Field(default_factory=dict)
    by_priority: dict[str, int] = Field(default_factory=dict)
    by_technician: dict[str, int] = Field(default_factory=dict)
    recent: list[PortalTicket] = Field(default_factory=list)
