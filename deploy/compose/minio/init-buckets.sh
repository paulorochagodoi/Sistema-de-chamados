#!/bin/sh
# Cria os buckets padrão do sistema. Idempotente — pode rodar a cada `up`.
set -eu

MC="/usr/bin/mc"
ALIAS="itsm"

echo "[minio-init] aguardando o MinIO responder..."
until $MC alias set "$ALIAS" http://minio:9000 "$MINIO_ROOT_USER" "$MINIO_ROOT_PASSWORD" >/dev/null 2>&1; do
  sleep 2
done

create_bucket() {
  bucket="$1"
  if $MC ls "$ALIAS/$bucket" >/dev/null 2>&1; then
    echo "[minio-init] bucket '$bucket' já existe"
  else
    $MC mb "$ALIAS/$bucket"
    echo "[minio-init] bucket '$bucket' criado"
  fi
  # nenhum bucket é público: o acesso é sempre via credencial/URL assinada
  $MC anonymous set none "$ALIAS/$bucket" >/dev/null
}

create_bucket glpi-attachments      # anexos de chamados
create_bucket chatwoot-uploads      # mídia das conversas
create_bucket session-recordings    # gravações de acesso remoto (auditoria)
create_bucket backups               # dumps de banco e backups de config

# Retenção dos backups e gravações (compliance): versiona e expira automaticamente
$MC version enable "$ALIAS/backups" >/dev/null 2>&1 || true
$MC ilm rule add --expire-days 90 "$ALIAS/backups" >/dev/null 2>&1 || true
$MC ilm rule add --expire-days 365 "$ALIAS/session-recordings" >/dev/null 2>&1 || true

echo "[minio-init] concluído"
