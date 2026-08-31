"""Testes de ponta a ponta da API HTTP (com o GLPI dublado)."""

from __future__ import annotations

import json

import pytest
from fastapi.testclient import TestClient

from app.config import Settings
from app.deps import get_config, get_glpi, get_store
from app.main import create_app
from app.security import SIGNATURE_HEADER, sign
from app.store import InMemoryStore

from .conftest import FakeGLPI

WEBHOOK_SECRET = "segredo-rmm"


@pytest.fixture
def context():
    glpi = FakeGLPI()
    store = InMemoryStore()
    settings = Settings(
        glpi_app_token="app-token",
        glpi_user_token="user-token",
        rmm_webhook_secret=WEBHOOK_SECRET,
        chatwoot_webhook_secret="",
        sla_poll_enabled=False,
        redis_url="",
    )

    app = create_app()
    app.dependency_overrides[get_config] = lambda: settings
    app.dependency_overrides[get_glpi] = lambda: glpi
    app.dependency_overrides[get_store] = lambda: store

    with TestClient(app) as client:
        yield client, glpi, settings


def post_signed(client: TestClient, url: str, payload: dict, secret: str = WEBHOOK_SECRET):
    body = json.dumps(payload).encode()
    headers = {"Content-Type": "application/json"}
    if secret:
        headers[SIGNATURE_HEADER] = sign(body, secret)
    return client.post(url, content=body, headers=headers)


ALERT = {
    "alert_id": "a-100",
    "severity": "high",
    "hostname": "srv-db",
    "check": "service-down",
    "message": "Serviço mariadb parado",
}


# --- webhooks --------------------------------------------------------------
def test_alerta_assinado_abre_chamado(context):
    client, glpi, _ = context
    response = post_signed(client, "/webhooks/rmm/alert", ALERT)

    assert response.status_code == 200
    body = response.json()
    assert body["status"] == "created"
    assert body["ticket_id"] == glpi.tickets[0]["id"]


def test_alerta_sem_assinatura_e_recusado(context):
    client, glpi, _ = context
    response = client.post("/webhooks/rmm/alert", json=ALERT)

    assert response.status_code == 401
    assert glpi.tickets == []


def test_alerta_com_assinatura_invalida_e_recusado(context):
    client, glpi, _ = context
    response = post_signed(client, "/webhooks/rmm/alert", ALERT, secret="segredo-errado")

    assert response.status_code == 401
    assert glpi.tickets == []


def test_payload_incompleto_devolve_422(context):
    client, _, _ = context
    response = post_signed(client, "/webhooks/rmm/alert", {"alert_id": "x"})
    assert response.status_code == 422


def test_corpo_nao_json_devolve_400(context):
    client, _, _ = context
    body = b"nao-e-json"
    response = client.post(
        "/webhooks/rmm/alert",
        content=body,
        headers={SIGNATURE_HEADER: sign(body, WEBHOOK_SECRET)},
    )
    assert response.status_code == 400


def test_chatwoot_sem_segredo_configurado_e_aceito(context):
    client, glpi, _ = context
    response = client.post(
        "/webhooks/chatwoot",
        json={
            "event": "message_created",
            "id": 1,
            "content": "Preciso de acesso ao ERP",
            "message_type": "incoming",
            "conversation": {"id": 8},
            "sender": {"name": "João"},
        },
    )
    assert response.status_code == 200
    assert response.json()["status"] == "created"
    assert glpi.tickets[0]["type"] == 2


# --- faturamento -----------------------------------------------------------
def test_previa_de_fatura(context):
    client, _, _ = context
    response = client.post(
        "/api/billing/invoices/preview",
        json={
            "contract": {
                "id": "CT-9",
                "client": "ACME",
                "billing_model": "hourly",
                "hourly_rate": "150.00",
                "rounding_increment_minutes": 15,
            },
            "period_start": "2026-08-01",
            "period_end": "2026-08-31",
            "time_entries": [
                {"ticket_id": 1, "minutes": 50},
                {"ticket_id": 2, "minutes": 25, "billable": False},
            ],
        },
    )
    assert response.status_code == 200
    body = response.json()
    assert body["billable_minutes"] == 60  # 50 -> 60 pelo incremento de 15min
    assert body["total"] == "150.00"


def test_previa_com_periodo_invalido_devolve_422(context):
    client, _, _ = context
    response = client.post(
        "/api/billing/invoices/preview",
        json={
            "contract": {"id": "CT-9", "client": "ACME", "billing_model": "fixed"},
            "period_start": "2026-08-31",
            "period_end": "2026-08-01",
        },
    )
    assert response.status_code == 422


# --- SLA -------------------------------------------------------------------
def test_calculo_de_prazo_pela_api(context):
    client, _, _ = context
    response = client.post(
        "/api/sla/deadline",
        json={
            "opened_at": "2026-08-31T17:00:00",
            "response_minutes": 30,
            "resolution_minutes": 180,
        },
    )
    assert response.status_code == 200
    body = response.json()
    assert body["response_due_at"] == "2026-08-31T17:30:00"
    assert body["resolution_due_at"] == "2026-09-01T10:00:00"


def test_sla_em_risco_pela_api(context):
    client, _, _ = context
    response = client.post(
        "/api/sla/at-risk",
        json={
            "due_at": "2026-08-31T12:00:00",
            "now": "2026-08-31T11:30:00",
            "threshold_minutes": 60,
        },
    )
    assert response.status_code == 200
    assert response.json() == {
        "at_risk": True,
        "breached": False,
        "business_minutes_remaining": 30,
    }


# --- infraestrutura --------------------------------------------------------
def test_healthz(context):
    client, _, _ = context
    assert client.get("/healthz").json() == {"status": "ok"}


def test_readyz_reporta_credenciais_do_glpi(context):
    client, _, _ = context
    body = client.get("/readyz").json()
    assert body["ready"] is True
    assert body["checks"]["glpi_credentials"] is True


def test_metrics_exposto_para_o_prometheus(context):
    client, _, _ = context
    post_signed(client, "/webhooks/rmm/alert", ALERT)
    text = client.get("/metrics").text
    assert "itsm_bridge_tickets_created_total" in text
    assert "itsm_tickets_sla_at_risk" in text
