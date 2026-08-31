"""Autenticação do painel unificado.

Duas formas de entrar, nesta ordem de precedência:

1. **Token do painel** — o formulário de login valida usuário e senha no
   próprio GLPI (``initSession`` com Basic auth) e o bridge devolve um JWT
   HS256 curto, guardado pelo navegador. Não há base de usuários paralela:
   quem entra no GLPI entra no painel, com o mesmo perfil.
2. **Identidade repassada por um proxy de SSO** (oauth2-proxy, Authelia) à
   frente do painel, no cabeçalho ``X-Auth-Request-User``. Só é aceita com
   ``BRIDGE_PORTAL_TRUST_FORWARDED_AUTH=true``, porque um cabeçalho é confiável
   apenas quando ninguém além do proxy alcança o bridge.

As operações no GLPI continuam usando o token de serviço da stack: o usuário
autenticado identifica *quem* pediu (e vira solicitante do chamado aberto pelo
painel), não *com quais* credenciais o bridge fala com o GLPI.
"""

from __future__ import annotations

import base64
import logging
from datetime import UTC, datetime, timedelta

import httpx
import jwt

from .models import PortalUser

logger = logging.getLogger(__name__)

ALGORITHM = "HS256"
ISSUER = "itsm-bridge"


class AuthError(Exception):
    """Credenciais inválidas ou token não confiável."""


def issue_token(user: PortalUser, secret: str, ttl_minutes: int) -> tuple[str, int]:
    """Devolve o JWT do painel e sua validade em segundos."""
    ttl = timedelta(minutes=max(ttl_minutes, 1))
    now = datetime.now(UTC)
    payload = {
        "iss": ISSUER,
        "sub": str(user.id),
        "iat": int(now.timestamp()),
        "exp": int((now + ttl).timestamp()),
        "username": user.username,
        "name": user.full_name,
        "profile": user.profile,
        "src": user.source,
    }
    return jwt.encode(payload, secret, algorithm=ALGORITHM), int(ttl.total_seconds())


def decode_token(token: str, secret: str) -> PortalUser:
    try:
        payload = jwt.decode(token, secret, algorithms=[ALGORITHM], issuer=ISSUER)
    except jwt.ExpiredSignatureError as exc:
        raise AuthError("sessão expirada") from exc
    except jwt.InvalidTokenError as exc:
        raise AuthError("token inválido") from exc

    source = payload.get("src")
    return PortalUser(
        id=int(payload.get("sub") or 0),
        username=payload.get("username", ""),
        full_name=payload.get("name", ""),
        profile=payload.get("profile", ""),
        source=source if source in ("glpi", "sso") else "glpi",
    )


async def authenticate_with_glpi(
    username: str,
    password: str,
    api_url: str,
    app_token: str,
    client: httpx.AsyncClient,
    timeout: float = 15.0,
) -> PortalUser:
    """Valida usuário e senha no GLPI e devolve a identidade da sessão.

    Exige ``Configurar > Geral > API > Habilitar login com credenciais`` ligado
    no GLPI — ver docs/04-integracoes.md.
    """
    base_url = api_url.rstrip("/")
    basic = base64.b64encode(f"{username}:{password}".encode()).decode()
    headers = {
        "Content-Type": "application/json",
        "App-Token": app_token,
        "Authorization": f"Basic {basic}",
    }

    try:
        response = await client.get(f"{base_url}/initSession", headers=headers, timeout=timeout)
    except httpx.HTTPError as exc:
        raise AuthError(f"GLPI inacessível: {exc}") from exc

    if response.status_code in (400, 401):
        raise AuthError("usuário ou senha inválidos")
    if response.status_code != 200:
        raise AuthError(f"GLPI recusou o login (HTTP {response.status_code})")

    session_token = response.json().get("session_token")
    if not session_token:
        raise AuthError("GLPI não devolveu session_token")

    session_headers = {
        "Content-Type": "application/json",
        "App-Token": app_token,
        "Session-Token": session_token,
    }
    try:
        full = await client.get(
            f"{base_url}/getFullSession", headers=session_headers, timeout=timeout
        )
        session = full.json().get("session", {}) if full.status_code == 200 else {}
    except (httpx.HTTPError, ValueError) as exc:  # sessão iniciada: seguimos com o mínimo
        logger.warning("getFullSession falhou após login de %s: %s", username, exc)
        session = {}
    finally:
        try:
            await client.get(f"{base_url}/killSession", headers=session_headers, timeout=timeout)
        except httpx.HTTPError as exc:
            logger.warning("falha ao encerrar sessão de login do GLPI: %s", exc)

    profile = session.get("glpiactiveprofile") or {}
    return PortalUser(
        id=int(session.get("glpiID") or 0),
        username=str(session.get("glpiname") or username),
        full_name=str(session.get("glpifriendlyname") or session.get("glpirealname") or username),
        profile=str(profile.get("name") or ""),
        source="glpi",
    )
