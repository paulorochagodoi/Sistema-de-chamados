from __future__ import annotations

import sys
from pathlib import Path
from typing import Any

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from app.config import Settings  # noqa: E402
from app.store import InMemoryStore  # noqa: E402


class FakeGLPI:
    """Dublê do GLPIClient: registra as chamadas e devolve ids previsíveis."""

    def __init__(
        self,
        computer_id: int | None = 77,
        entity_id: int | None = 5,
        fail_on: set[str] | None = None,
    ) -> None:
        self.computer_id = computer_id
        self.entity_id = entity_id
        self.fail_on = fail_on or set()
        self.tickets: list[dict[str, Any]] = []
        self.followups: list[tuple[int, str]] = []
        self.links: list[tuple[int, int]] = []
        self.solutions: list[tuple[int, str]] = []
        # linhas cruas de /search/Ticket devolvidas por list_tickets
        self.rows: list[dict[str, Any]] = []
        self.queries: list[dict[str, Any]] = []
        self.followups_added: list[dict[str, Any]] = []
        self._next_id = 1000

    async def create_ticket(
        self,
        name: str,
        content: str,
        entity_id: int,
        urgency: int = 3,
        ticket_type: int = 1,
        requester_id: int | None = None,
    ) -> int:
        if "create_ticket" in self.fail_on:
            from app.glpi import GLPIError

            raise GLPIError("GLPI indisponível")
        self._next_id += 1
        self.tickets.append(
            {
                "id": self._next_id,
                "name": name,
                "content": content,
                "entities_id": entity_id,
                "urgency": urgency,
                "type": ticket_type,
                "requester_id": requester_id,
            }
        )
        return self._next_id

    async def add_followup(self, ticket_id: int, content: str, is_private: bool = False) -> int:
        self.followups.append((ticket_id, content))
        self.followups_added.append(
            {
                "id": 100 + len(self.followups),
                "content": content,
                "date_creation": "2026-08-31 10:00:00",
                "users_id": "API",
                "is_private": int(is_private),
            }
        )
        return len(self.followups)

    async def find_computer_id(self, hostname: str, serial: str | None = None) -> int | None:
        if "find_computer_id" in self.fail_on:
            raise RuntimeError("busca de ativo falhou")
        return self.computer_id

    async def find_entity_id(self, client_code: str) -> int | None:
        if "find_entity_id" in self.fail_on:
            raise RuntimeError("busca de entidade falhou")
        return self.entity_id

    async def link_asset(self, ticket_id: int, computer_id: int) -> None:
        if "link_asset" in self.fail_on:
            raise RuntimeError("vínculo falhou")
        self.links.append((ticket_id, computer_id))

    async def solve_ticket(self, ticket_id: int, solution: str) -> None:
        self.solutions.append((ticket_id, solution))

    # -- leituras usadas pelo painel ---------------------------------------
    async def list_tickets(
        self,
        status: str | int = "notold",
        search: str = "",
        entity_id: int | None = None,
        limit: int = 50,
        offset: int = 0,
    ) -> list[dict[str, Any]]:
        if "list_tickets" in self.fail_on:
            from app.glpi import GLPIError

            raise GLPIError("busca indisponível")
        self.queries.append(
            {
                "status": status,
                "search": search,
                "entity_id": entity_id,
                "limit": limit,
                "offset": offset,
            }
        )
        return self.rows[offset : offset + limit]

    async def get_ticket(self, ticket_id: int) -> dict[str, Any]:
        return {
            "id": ticket_id,
            "name": "Impressora sem tinta",
            "content": "<p>Trocar o <b>toner</b></p>",
            "status": 2,
            "priority": 4,
            "type": 1,
            "date_creation": "2026-08-31 09:00:00",
            "time_to_resolve": "2026-08-31 17:00:00",
            "entities_id": "Cliente A",
        }

    async def ticket_followups(self, ticket_id: int) -> list[dict[str, Any]]:
        return [
            {
                "id": 1,
                "content": "<p>Chamado recebido</p>",
                "date_creation": "2026-08-31 09:05:00",
                "users_id": "Ana",
                "is_private": 0,
            },
            *self.followups_added,
        ]


@pytest.fixture
def settings() -> Settings:
    return Settings(
        glpi_app_token="app-token",
        glpi_user_token="user-token",
        rmm_webhook_secret="",
        chatwoot_webhook_secret="",
        default_entity_id=0,
        dedupe_ttl_seconds=900,
        sla_poll_enabled=False,
    )


@pytest.fixture
def store() -> InMemoryStore:
    return InMemoryStore()


@pytest.fixture
def glpi() -> FakeGLPI:
    return FakeGLPI()
