"""Tradução das respostas do GLPI para o formato que o painel consome.

O GLPI devolve duas formas bem diferentes do mesmo chamado:

* ``/search/Ticket`` entrega linhas com as *searchoptions* como chave
  (``{"1": "Título", "12": 2, ...}``);
* ``/Ticket/{id}`` entrega o item com os nomes das colunas do banco.

Aqui as duas viram :class:`PortalTicket`. As funções são puras — dá para testar
o mapeamento inteiro sem GLPI nenhum.
"""

from __future__ import annotations

import html
import re
from typing import Any

from .glpi import (
    SEARCH_OPTION_NAME,
    SEARCH_OPTION_TICKET_ENTITY,
    SEARCH_OPTION_TICKET_ID,
    SEARCH_OPTION_TICKET_OPENING_DATE,
    SEARCH_OPTION_TICKET_PRIORITY,
    SEARCH_OPTION_TICKET_REQUESTER,
    SEARCH_OPTION_TICKET_STATUS,
    SEARCH_OPTION_TICKET_TECHNICIAN,
    SEARCH_OPTION_TICKET_TIME_TO_RESOLVE,
    SEARCH_OPTION_TICKET_TYPE,
)
from .models import PortalTicket, PortalTicketDetail, TicketFollowup

STATUS_LABELS = {
    1: "Novo",
    2: "Em atendimento",
    3: "Planejado",
    4: "Pendente",
    5: "Solucionado",
    6: "Fechado",
}
OPEN_STATUSES = (1, 2, 3, 4)

PRIORITY_LABELS = {
    1: "Muito baixa",
    2: "Baixa",
    3: "Média",
    4: "Alta",
    5: "Muito alta",
    6: "Crítica",
}

TYPE_LABELS = {1: "Incidente", 2: "Requisição"}

_TAG = re.compile(r"<[^>]+>")
_PARAGRAPH = re.compile(r"(?i)<\s*/\s*(p|div|h[1-6])\s*>")
_BREAK = re.compile(r"(?i)<\s*(br\s*/?|/\s*li|/\s*tr)\s*>")
_BLANK_LINES = re.compile(r"\n{3,}")


def html_to_text(value: Any) -> str:
    """Converte o rich text do GLPI em texto puro.

    O painel nunca injeta HTML de terceiros na página: o conteúdo do chamado é
    escrito por usuários e viraria um XSS refletido no navegador do técnico.
    """
    if not value:
        return ""
    text = _PARAGRAPH.sub("\n\n", str(value))
    text = _BREAK.sub("\n", text)
    text = _TAG.sub("", text)
    text = html.unescape(text)
    text = text.replace("\r\n", "\n").replace("\xa0", " ")
    return _BLANK_LINES.sub("\n\n", text).strip()


def _scalar(value: Any) -> str:
    """Achata os formatos que o GLPI usa para um mesmo campo.

    Um campo com vários valores (dois solicitantes, por exemplo) vem como lista;
    dropdowns expandidos vêm como dicionário.
    """
    if value is None:
        return ""
    if isinstance(value, list):
        return ", ".join(part for part in (_scalar(item) for item in value) if part)
    if isinstance(value, dict):
        for key in ("name", "completename", "friendlyname", "value"):
            if value.get(key):
                return str(value[key])
        return ""
    return str(value).strip()


def _int(value: Any, default: int = 0) -> int:
    try:
        return int(_scalar(value) or default)
    except (TypeError, ValueError):
        return default


def _labelled(value: Any, labels: dict[int, str]) -> tuple[int, str]:
    number = _int(value)
    return number, labels.get(number, "")


def from_search_row(row: dict[str, Any]) -> PortalTicket:
    """Converte uma linha de ``/search/Ticket`` em chamado do painel."""
    status, status_label = _labelled(row.get(str(SEARCH_OPTION_TICKET_STATUS)), STATUS_LABELS)
    priority, priority_label = _labelled(
        row.get(str(SEARCH_OPTION_TICKET_PRIORITY)), PRIORITY_LABELS
    )
    kind, type_label = _labelled(row.get(str(SEARCH_OPTION_TICKET_TYPE)), TYPE_LABELS)
    return PortalTicket(
        id=_int(row.get(str(SEARCH_OPTION_TICKET_ID)) or row.get("id")),
        title=_scalar(row.get(str(SEARCH_OPTION_NAME))),
        status=status,
        status_label=status_label,
        priority=priority,
        priority_label=priority_label,
        type=kind,
        type_label=type_label,
        opened_at=_scalar(row.get(str(SEARCH_OPTION_TICKET_OPENING_DATE))),
        due_at=_scalar(row.get(str(SEARCH_OPTION_TICKET_TIME_TO_RESOLVE))),
        requester=_scalar(row.get(str(SEARCH_OPTION_TICKET_REQUESTER))),
        technician=_scalar(row.get(str(SEARCH_OPTION_TICKET_TECHNICIAN))),
        entity=_scalar(row.get(str(SEARCH_OPTION_TICKET_ENTITY))),
    )


def from_item(
    item: dict[str, Any], followups: list[dict[str, Any]] | None = None
) -> PortalTicketDetail:
    """Converte ``/Ticket/{id}`` (com ``expand_dropdowns``) no detalhe do painel."""
    status, status_label = _labelled(item.get("status"), STATUS_LABELS)
    priority, priority_label = _labelled(item.get("priority"), PRIORITY_LABELS)
    kind, type_label = _labelled(item.get("type"), TYPE_LABELS)
    return PortalTicketDetail(
        id=_int(item.get("id")),
        title=_scalar(item.get("name")),
        status=status,
        status_label=status_label,
        priority=priority,
        priority_label=priority_label,
        type=kind,
        type_label=type_label,
        opened_at=_scalar(item.get("date_creation") or item.get("date")),
        due_at=_scalar(item.get("time_to_resolve")),
        requester=_scalar(item.get("users_id_recipient")),
        technician=_scalar(item.get("users_id_lastupdater")),
        entity=_scalar(item.get("entities_id")),
        content=html_to_text(item.get("content")),
        followups=[followup_from_item(entry) for entry in followups or []],
    )


def followup_from_item(entry: dict[str, Any]) -> TicketFollowup:
    return TicketFollowup(
        id=_int(entry.get("id")),
        content=html_to_text(entry.get("content")),
        created_at=_scalar(entry.get("date_creation") or entry.get("date")),
        author=_scalar(entry.get("users_id")),
        is_private=bool(_int(entry.get("is_private"))),
    )


def summarize(tickets: list[PortalTicket], now: str = "", soon: str = "") -> dict[str, Any]:
    """Agrega a listagem em números para o painel inicial.

    ``now`` e ``soon`` são datas no formato do GLPI (``YYYY-MM-DD HH:MM:SS``):
    prazo anterior a ``now`` conta como estourado; entre ``now`` e ``soon``,
    como em risco. Comparar as datas como texto é correto porque ambas vêm no
    mesmo fuso e no mesmo formato, zero-padded.
    """
    by_status: dict[str, int] = {}
    by_priority: dict[str, int] = {}
    by_technician: dict[str, int] = {}
    open_count = 0
    unassigned = 0
    overdue = 0
    at_risk = 0

    for ticket in tickets:
        label = ticket.status_label or str(ticket.status)
        by_status[label] = by_status.get(label, 0) + 1
        if ticket.status not in OPEN_STATUSES:
            continue
        open_count += 1
        priority = ticket.priority_label or str(ticket.priority)
        by_priority[priority] = by_priority.get(priority, 0) + 1
        technician = ticket.technician or "Não atribuído"
        by_technician[technician] = by_technician.get(technician, 0) + 1
        if not ticket.technician:
            unassigned += 1
        if now and ticket.due_at:
            if ticket.due_at < now:
                overdue += 1
            elif soon and ticket.due_at <= soon:
                at_risk += 1

    return {
        "total": len(tickets),
        "open": open_count,
        "unassigned": unassigned,
        "overdue": overdue,
        "at_risk": at_risk,
        "by_status": by_status,
        "by_priority": by_priority,
        "by_technician": dict(sorted(by_technician.items(), key=lambda kv: -kv[1])),
    }
