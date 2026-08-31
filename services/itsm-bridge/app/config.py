"""Configuração do itsm-bridge, lida do ambiente (prefixo BRIDGE_)."""

from __future__ import annotations

from functools import lru_cache

from pydantic import Field
from pydantic_settings import BaseSettings, SettingsConfigDict


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


@lru_cache
def get_settings() -> Settings:
    return Settings()
