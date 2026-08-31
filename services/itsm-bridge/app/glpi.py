"""Cliente assíncrono da REST API do GLPI.

Fluxo da API (apirest.php):

1. ``GET /initSession`` com ``App-Token`` + ``Authorization: user_token <token>``
   devolve um ``session_token``;
2. as demais chamadas usam ``Session-Token`` + ``App-Token``;
3. ``GET /killSession`` encerra a sessão — o GLPI limita sessões simultâneas,
   então sempre encerramos ao fim da operação.
"""

from __future__ import annotations

import logging
from collections.abc import AsyncIterator
from contextlib import asynccontextmanager
from typing import Any

import httpx

logger = logging.getLogger(__name__)

# searchoptions do GLPI usadas nas buscas (ver Configurar > pesquisa)
SEARCH_OPTION_NAME = 1
SEARCH_OPTION_COMPUTER_SERIAL = 5
SEARCH_OPTION_ENTITY_COMPLETENAME = 1
SEARCH_OPTION_TICKET_TIME_TO_RESOLVE = 18

# Mapa severidade do alerta -> urgência do GLPI (1 = muito baixa ... 5 = muito alta)
SEVERITY_TO_URGENCY = {
    "critical": 5,
    "high": 4,
    "warning": 3,
    "low": 2,
    "info": 1,
}

TICKET_TYPE_INCIDENT = 1
TICKET_TYPE_REQUEST = 2
TICKET_STATUS_SOLVED = 5


class GLPIError(RuntimeError):
    """Falha de comunicação ou de negócio com o GLPI."""


class GLPIClient:
    """Wrapper fino sobre a apirest.php, com sessão gerenciada."""

    def __init__(
        self,
        base_url: str,
        app_token: str,
        user_token: str,
        timeout: float = 15.0,
        client: httpx.AsyncClient | None = None,
    ) -> None:
        self.base_url = base_url.rstrip("/")
        self.app_token = app_token
        self.user_token = user_token
        self.timeout = timeout
        self._client = client
        self._owns_client = client is None
        self._session_token: str | None = None

    # -- infraestrutura ----------------------------------------------------
    async def _http(self) -> httpx.AsyncClient:
        if self._client is None:
            self._client = httpx.AsyncClient(timeout=self.timeout)
        return self._client

    def _headers(self, with_session: bool = True) -> dict[str, str]:
        headers = {"Content-Type": "application/json", "App-Token": self.app_token}
        if with_session:
            if not self._session_token:
                raise GLPIError("sessão não iniciada")
            headers["Session-Token"] = self._session_token
        return headers

    async def init_session(self) -> str:
        client = await self._http()
        response = await client.get(
            f"{self.base_url}/initSession",
            headers={
                "Content-Type": "application/json",
                "App-Token": self.app_token,
                "Authorization": f"user_token {self.user_token}",
            },
        )
        if response.status_code != 200:
            raise GLPIError(f"initSession falhou ({response.status_code}): {response.text[:300]}")
        token = response.json().get("session_token")
        if not token:
            raise GLPIError("initSession não devolveu session_token")
        self._session_token = token
        return token

    async def kill_session(self) -> None:
        if not self._session_token:
            return
        client = await self._http()
        try:
            await client.get(f"{self.base_url}/killSession", headers=self._headers())
        except httpx.HTTPError as exc:  # encerrar sessão nunca deve derrubar o fluxo
            logger.warning("falha ao encerrar sessão GLPI: %s", exc)
        finally:
            self._session_token = None

    async def aclose(self) -> None:
        if self._client is not None and self._owns_client:
            await self._client.aclose()
            self._client = None

    @asynccontextmanager
    async def session(self) -> AsyncIterator[GLPIClient]:
        await self.init_session()
        try:
            yield self
        finally:
            await self.kill_session()

    # -- operações ---------------------------------------------------------
    async def create_item(self, itemtype: str, payload: dict[str, Any]) -> int:
        client = await self._http()
        response = await client.post(
            f"{self.base_url}/{itemtype}",
            headers=self._headers(),
            json={"input": payload},
        )
        if response.status_code not in (200, 201):
            raise GLPIError(
                f"criação de {itemtype} falhou ({response.status_code}): {response.text[:300]}"
            )
        body = response.json()
        if isinstance(body, list):  # criação em lote devolve lista
            body = body[0]
        item_id = body.get("id")
        if item_id is None:
            raise GLPIError(f"resposta de criação de {itemtype} sem id: {body}")
        return int(item_id)

    async def update_item(self, itemtype: str, item_id: int, payload: dict[str, Any]) -> None:
        client = await self._http()
        response = await client.put(
            f"{self.base_url}/{itemtype}/{item_id}",
            headers=self._headers(),
            json={"input": payload},
        )
        if response.status_code not in (200, 201):
            raise GLPIError(
                f"atualização de {itemtype}/{item_id} falhou "
                f"({response.status_code}): {response.text[:300]}"
            )

    async def search(
        self,
        itemtype: str,
        criteria: list[dict[str, Any]],
        forcedisplay: list[int] | None = None,
        range_: str = "0-49",
    ) -> list[dict[str, Any]]:
        params: dict[str, Any] = {"range": range_}
        for index, criterion in enumerate(criteria):
            for key, value in criterion.items():
                params[f"criteria[{index}][{key}]"] = value
        for index, field in enumerate(forcedisplay or []):
            params[f"forcedisplay[{index}]"] = field

        client = await self._http()
        response = await client.get(
            f"{self.base_url}/search/{itemtype}", headers=self._headers(), params=params
        )
        # 206 Partial Content é a resposta normal de busca paginada do GLPI
        if response.status_code not in (200, 206):
            raise GLPIError(
                f"busca em {itemtype} falhou ({response.status_code}): {response.text[:300]}"
            )
        if not response.content:
            return []
        return response.json().get("data", []) or []

    # -- helpers de domínio ------------------------------------------------
    async def find_computer_id(self, hostname: str, serial: str | None = None) -> int | None:
        """Localiza o ativo pelo serial (mais confiável) e cai para o hostname."""
        if serial:
            found = await self.search(
                "Computer",
                [{"field": SEARCH_OPTION_COMPUTER_SERIAL, "searchtype": "equals", "value": serial}],
                range_="0-1",
            )
            if found:
                return int(found[0]["2"]) if "2" in found[0] else int(found[0].get("id", 0)) or None

        found = await self.search(
            "Computer",
            [{"field": SEARCH_OPTION_NAME, "searchtype": "equals", "value": hostname}],
            range_="0-1",
        )
        if found:
            return int(found[0]["2"]) if "2" in found[0] else int(found[0].get("id", 0)) or None
        return None

    async def find_entity_id(self, client_code: str) -> int | None:
        """Resolve o código do cliente para uma entidade (multi-tenant do GLPI)."""
        found = await self.search(
            "Entity",
            [
                {
                    "field": SEARCH_OPTION_ENTITY_COMPLETENAME,
                    "searchtype": "contains",
                    "value": client_code,
                }
            ],
            range_="0-1",
        )
        if found:
            raw_id = found[0].get("2") or found[0].get("id")
            return int(raw_id) if raw_id is not None else None
        return None

    async def create_ticket(
        self,
        name: str,
        content: str,
        entity_id: int,
        urgency: int = 3,
        ticket_type: int = TICKET_TYPE_INCIDENT,
    ) -> int:
        return await self.create_item(
            "Ticket",
            {
                "name": name[:255],
                "content": content,
                "entities_id": entity_id,
                "urgency": urgency,
                "impact": urgency,
                "priority": urgency,
                "type": ticket_type,
            },
        )

    async def add_followup(self, ticket_id: int, content: str, is_private: bool = False) -> int:
        return await self.create_item(
            "ITILFollowup",
            {
                "itemtype": "Ticket",
                "items_id": ticket_id,
                "content": content,
                "is_private": int(is_private),
            },
        )

    async def link_asset(self, ticket_id: int, computer_id: int) -> None:
        await self.create_item(
            "Item_Ticket",
            {"tickets_id": ticket_id, "itemtype": "Computer", "items_id": computer_id},
        )

    async def solve_ticket(self, ticket_id: int, solution: str) -> None:
        """Registra a solução e move o chamado para 'solucionado'."""
        await self.create_item(
            "ITILSolution",
            {"itemtype": "Ticket", "items_id": ticket_id, "content": solution},
        )
        await self.update_item("Ticket", ticket_id, {"status": TICKET_STATUS_SOLVED})

    async def open_tickets_with_deadline(self, limit: int = 200) -> list[dict[str, Any]]:
        """Chamados não encerrados com prazo de resolução definido."""
        return await self.search(
            "Ticket",
            [{"field": 12, "searchtype": "equals", "value": "notold"}],
            forcedisplay=[2, SEARCH_OPTION_NAME, SEARCH_OPTION_TICKET_TIME_TO_RESOLVE, 12, 80],
            range_=f"0-{max(limit - 1, 0)}",
        )
