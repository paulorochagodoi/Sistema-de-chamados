"""Regras de conversão alerta/conversa -> chamado."""

from __future__ import annotations

import pytest

from app.glpi import GLPIError
from app.handlers import handle_chatwoot_event, handle_rmm_alert
from app.models import ChatwootEvent, RMMAlert

from .conftest import FakeGLPI


def alert(**overrides) -> RMMAlert:
    payload = {
        "alert_id": "alert-1",
        "severity": "critical",
        "hostname": "srv-fileserver",
        "check": "disk-free",
        "message": "Espaço livre em C: abaixo de 5%",
        "metric_value": 3.2,
        "threshold": 5.0,
    }
    payload.update(overrides)
    return RMMAlert(**payload)


async def test_alerta_abre_chamado_com_urgencia_mapeada(glpi, store, settings):
    result = await handle_rmm_alert(alert(), glpi, store, settings)

    assert result.status == "created"
    assert result.ticket_id == glpi.tickets[0]["id"]
    assert glpi.tickets[0]["urgency"] == 5  # critical
    assert "srv-fileserver" in glpi.tickets[0]["name"]
    assert "disk-free" in glpi.tickets[0]["content"]


async def test_alerta_vincula_o_ativo_ao_chamado(glpi, store, settings):
    result = await handle_rmm_alert(alert(asset_serial="SN-123"), glpi, store, settings)
    assert glpi.links == [(result.ticket_id, 77)]


async def test_alerta_sem_ativo_cadastrado_ainda_abre_chamado(store, settings):
    glpi = FakeGLPI(computer_id=None)
    result = await handle_rmm_alert(alert(), glpi, store, settings)
    assert result.status == "created"
    assert glpi.links == []


async def test_falha_ao_vincular_ativo_nao_invalida_o_chamado(store, settings):
    glpi = FakeGLPI(fail_on={"link_asset"})
    result = await handle_rmm_alert(alert(), glpi, store, settings)
    assert result.status == "created"
    assert result.ticket_id is not None


async def test_alerta_repetido_nao_abre_segundo_chamado(glpi, store, settings):
    first = await handle_rmm_alert(alert(), glpi, store, settings)
    second = await handle_rmm_alert(alert(), glpi, store, settings)

    assert second.status == "duplicate"
    assert second.ticket_id == first.ticket_id
    assert len(glpi.tickets) == 1


async def test_normalizacao_registra_acompanhamento_e_libera_a_dedupe(glpi, store, settings):
    created = await handle_rmm_alert(alert(), glpi, store, settings)
    resolved = await handle_rmm_alert(alert(status="resolved"), glpi, store, settings)

    assert resolved.status == "updated"
    assert resolved.ticket_id == created.ticket_id
    assert glpi.followups and "normalização" in glpi.followups[0][1]

    # o chamado não é encerrado automaticamente: o técnico valida a causa raiz
    assert glpi.solutions == []

    # com a correlação liberada, um novo disparo abre chamado novo
    again = await handle_rmm_alert(alert(), glpi, store, settings)
    assert again.status == "created"
    assert again.ticket_id != created.ticket_id


async def test_normalizacao_sem_chamado_correlacionado_e_ignorada(glpi, store, settings):
    result = await handle_rmm_alert(alert(status="resolved"), glpi, store, settings)
    assert result.status == "ignored"
    assert glpi.tickets == []


async def test_entidade_resolvida_pelo_codigo_do_cliente(glpi, store, settings):
    await handle_rmm_alert(alert(client_code="ACME"), glpi, store, settings)
    assert glpi.tickets[0]["entities_id"] == 5


async def test_entidade_explicita_tem_precedencia(glpi, store, settings):
    await handle_rmm_alert(alert(client_code="ACME", entity_id=9), glpi, store, settings)
    assert glpi.tickets[0]["entities_id"] == 9


async def test_cliente_desconhecido_cai_na_entidade_padrao(store, settings):
    glpi = FakeGLPI(entity_id=None)
    settings.default_entity_id = 3
    await handle_rmm_alert(alert(client_code="INEXISTENTE"), glpi, store, settings)
    assert glpi.tickets[0]["entities_id"] == 3


async def test_falha_na_criacao_propaga_erro(store, settings):
    glpi = FakeGLPI(fail_on={"create_ticket"})
    with pytest.raises(GLPIError):
        await handle_rmm_alert(alert(), glpi, store, settings)
    # sem correlação gravada, a próxima tentativa do RMM pode reprocessar
    assert await store.get("rmm:alert-1") is None


# --- Chatwoot --------------------------------------------------------------
def chat_event(**overrides) -> ChatwootEvent:
    payload = {
        "event": "message_created",
        "id": 1,
        "content": "Minha impressora parou de funcionar",
        "message_type": "incoming",
        "conversation": {"id": 42},
        "sender": {"name": "Maria Souza"},
    }
    payload.update(overrides)
    return ChatwootEvent(**payload)


async def test_conversa_abre_chamado_como_requisicao(glpi, store, settings):
    result = await handle_chatwoot_event(chat_event(), glpi, store, settings)
    assert result.status == "created"
    assert glpi.tickets[0]["type"] == 2  # requisição de serviço
    assert "Maria Souza" in glpi.tickets[0]["name"]


async def test_mensagens_seguintes_viram_acompanhamento(glpi, store, settings):
    created = await handle_chatwoot_event(chat_event(), glpi, store, settings)
    updated = await handle_chatwoot_event(
        chat_event(content="Continua sem imprimir"), glpi, store, settings
    )

    assert updated.status == "updated"
    assert updated.ticket_id == created.ticket_id
    assert len(glpi.tickets) == 1
    assert "Continua sem imprimir" in glpi.followups[0][1]


async def test_mensagem_do_agente_nao_e_espelhada(glpi, store, settings):
    result = await handle_chatwoot_event(
        chat_event(message_type="outgoing"), glpi, store, settings
    )
    assert result.status == "ignored"
    assert glpi.tickets == []


async def test_evento_sem_conversa_e_ignorado(glpi, store, settings):
    result = await handle_chatwoot_event(
        ChatwootEvent(event="contact_created", id=7), glpi, store, settings
    )
    assert result.status == "ignored"
