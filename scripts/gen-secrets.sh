#!/usr/bin/env bash
# Substitui todos os valores "troque-me-*" do .env por segredos aleatórios.
#
#   cp .env.example .env && ./scripts/gen-secrets.sh
#
# Idempotente: valores já trocados não são mexidos.
set -euo pipefail

ENV_FILE="${1:-.env}"

if [ ! -f "$ENV_FILE" ]; then
  echo "erro: $ENV_FILE não existe. Rode antes: cp .env.example .env" >&2
  exit 1
fi

if ! command -v openssl >/dev/null 2>&1; then
  echo "erro: openssl é necessário para gerar os segredos" >&2
  exit 1
fi

random() { openssl rand -hex "${1:-24}"; }

tmp="$(mktemp)"
trap 'rm -f "$tmp"' EXIT
trocados=0

while IFS= read -r line; do
  if [[ "$line" =~ ^([A-Z0-9_]+)=troque-me ]]; then
    key="${BASH_REMATCH[1]}"
    case "$key" in
      CHATWOOT_SECRET_KEY_BASE) value="$(random 64)" ;;
      N8N_ENCRYPTION_KEY)       value="$(random 32)" ;;
      *)                        value="$(random 24)" ;;
    esac
    printf '%s=%s\n' "$key" "$value" >> "$tmp"
    trocados=$((trocados + 1))
  else
    printf '%s\n' "$line" >> "$tmp"
  fi
done < "$ENV_FILE"

cat "$tmp" > "$ENV_FILE"
chmod 600 "$ENV_FILE"

echo "$trocados segredo(s) gerado(s) em $ENV_FILE (permissão 600)."
echo "Revise DOMAIN, ACME_EMAIL e os tokens do GLPI antes de subir a stack."
