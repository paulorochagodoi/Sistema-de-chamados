"""Métricas Prometheus do bridge (scrape em /metrics)."""

from __future__ import annotations

from prometheus_client import Counter, Gauge, Histogram

tickets_created = Counter(
    "itsm_bridge_tickets_created_total",
    "Chamados abertos automaticamente pelo bridge",
    ["source", "severity"],
)

ticket_failures = Counter(
    "itsm_bridge_ticket_failures_total",
    "Falhas ao criar ou atualizar chamados no GLPI",
    ["source"],
)

alerts_deduplicated = Counter(
    "itsm_bridge_alerts_deduplicated_total",
    "Alertas descartados por já existir chamado aberto na janela de dedupe",
    ["source"],
)

webhook_rejected = Counter(
    "itsm_bridge_webhook_rejected_total",
    "Webhooks rejeitados (assinatura inválida ou payload malformado)",
    ["source", "reason"],
)

webhook_duration = Histogram(
    "itsm_bridge_webhook_duration_seconds",
    "Tempo de processamento dos webhooks",
    ["source"],
    buckets=(0.05, 0.1, 0.25, 0.5, 1.0, 2.5, 5.0, 10.0),
)

sla_at_risk = Gauge(
    "itsm_tickets_sla_at_risk",
    "Chamados abertos cujo prazo de resolução está a vencer ou já venceu",
)

sla_poll_errors = Counter(
    "itsm_bridge_sla_poll_errors_total",
    "Falhas ao consultar o GLPI para calcular SLA em risco",
)
