"""Painel unificado: catálogo, sessão e chamados."""

from __future__ import annotations

import base64

import httpx
import jwt
import pytest
from fastapi.testclient import TestClient

from app import portal
from app.auth import AuthError, authenticate_with_glpi, decode_token, issue_token
from app.config import Settings
from app.deps import get_config, get_current_user, get_glpi, get_http_client
from app.main import create_app
from app.models import PortalUser
from app.tickets import from_search_row, html_to_text, summarize

from .conftest import FakeGLPI

SECRET = "segredo-do-painel"


def row(ticket_id: int, **overrides) -> dict:
    """Linha de /search/Ticket como o GLPI devolve (searchoption -> valor)."""
    data = {
        "2": ticket_id,
        "1": f"Chamado {ticket_id}",
        "3": 3,
        "4": "Maria Cliente",
        "5": "Ana Técnica",
        "12": 2,
        "14": 1,
        "15": "2026-08-31 09:00:00",
        "18": "2099-12-31 17:00:00",
        "80": "Cliente A",
    }
    data.update({str(key): value for key, value in overrides.items()})
    return data


@pytest.fixture
def portal_settings() -> Settings:
    return Settings(
        glpi_app_token="app-token",
        glpi_user_token="user-token",
        portal_secret=SECRET,
        portal_domain="itsm.example.com",
        sla_poll_enabled=False,
        redis_url="",
    )


@pytest.fixture
def context(portal_settings):
    glpi = FakeGLPI()
    user = PortalUser(id=7, username="ana", full_name="Ana Técnica", profile="Técnico")

    app = create_app()
    app.dependency_overrides[get_config] = lambda: portal_settings
    app.dependency_overrides[get_glpi] = lambda: glpi
    app.dependency_overrides[get_current_user] = lambda: user

    with TestClient(app) as client:
        yield client, glpi, user


# --- catálogo de serviços --------------------------------------------------
def test_catalogo_deriva_as_urls_do_dominio():
    services = {item.slug: item for item in portal.catalog("itsm.example.com")}

    assert services["glpi"].url == "https://glpi.itsm.example.com/"
    assert services["keycloak"].url == "https://sso.itsm.example.com/admin/"
    assert services["bridge"].url == "https://bridge.itsm.example.com/docs"
    # RustDesk não fala HTTP: aparece no painel sem link de navegação
    assert services["rustdesk"].url is None


def test_catalogo_respeita_os_perfis_ativos():
    slugs = {item.slug for item in portal.catalog("itsm.example.com", {"core"})}

    assert "glpi" in slugs
    assert "grafana" not in slugs  # perfil observability não está de pé


def test_catalogo_cobre_todos_os_perfis_do_compose():
    perfis = {item.profile for item in portal.CATALOG}
    assert perfis == {"core", "rmm", "omnichannel", "automation", "bi", "observability"}


def test_endpoint_de_servicos_lista_o_catalogo(context):
    client, _, _ = context
    response = client.get("/api/portal/services")

    assert response.status_code == 200
    slugs = [item["slug"] for item in response.json()]
    assert "glpi" in slugs and "n8n" in slugs


# --- sessão ----------------------------------------------------------------
def test_token_do_painel_vai_e_volta():
    user = PortalUser(id=42, username="ana", full_name="Ana Técnica", profile="Supervisor")
    token, expires_in = issue_token(user, SECRET, 60)

    restored = decode_token(token, SECRET)
    assert expires_in == 3600
    assert (restored.id, restored.username, restored.profile) == (42, "ana", "Supervisor")


def test_token_assinado_com_outra_chave_e_recusado():
    token, _ = issue_token(PortalUser(username="ana"), SECRET, 60)
    with pytest.raises(AuthError):
        decode_token(token, "outra-chave")


def test_token_expirado_e_recusado():
    expirado = jwt.encode(
        {"iss": "itsm-bridge", "sub": "1", "username": "ana", "exp": 1_000_000_000},
        SECRET,
        algorithm="HS256",
    )
    with pytest.raises(AuthError, match="expirada"):
        decode_token(expirado, SECRET)


def test_painel_exige_autenticacao(portal_settings):
    app = create_app()
    app.dependency_overrides[get_config] = lambda: portal_settings
    app.dependency_overrides[get_glpi] = lambda: FakeGLPI()

    with TestClient(app) as client:
        for url in ("/api/portal/services", "/api/portal/tickets", "/api/portal/summary"):
            assert client.get(url).status_code == 401


def test_token_valido_abre_o_painel(portal_settings):
    app = create_app()
    app.dependency_overrides[get_config] = lambda: portal_settings
    app.dependency_overrides[get_glpi] = lambda: FakeGLPI()
    token, _ = issue_token(PortalUser(id=1, username="ana"), SECRET, 60)

    with TestClient(app) as client:
        response = client.get(
            "/api/portal/auth/me", headers={"Authorization": f"Bearer {token}"}
        )

    assert response.status_code == 200
    assert response.json()["username"] == "ana"


def test_identidade_do_sso_so_vale_quando_habilitada():
    headers = {"X-Auth-Request-User": "ana@example.com"}

    desligado = Settings(portal_secret=SECRET, portal_trust_forwarded_auth=False)
    ligado = Settings(portal_secret=SECRET, portal_trust_forwarded_auth=True)

    for settings, expected in ((desligado, 401), (ligado, 200)):
        app = create_app()
        app.dependency_overrides[get_config] = lambda s=settings: s
        with TestClient(app) as client:
            assert client.get("/api/portal/auth/me", headers=headers).status_code == expected


# --- chamados --------------------------------------------------------------
def test_listagem_traduz_as_searchoptions_do_glpi(context):
    client, glpi, _ = context
    glpi.rows = [row(10), row(11, **{"12": 4})]

    response = client.get("/api/portal/tickets")

    assert response.status_code == 200
    first, second = response.json()
    assert first["id"] == 10
    assert first["status_label"] == "Em atendimento"
    assert first["requester"] == "Maria Cliente"
    assert first["entity"] == "Cliente A"
    assert second["status_label"] == "Pendente"


def test_listagem_repassa_os_filtros(context):
    client, glpi, _ = context
    client.get("/api/portal/tickets?status=1&search=impressora&limit=10&offset=20")

    assert glpi.queries[-1] == {
        "status": "1",
        "search": "impressora",
        "entity_id": None,
        "limit": 10,
        "offset": 20,
    }


def test_falha_do_glpi_vira_502(context):
    client, glpi, _ = context
    glpi.fail_on.add("list_tickets")

    assert client.get("/api/portal/tickets").status_code == 502


def test_resumo_agrega_status_prioridade_e_prazo(context):
    client, glpi, _ = context
    glpi.rows = [
        row(1, **{"12": 1, "3": 5, "5": "", "18": "2000-01-01 00:00:00"}),  # vencido, sem técnico
        row(2, **{"12": 2, "3": 3}),
        row(3, **{"12": 4, "3": 3}),
    ]

    body = client.get("/api/portal/summary").json()

    assert body["total"] == 3
    assert body["open"] == 3
    assert body["unassigned"] == 1
    assert body["overdue"] == 1
    assert body["by_status"]["Novo"] == 1
    assert body["by_priority"]["Média"] == 2
    assert body["by_technician"]["Não atribuído"] == 1
    assert len(body["recent"]) == 3


def test_resumo_separa_prazo_vencido_de_prazo_a_vencer():
    tickets = [
        from_search_row(row(1, **{"18": "2026-08-31 08:00:00"})),  # já venceu
        from_search_row(row(2, **{"18": "2026-08-31 12:30:00"})),  # vence dentro da janela
        from_search_row(row(3, **{"18": "2026-08-31 18:00:00"})),  # fora da janela
    ]

    aggregate = summarize(tickets, now="2026-08-31 12:00:00", soon="2026-08-31 13:00:00")

    assert aggregate["overdue"] == 1
    assert aggregate["at_risk"] == 1


def test_abertura_registra_quem_pediu(context):
    client, glpi, user = context
    response = client.post(
        "/api/portal/tickets",
        json={"title": "Sem internet", "content": "Link caiu", "urgency": 4, "type": 1},
    )

    assert response.status_code == 201
    assert response.json()["priority_label"] == "Alta"
    assert glpi.tickets[0]["requester_id"] == user.id
    assert glpi.tickets[0]["urgency"] == 4


def test_detalhe_traz_conteudo_em_texto_puro(context):
    client, _, _ = context
    body = client.get("/api/portal/tickets/55").json()

    assert body["id"] == 55
    assert body["content"] == "Trocar o toner"
    assert body["entity"] == "Cliente A"
    assert body["followups"][0]["content"] == "Chamado recebido"


def test_acompanhamento_assina_quem_escreveu(context):
    client, glpi, _ = context
    response = client.post(
        "/api/portal/tickets/55/followups", json={"content": "Técnico a caminho"}
    )

    assert response.status_code == 200
    assert "Ana Técnica" in glpi.followups[0][1]
    assert any("Técnico a caminho" in item["content"] for item in response.json()["followups"])


def test_solucao_encerra_o_chamado(context):
    client, glpi, _ = context
    response = client.post("/api/portal/tickets/55/solution", json={"content": "Toner trocado"})

    assert response.status_code == 200
    assert glpi.solutions[0][0] == 55
    assert "Toner trocado" in glpi.solutions[0][1]


# --- mapeamento puro -------------------------------------------------------
def test_html_do_glpi_vira_texto():
    assert html_to_text("<p>Linha 1</p><p>Linha 2</p>") == "Linha 1\n\nLinha 2"
    assert html_to_text("<b>caf&eacute;</b> &amp; ch&aacute;") == "café & chá"
    assert html_to_text(None) == ""


def test_campo_multivalorado_do_glpi_e_achatado():
    ticket = from_search_row(row(1, **{"4": ["Maria", "João"], "80": {"name": "Cliente B"}}))
    assert ticket.requester == "Maria, João"
    assert ticket.entity == "Cliente B"


def test_resumo_ignora_encerrados_no_contador_de_abertos():
    tickets = [from_search_row(row(1, **{"12": 6})), from_search_row(row(2, **{"12": 2}))]
    aggregate = summarize(tickets, now="2026-08-31 12:00:00")

    assert aggregate["total"] == 2
    assert aggregate["open"] == 1
    assert aggregate["by_status"]["Fechado"] == 1


# --- login contra o GLPI ---------------------------------------------------
def glpi_stub(
    status_code: int = 200, session: dict | None = None
) -> tuple[httpx.AsyncClient, list]:
    """Dublê da apirest.php: registra as chamadas e devolve a sessão pedida."""
    chamadas: list[httpx.Request] = []

    def handler(request: httpx.Request) -> httpx.Response:
        chamadas.append(request)
        if request.url.path.endswith("/initSession"):
            if status_code != 200:
                return httpx.Response(status_code, json={"detail": "ERROR_LOGIN"})
            return httpx.Response(200, json={"session_token": "sess-123"})
        if request.url.path.endswith("/getFullSession"):
            return httpx.Response(200, json={"session": session or {}})
        return httpx.Response(200, json={})

    return httpx.AsyncClient(transport=httpx.MockTransport(handler)), chamadas


async def test_login_no_glpi_devolve_a_identidade_da_sessao():
    client, chamadas = glpi_stub(
        session={
            "glpiID": 12,
            "glpiname": "ana",
            "glpifriendlyname": "Ana Técnica",
            "glpiactiveprofile": {"name": "Técnico"},
        }
    )

    user = await authenticate_with_glpi(
        "ana", "senha", "http://glpi/apirest.php", "app-token", client
    )

    identidade = (user.id, user.username, user.full_name, user.profile)
    assert identidade == (12, "ana", "Ana Técnica", "Técnico")
    assert user.source == "glpi"

    inicio = chamadas[0]
    assert inicio.headers["App-Token"] == "app-token"
    esperado = base64.b64encode(b"ana:senha").decode()
    assert inicio.headers["Authorization"] == f"Basic {esperado}"
    # a sessão aberta para autenticar precisa ser encerrada: o GLPI limita sessões
    assert chamadas[-1].url.path.endswith("/killSession")


async def test_credencial_invalida_vira_erro_de_autenticacao():
    client, _ = glpi_stub(status_code=401)

    with pytest.raises(AuthError, match="usuário ou senha inválidos"):
        await authenticate_with_glpi(
            "ana", "errada", "http://glpi/apirest.php", "app-token", client
        )


def test_endpoint_de_login_devolve_token_utilizavel(portal_settings):
    http_client, _ = glpi_stub(session={"glpiID": 3, "glpiname": "ana"})

    app = create_app()
    app.dependency_overrides[get_config] = lambda: portal_settings
    app.dependency_overrides[get_http_client] = lambda: http_client
    app.dependency_overrides[get_glpi] = lambda: FakeGLPI()

    with TestClient(app) as client:
        login = client.post("/api/portal/auth/login", json={"username": "ana", "password": "s3nha"})
        assert login.status_code == 200
        corpo = login.json()
        assert corpo["user"]["username"] == "ana"
        assert corpo["expires_in"] == portal_settings.portal_session_minutes * 60

        me = client.get(
            "/api/portal/auth/me",
            headers={"Authorization": f"Bearer {corpo['access_token']}"},
        )

    assert me.status_code == 200
    assert me.json()["id"] == 3


def test_login_sem_credenciais_do_glpi_responde_503():
    app = create_app()
    app.dependency_overrides[get_config] = lambda: Settings(glpi_app_token="", portal_secret=SECRET)

    with TestClient(app) as client:
        resposta = client.post("/api/portal/auth/login", json={"username": "a", "password": "b"})

    assert resposta.status_code == 503
