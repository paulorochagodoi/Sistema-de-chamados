#!/usr/bin/env bash
# Backup completo do stack: bancos + volumes de dados + objetos do MinIO.
#
#   ./scripts/backup.sh [diretório-destino]
#
# Gera um diretório por data com dumps comprimidos e envia ao bucket
# 'backups' do MinIO quando o mc estiver disponível no container.
# Restauração: ./scripts/restore.sh <diretório>
set -euo pipefail

cd "$(dirname "$0")/.."

COMPOSE="docker compose --env-file .env -f deploy/compose/docker-compose.yml"
DEST_ROOT="${1:-backups}"
STAMP="$(date +%Y%m%d-%H%M%S)"
DEST="$DEST_ROOT/$STAMP"

set -a
# shellcheck disable=SC1091  # o .env não existe no lint, só em execução
source .env
set +a

mkdir -p "$DEST"
echo "==> destino: $DEST"

echo "==> dump do MariaDB (GLPI)"
$COMPOSE exec -T mariadb \
  mariadb-dump --user=root --password="$MARIADB_ROOT_PASSWORD" \
    --single-transaction --routines --triggers --events \
    --databases "${GLPI_DB_NAME:-glpi}" | gzip -9 > "$DEST/mariadb-glpi.sql.gz"

echo "==> dump do PostgreSQL (keycloak, chatwoot, n8n, metabase)"
$COMPOSE exec -T -e PGPASSWORD="$POSTGRES_SUPER_PASSWORD" postgres \
  pg_dumpall --username="${POSTGRES_SUPER_USER:-postgres}" | gzip -9 > "$DEST/postgres-all.sql.gz"

echo "==> volumes de arquivos (GLPI e MeshCentral)"
backup_volume() {
  local volume="$1" arquivo="$2"
  if docker volume inspect "$volume" >/dev/null 2>&1; then
    docker run --rm -v "$volume":/data:ro -v "$PWD/$DEST":/backup alpine:3.21 \
      tar czf "/backup/$arquivo" -C /data .
    echo "    $volume -> $arquivo"
  else
    echo "    $volume ausente (perfil não ativo) — ignorado"
  fi
}
backup_volume itsm_glpi_data glpi-files.tar.gz
backup_volume itsm_meshcentral_data meshcentral-data.tar.gz

echo "==> configuração do stack"
tar czf "$DEST/config.tar.gz" deploy/compose automation .env.example

echo "==> envio para o bucket 'backups' do MinIO"
if docker run --rm \
     --network itsm_data \
     -v "$PWD/$DEST":/backup:ro \
     -e MINIO_ROOT_USER="$MINIO_ROOT_USER" \
     -e MINIO_ROOT_PASSWORD="$MINIO_ROOT_PASSWORD" \
     --entrypoint /bin/sh \
     "${MINIO_IMAGE:-minio/minio:RELEASE.2025-09-07T16-13-09Z}" -c "
       mc alias set itsm http://minio:9000 \"\$MINIO_ROOT_USER\" \"\$MINIO_ROOT_PASSWORD\" >/dev/null &&
       mc cp --recursive /backup/ itsm/backups/$STAMP/
     "; then
  echo "    enviado para itsm/backups/$STAMP/"
else
  echo "    MinIO indisponível — backup permanece apenas local em $DEST" >&2
fi

echo "==> concluído: $(du -sh "$DEST" | cut -f1) em $DEST"
echo "Lembrete: um backup só existe depois de um restore testado (ver docs/05-operacao-runbook.md)."
