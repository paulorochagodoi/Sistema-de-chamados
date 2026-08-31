"""Configuração do itsm-bridge, lida do ambiente (prefixo BRIDGE_)."""

from __future__ import annotations

import secrets
from functools import lru_cache

from pydantic import Field
from pydantic_settings import BaseSettings, SettingsConfigDict

# Usada quando BRIDGE_PORTAL_SECRET não é definida (ver portal_signing_key).
_EPHEMERAL_PORTAL_SECRET = secrets.token_urlsafe(48)


class Settings(BaseSettings):
    model_config = SettingsConfigDict(
        env_prefix="BRIDGE_",
        env_file=".env",
        extra="ignore",
    )

    log_level: str = "INFO"

    # --- GLPI -------------------------------------------------------------
    glpi_api_url: str = "http://glpi/apirest.php"
    glpi_app_token: str = ""
    glpi_user_token: str = ""
    glpi_timeout_seconds: float = 15.0

    # --- Webhooks ---------------------------------------------------------
    # Segredo HMAC-SHA256. Vazio desabilita a validação (apenas desenvolvimento).
    rmm_webhook_secret: str = ""
    chatwoot_webhook_secret: str = ""

    # --- Comportamento ----------------------------------------------------
    default_entity_id: int = 0
    # janela em que um alerta repetido não abre novo chamado
    dedupe_ttl_seconds: int = 900
    # por quanto tempo uma conversa do Chatwoot continua alimentando o mesmo chamado
    conversation_ttl_seconds: int = 604_800  # 7 dias
    redis_url: str = ""

    # --- Painel unificado (portal) ---------------------------------------
    # Domínio raiz da stack; as URLs públicas dos serviços derivam dele
    # (glpi.<domínio>, sso.<domínio>, ...).
    portal_domain: str = "itsm.localhost"
    # Perfis do Compose que o operador subiu — filtra o catálogo do painel.
    portal_profiles: str = "core,rmm,omnichannel,automation,bi,observability"
    # Chave de assinatura dos tokens de sessão do painel. Vazia gera uma chave
    # efêmera no processo: funciona em dev, mas invalida sessões a cada restart
    # e não serve com mais de uma réplica.
    portal_secret: str = ""
    portal_session_minutes: int = 480
    # Aceitar identidade repassada por um proxy de SSO (oauth2-proxy, Authelia).
    # Só ligue quando o painel estiver atrás desse proxy: o cabeçalho é
    # confiável apenas se ninguém além do proxy alcançar o bridge.
    portal_trust_forwarded_auth: bool = False
    portal_forwarded_user_header: str = "X-Auth-Request-User"
    portal_forwarded_name_header: str = "X-Auth-Request-Preferred-Username"
    # Sondagem de disponibilidade dos serviços mostrada no painel
    portal_status_ttl_seconds: int = 15
    portal_probe_timeout_seconds: float = 3.0
    portal_page_size: int = 50

    # Coletor que alimenta a métrica itsm_tickets_sla_at_risk
    sla_poll_interval_seconds: int = 300
    sla_at_risk_threshold_minutes: int = 60
    sla_poll_enabled: bool = True

    # Prazos padrão por urgência (minutos), usados quando o contrato do
    # cliente não define uma política própria.
    default_response_minutes: dict[str, int] = Field(
        default_factory=lambda: {
            "critical": 15,
            "high": 30,
            "warning": 120,
            "low": 480,
            "info": 480,
        }
    )
    default_resolution_minutes: dict[str, int] = Field(
        default_factory=lambda: {
            "critical": 240,
            "high": 480,
            "warning": 1440,
            "low": 2880,
            "info": 4320,
        }
    )

    @property
    def glpi_configured(self) -> bool:
        return bool(self.glpi_app_token and self.glpi_user_token)

    @property
    def portal_enabled_profiles(self) -> set[str]:
        return {item.strip() for item in self.portal_profiles.split(",") if item.strip()}

    @property
    def portal_signing_key(self) -> str:
        """Chave HMAC dos tokens do painel, com fallback efêmero em dev."""
        return self.portal_secret or _EPHEMERAL_PORTAL_SECRET


@lru_cache
def get_settings() -> Settings:
    return Settings()
