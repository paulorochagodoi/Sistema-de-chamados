"""Regras de negócio das integrações (independentes do framework web)."""

from __future__ import annotations

import logging
from datetime import datetime

from . import metrics
from .config import Settings
from .glpi import SEVERITY_TO_URGENCY, TICKET_TYPE_INCIDENT, TICKET_TYPE_REQUEST, GLPIClient
from .models import ChatwootEvent, RMMAlert, WebhookResult
from .store import CorrelationStore

logger = logging.getLogger(__name__)


def _format_alert_body(alert: RMMAlert) -> str:
    occurred = (alert.occurred_at or datetime.now()).strftime("%d/%m/%Y %H:%M:%S")
    lines = [
        "Chamado aberto automaticamente pelo monitoramento proativo (RMM).",
        "",
        f"Host: {alert.hostname}",
        f"Monitor: {alert.check}",
        f"Severidade: {alert.severity}",
        f"Ocorrido em: {occurred}",
        f"Identificador do alerta: {alert.alert_id}",
    ]
    if alert.asset_serial:
        lines.append(f"Série do ativo: {alert.asset_serial}")
    if alert.metric_value is not None:
        threshold = f" (limite: {alert.threshold})" if alert.threshold is not None else ""
        lines.append(f"Valor medido: {alert.metric_value}{threshold}")
    if alert.message:
        lines += ["", alert.message]
    return "\n".join(lines)


async def resolve_entity(alert: RMMAlert, glpi: GLPIClient, settings: Settings) -> int:
    """Descobre em qual entidade (cliente) o chamado deve nascer."""
    if alert.entity_id is not None:
        return alert.entity_id
    if alert.client_code:
        try:
            entity_id = await glpi.find_entity_id(alert.client_code)
        except Exception as exc:  # a entidade errada é pior que a padrão: só loga
            logger.warning("falha ao resolver entidade '%s': %s", alert.client_code, exc)
            entity_id = None
        if entity_id is not None:
            return entity_id
        logger.warning(
            "cliente '%s' sem entidade correspondente; usando a entidade padrão %s",
            alert.client_code,
            settings.default_entity_id,
        )
    return settings.default_entity_id


async def handle_rmm_alert(
    alert: RMMAlert,
    glpi: GLPIClient,
    store: CorrelationStore,
    settings: Settings,
) -> WebhookResult:
    """Converte um alerta do RMM em chamado, deduplicando repetições."""
    key = f"rmm:{alert.alert_id}"
    existing = await store.get(key)

    if alert.status == "resolved":
        if existing is None:
            return WebhookResult(status="ignored", detail="alerta sem chamado correlacionado")
        await glpi.add_followup(
            existing,
            f"O monitoramento sinalizou a normalização de '{alert.check}' em "
            f"{alert.hostname}. Alerta {alert.alert_id} encerrado na origem.",
        )
        await store.delete(key)
        # não encerramos o chamado automaticamente: o técnico valida a causa raiz
        return WebhookResult(status="updated", ticket_id=existing, detail="normalização registrada")

    if existing is not None:
        metrics.alerts_deduplicated.labels(source="rmm").inc()
        return WebhookResult(
            status="duplicate",
            ticket_id=existing,
            detail="alerta repetido dentro da janela de deduplicação",
        )

    entity_id = await resolve_entity(alert, glpi, settings)
    urgency = SEVERITY_TO_URGENCY.get(alert.severity, 3)
    title = f"[{alert.severity.upper()}] {alert.hostname} — {alert.check}"

    try:
        ticket_id = await glpi.create_ticket(
            name=title,
            content=_format_alert_body(alert),
            entity_id=entity_id,
            urgency=urgency,
            ticket_type=TICKET_TYPE_INCIDENT,
        )
    except Exception:
        metrics.ticket_failures.labels(source="rmm").inc()
        raise

    # Vincular o ativo é desejável, não essencial: falha aqui não invalida o chamado.
    try:
        computer_id = await glpi.find_computer_id(alert.hostname, alert.asset_serial)
        if computer_id:
            await glpi.link_asset(ticket_id, computer_id)
    except Exception as exc:
        logger.warning("não foi possível vincular o ativo ao chamado %s: %s", ticket_id, exc)

    await store.set(key, ticket_id, settings.dedupe_ttl_seconds)
    metrics.tickets_created.labels(source="rmm", severity=alert.severity).inc()
    logger.info(
        "chamado %s aberto para o alerta %s (%s/%s)",
        ticket_id,
        alert.alert_id,
        alert.hostname,
        alert.check,
    )
    return WebhookResult(status="created", ticket_id=ticket_id)


async def handle_chatwoot_event(
    event: ChatwootEvent,
    glpi: GLPIClient,
    store: CorrelationStore,
    settings: Settings,
) -> WebhookResult:
    """Espelha conversas do Chatwoot como chamados no GLPI.

    Uma conversa vira um chamado; as mensagens seguintes do cliente viram
    acompanhamentos, mantendo o histórico unificado no núcleo ITSM.
    """
    conversation_id = event.conversation_id
    if conversation_id is None:
        return WebhookResult(status="ignored", detail="evento sem conversa associada")

    # respostas do agente já ficam registradas no Chatwoot; só espelhamos o cliente
    if event.event == "message_created" and event.message_type not in (None, "incoming"):
        return WebhookResult(status="ignored", detail="mensagem de saída não espelhada")

    key = f"chatwoot:{conversation_id}"
    existing = await store.get(key)
    content = (event.content or "").strip()

    if existing is not None:
        if not content:
            return WebhookResult(status="ignored", ticket_id=existing, detail="mensagem vazia")
        await glpi.add_followup(existing, f"[chat] {event.contact_name}: {content}")
        return WebhookResult(status="updated", ticket_id=existing)

    if event.event not in ("conversation_created", "message_created"):
        return WebhookResult(status="ignored", detail=f"evento não tratado: {event.event}")

    title = f"[chat] {event.contact_name} — conversa {conversation_id}"
    body = "\n".join(
        [
            "Chamado aberto a partir de uma conversa do Chatwoot (omnichannel).",
            "",
            f"Conversa: {conversation_id}",
            f"Contato: {event.contact_name}",
            "",
            content or "(conversa iniciada sem mensagem)",
        ]
    )

    try:
        ticket_id = await glpi.create_ticket(
            name=title,
            content=body,
            entity_id=settings.default_entity_id,
            urgency=3,
            ticket_type=TICKET_TYPE_REQUEST,
        )
    except Exception:
        metrics.ticket_failures.labels(source="chatwoot").inc()
        raise

    await store.set(key, ticket_id, settings.conversation_ttl_seconds)
    metrics.tickets_created.labels(source="chatwoot", severity="n/a").inc()
    return WebhookResult(status="created", ticket_id=ticket_id)
