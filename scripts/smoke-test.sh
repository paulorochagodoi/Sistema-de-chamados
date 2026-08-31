#!/usr/bin/env bash
# Verificação pós-deploy: cada serviço do perfil ativo responde?
#
#   ./scripts/smoke-test.sh
#
# Sai com código != 0 se algum teste essencial falhar — serve para CI/CD.
set -uo pipefail

cd "$(dirname "$0")/.."

COMPOSE="docker compose --env-file .env -f deploy/compose/docker-compose.yml"
falhas=0

# shellcheck disable=SC1091
set -a; source .env 2>/dev/null || true; set +a
DOMAIN="${DOMAIN:-itsm.localhost}"

check() {
  local nome="$1"; shift
  printf '%-42s' "$nome"
  if "$@" >/dev/null 2>&1; then
    echo "OK"
  else
    echo "FALHOU"
    falhas=$((falhas + 1))
  fi
}

http() {
  # -k: em dev o Traefik serve certificado auto-assinado
  curl -fsSk --max-time 10 "$@"
}

echo "== containers =="
check "containers do perfil core de pé" \
  bash -c "$COMPOSE --profile core ps --status running --quiet | grep -q ."

echo
echo "== bancos =="
check "MariaDB aceitando conexão" \
  bash -c "$COMPOSE exec -T mariadb healthcheck.sh --connect"
check "PostgreSQL aceitando conexão" \
  bash -c "$COMPOSE exec -T postgres pg_isready -U \"${POSTGRES_SUPER_USER:-postgres}\""
check "Redis respondendo PING" \
  bash -c "$COMPOSE exec -T redis redis-cli -a \"${REDIS_PASSWORD:-}\" ping | grep -q PONG"

echo
echo "== HTTP (via Traefik) =="
check "GLPI responde"          http -o /dev/null "https://glpi.$DOMAIN/"
check "Keycloak responde"      http -o /dev/null "https://sso.$DOMAIN/realms/${KEYCLOAK_REALM:-itsm}/.well-known/openid-configuration"
check "MinIO console responde" http -o /dev/null "https://minio.$DOMAIN/"
check "itsm-bridge healthz"    bash -c "http \"https://bridge.$DOMAIN/healthz\" | grep -q ok"
check "itsm-bridge /metrics"   bash -c "http \"https://bridge.$DOMAIN/metrics\" | grep -q itsm_bridge"

echo
echo "== regras de negócio (itsm-bridge) =="
check "cálculo de SLA" bash -c "
  http -X POST -H 'Content-Type: application/json' \
    -d '{\"opened_at\":\"2026-08-31T17:00:00\",\"response_minutes\":30,\"resolution_minutes\":180}' \
    \"https://bridge.$DOMAIN/api/sla/deadline\" | grep -q '2026-09-01T10:00:00'"
check "prévia de fatura" bash -c "
  http -X POST -H 'Content-Type: application/json' \
    -d '{\"contract\":{\"id\":\"CT-SMOKE\",\"client\":\"Smoke\",\"billing_model\":\"hourly\",\"hourly_rate\":\"100.00\"},
         \"period_start\":\"2026-08-01\",\"period_end\":\"2026-08-31\",
         \"time_entries\":[{\"ticket_id\":1,\"minutes\":60}]}' \
    \"https://bridge.$DOMAIN/api/billing/invoices/preview\" | grep -q '\"total\":\"100.00\"'"

echo
if [ "$falhas" -eq 0 ]; then
  echo "Todos os testes passaram."
else
  echo "$falhas teste(s) falharam." >&2
fi
exit "$falhas"
