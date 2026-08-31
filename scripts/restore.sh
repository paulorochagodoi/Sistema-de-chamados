#!/usr/bin/env bash
# Restauração a partir de um diretório gerado por scripts/backup.sh.
#
#   ./scripts/restore.sh backups/20260831-030000
#
# DESTRUTIVO: sobrescreve os bancos e os volumes de arquivos.
# Use em ambiente de teste para o restore drill trimestral.
set -euo pipefail

cd "$(dirname "$0")/.."

SRC="${1:-}"
if [ -z "$SRC" ] || [ ! -d "$SRC" ]; then
  echo "uso: $0 <diretório-do-backup>" >&2
  exit 1
fi

COMPOSE="docker compose --env-file .env -f deploy/compose/docker-compose.yml"

set -a
# shellcheck disable=SC1091  # o .env não existe no lint, só em execução
source .env
set +a

echo "ATENÇÃO: isto sobrescreve os dados atuais do stack."
read -r -p "Digite 'restaurar' para confirmar: " confirm
[ "$confirm" = "restaurar" ] || { echo "cancelado"; exit 1; }

echo "==> parando as aplicações (bancos seguem de pé)"
$COMPOSE --profile core --profile omnichannel --profile automation --profile bi stop \
  glpi glpi-cron itsm-bridge keycloak chatwoot-web chatwoot-worker n8n n8n-worker metabase \
  2>/dev/null || true

if [ -f "$SRC/mariadb-glpi.sql.gz" ]; then
  echo "==> restaurando MariaDB"
  gunzip -c "$SRC/mariadb-glpi.sql.gz" | \
    $COMPOSE exec -T mariadb mariadb --user=root --password="$MARIADB_ROOT_PASSWORD"
fi

if [ -f "$SRC/postgres-all.sql.gz" ]; then
  echo "==> restaurando PostgreSQL"
  gunzip -c "$SRC/postgres-all.sql.gz" | \
    $COMPOSE exec -T -e PGPASSWORD="$POSTGRES_SUPER_PASSWORD" postgres \
      psql --username="${POSTGRES_SUPER_USER:-postgres}" --dbname postgres
fi

restore_volume() {
  local volume="$1" arquivo="$2"
  [ -f "$SRC/$arquivo" ] || return 0
  docker volume create "$volume" >/dev/null
  docker run --rm -v "$volume":/data -v "$PWD/$SRC":/backup:ro alpine:3.21 \
    sh -c "rm -rf /data/* && tar xzf /backup/$arquivo -C /data"
  echo "    $arquivo -> $volume"
}
echo "==> restaurando volumes de arquivos"
restore_volume itsm_glpi_data glpi-files.tar.gz
restore_volume itsm_meshcentral_data meshcentral-data.tar.gz

echo "==> subindo as aplicações"
$COMPOSE --profile core up -d

echo "==> restauração concluída. Valide:"
echo "    1. login no GLPI e abertura de um chamado"
echo "    2. anexos antigos abrindo normalmente"
echo "    3. ./scripts/smoke-test.sh"
