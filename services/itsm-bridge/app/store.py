"""Armazenamento de correlação alerta -> chamado, com TTL.

Serve para dois propósitos:

* **Deduplicação**: um monitor que repete o mesmo alerta a cada minuto não
  pode abrir um chamado por minuto.
* **Correlação**: quando o alerta é resolvido, precisamos saber em qual
  chamado registrar o fechamento.

Em produção usa Redis (compartilhado entre réplicas do bridge). Sem Redis
configurado cai para memória — suficiente para dev e para instância única,
mas perde a correlação em um restart.
"""

from __future__ import annotations

import logging
import time
from typing import Protocol

logger = logging.getLogger(__name__)


class CorrelationStore(Protocol):
    async def get(self, key: str) -> int | None: ...
    async def set(self, key: str, ticket_id: int, ttl_seconds: int) -> None: ...
    async def delete(self, key: str) -> None: ...
    async def close(self) -> None: ...


class InMemoryStore:
    """Implementação local com expiração preguiçosa."""

    def __init__(self) -> None:
        self._data: dict[str, tuple[int, float]] = {}

    async def get(self, key: str) -> int | None:
        entry = self._data.get(key)
        if entry is None:
            return None
        ticket_id, expires_at = entry
        if expires_at <= time.monotonic():
            self._data.pop(key, None)
            return None
        return ticket_id

    async def set(self, key: str, ticket_id: int, ttl_seconds: int) -> None:
        self._data[key] = (ticket_id, time.monotonic() + ttl_seconds)

    async def delete(self, key: str) -> None:
        self._data.pop(key, None)

    async def close(self) -> None:
        self._data.clear()


class RedisStore:
    """Implementação compartilhada entre réplicas."""

    def __init__(self, url: str) -> None:
        import redis.asyncio as redis  # import tardio: dependência opcional

        self._redis = redis.from_url(url, decode_responses=True)

    async def get(self, key: str) -> int | None:
        value = await self._redis.get(key)
        return int(value) if value is not None else None

    async def set(self, key: str, ticket_id: int, ttl_seconds: int) -> None:
        await self._redis.set(key, ticket_id, ex=max(ttl_seconds, 1))

    async def delete(self, key: str) -> None:
        await self._redis.delete(key)

    async def close(self) -> None:
        await self._redis.aclose()


def build_store(redis_url: str) -> CorrelationStore:
    if redis_url:
        try:
            return RedisStore(redis_url)
        except Exception as exc:  # pragma: no cover - depende do ambiente
            logger.warning("Redis indisponível (%s); usando store em memória", exc)
    return InMemoryStore()
