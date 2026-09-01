#!/usr/bin/env bash
# Configura o .env da stack: domínio, e-mail do ACME, fuso, perfis do painel,
# tokens do GLPI e segredos.
#
#   ./scripts/configure.sh                       # pergunta o que falta
#   ./scripts/configure.sh --domain itsm.acme.com --email ti@acme.com --yes
#
# Idempotente: rodar de novo só ajusta o que você passar (ou confirmar).
set -euo pipefail

cd "$(dirname "$0")/.."

ENV_FILE=".env"
EXAMPLE_FILE=".env.example"
ASSUME_YES=0
DOMAIN_ARG=""
EMAIL_ARG=""
TZ_ARG=""
PROFILES_ARG=""
GLPI_APP_TOKEN_ARG=""
GLPI_USER_TOKEN_ARG=""
RUSTDESK_ARG=""
REGENERATE=0

uso() {
  cat <<'TXT'
Uso: ./scripts/configure.sh [opções]

  --domain <dom>          Domínio da stack (ex.: itsm.acme.com)
  --email <e-mail>        E-mail do Let's Encrypt (ACME)
  --timezone <tz>         Fuso horário (ex.: America/Sao_Paulo)
  --profiles <lista>      Perfis ativos, separados por vírgula
                          (core,rmm,omnichannel,automation,bi,observability)
  --glpi-app-token <tok>  App-Token da API do GLPI
  --glpi-user-token <tok> User-Token da API do GLPI
  --rustdesk-host <host>  Host público do relay RustDesk
  --regenerate-secrets    Troca TODOS os segredos (invalida sessões e dados
                          cifrados do n8n — use só em instalação nova)
  --env-file <caminho>    Arquivo de destino (padrão: .env)
  -y, --yes               Não pergunta nada; mantém o que não foi passado
  -h, --help              Esta ajuda
TXT
}

while [ $# -gt 0 ]; do
  case "$1" in
    --domain)             DOMAIN_ARG="${2:?}"; shift 2 ;;
    --email)              EMAIL_ARG="${2:?}"; shift 2 ;;
    --timezone)           TZ_ARG="${2:?}"; shift 2 ;;
    --profiles)           PROFILES_ARG="${2:?}"; shift 2 ;;
    --glpi-app-token)     GLPI_APP_TOKEN_ARG="${2:?}"; shift 2 ;;
    --glpi-user-token)    GLPI_USER_TOKEN_ARG="${2:?}"; shift 2 ;;
    --rustdesk-host)      RUSTDESK_ARG="${2:?}"; shift 2 ;;
    --env-file)           ENV_FILE="${2:?}"; shift 2 ;;
    --regenerate-secrets) REGENERATE=1; shift ;;
    -y|--yes)             ASSUME_YES=1; shift ;;
    -h|--help)            uso; exit 0 ;;
    *) echo "opção desconhecida: $1" >&2; uso >&2; exit 2 ;;
  esac
done

info() { printf '\033[36m==>\033[0m %s\n' "$*"; }
aviso() { printf '\033[33m!!\033[0m %s\n' "$*" >&2; }
erro() { printf '\033[31merro:\033[0m %s\n' "$*" >&2; exit 1; }

# --- leitura/escrita do .env ------------------------------------------------
get_env() {
  # imprime o valor atual da chave (vazio se ausente)
  sed -n "s/^$1=//p" "$ENV_FILE" | head -1
}

set_env() {
  # substitui a linha da chave preservando a ordem; acrescenta se não existir.
  # Feito com read/print para não depender de escape de sed no valor.
  local key="$1" value="$2" tmp found=0
  tmp="$(mktemp)"
  while IFS= read -r line || [ -n "$line" ]; do
    if [ "$found" -eq 0 ] && [[ "$line" == "$key="* ]]; then
      printf '%s=%s\n' "$key" "$value" >> "$tmp"
      found=1
    else
      printf '%s\n' "$line" >> "$tmp"
    fi
  done < "$ENV_FILE"
  [ "$found" -eq 1 ] || printf '%s=%s\n' "$key" "$value" >> "$tmp"
  cat "$tmp" > "$ENV_FILE"
  rm -f "$tmp"
}

perguntar() {
  # perguntar <descrição> <valor-atual> <argumento>; ecoa o valor escolhido
  local descricao="$1" atual="$2" argumento="$3" resposta
  if [ -n "$argumento" ]; then
    printf '%s' "$argumento"
    return
  fi
  if [ "$ASSUME_YES" -eq 1 ] || [ ! -t 0 ]; then
    printf '%s' "$atual"
    return
  fi
  read -r -p "$descricao [$atual]: " resposta </dev/tty || resposta=""
  printf '%s' "${resposta:-$atual}"
}

# --- 1. arquivo base --------------------------------------------------------
if [ ! -f "$ENV_FILE" ]; then
  [ -f "$EXAMPLE_FILE" ] || erro "$EXAMPLE_FILE não encontrado — rode a partir da raiz do repositório"
  cp "$EXAMPLE_FILE" "$ENV_FILE"
  info "$ENV_FILE criado a partir de $EXAMPLE_FILE"
fi

# --- 2. segredos ------------------------------------------------------------
SEGREDOS="MARIADB_ROOT_PASSWORD GLPI_DB_PASSWORD POSTGRES_SUPER_PASSWORD
KEYCLOAK_DB_PASSWORD CHATWOOT_DB_PASSWORD N8N_DB_PASSWORD METABASE_DB_PASSWORD
REDIS_PASSWORD RABBITMQ_PASSWORD MINIO_ROOT_PASSWORD KEYCLOAK_ADMIN_PASSWORD
GRAFANA_ADMIN_PASSWORD CHATWOOT_SECRET_KEY_BASE N8N_ENCRYPTION_KEY PORTAL_SECRET
MESHCENTRAL_BACKUPS_PW BRIDGE_RMM_WEBHOOK_SECRET BRIDGE_CHATWOOT_WEBHOOK_SECRET"

if [ "$REGENERATE" -eq 1 ]; then
  aviso "trocando TODOS os segredos: bancos já criados deixarão de abrir com as senhas novas"
  # marca cada segredo como pendente; quem sorteia os valores é o gen-secrets.sh
  for chave in $SEGREDOS; do
    set_env "$chave" "troque-me-regenerado"
  done
fi

./scripts/gen-secrets.sh "$ENV_FILE"

# Os segredos de webhook nascem vazios no exemplo (validação desligada). Em uma
# instalação nova vale gerá-los: sem eles qualquer um posta um alerta.
for chave in BRIDGE_RMM_WEBHOOK_SECRET BRIDGE_CHATWOOT_WEBHOOK_SECRET; do
  if [ -z "$(get_env "$chave")" ]; then
    set_env "$chave" "$(openssl rand -hex 24)"
    info "$chave gerado (configure o mesmo valor no emissor do webhook)"
  fi
done

# --- 3. parâmetros do ambiente ---------------------------------------------
dominio="$(perguntar 'Domínio da stack' "$(get_env DOMAIN)" "$DOMAIN_ARG")"
case "$dominio" in
  *[![:alnum:].-]*|"") erro "domínio inválido: '$dominio'" ;;
esac
set_env DOMAIN "$dominio"

email="$(perguntar 'E-mail para o Let'\''s Encrypt' "$(get_env ACME_EMAIL)" "$EMAIL_ARG")"
case "$email" in
  *@*.*) : ;;
  *) aviso "e-mail '$email' não parece válido; o Let's Encrypt vai recusar" ;;
esac
set_env ACME_EMAIL "$email"

fuso="$(perguntar 'Fuso horário' "$(get_env TZ)" "$TZ_ARG")"
if [ -n "$fuso" ] && [ ! -f "/usr/share/zoneinfo/$fuso" ]; then
  aviso "fuso '$fuso' não existe neste host; verifique com: timedatectl list-timezones"
fi
set_env TZ "$fuso"

perfis="$(perguntar 'Perfis ativos (menu do painel)' "$(get_env PORTAL_PROFILES)" "$PROFILES_ARG")"
for perfil in ${perfis//,/ }; do
  case "$perfil" in
    core|rmm|omnichannel|automation|bi|observability) : ;;
    *) erro "perfil desconhecido: '$perfil'" ;;
  esac
done
case ",$perfis," in
  *,core,*) : ;;
  *) erro "o perfil 'core' é obrigatório (portal, GLPI, bancos e bridge vivem nele)" ;;
esac
set_env PORTAL_PROFILES "$perfis"

if [ -n "$RUSTDESK_ARG" ] || [ "$ASSUME_YES" -eq 0 ]; then
  relay="$(perguntar 'Host público do relay RustDesk' "$(get_env RUSTDESK_RELAY_HOST)" "$RUSTDESK_ARG")"
  set_env RUSTDESK_RELAY_HOST "$relay"
fi

# --- 4. tokens do GLPI ------------------------------------------------------
# Só existem depois que o GLPI subiu (Configurar > Geral > API): por isso são
# opcionais aqui e podem ser preenchidos depois, com um restart do bridge.
[ -n "$GLPI_APP_TOKEN_ARG" ] && set_env GLPI_APP_TOKEN "$GLPI_APP_TOKEN_ARG"
[ -n "$GLPI_USER_TOKEN_ARG" ] && set_env GLPI_USER_TOKEN "$GLPI_USER_TOKEN_ARG"

chmod 600 "$ENV_FILE"

# --- 5. resumo --------------------------------------------------------------
echo
info "configuração gravada em $ENV_FILE"
cat <<TXT

  Domínio ........ $dominio
  ACME e-mail .... $email
  Fuso ........... $fuso
  Perfis ......... $perfis

  Painel ......... https://$dominio/  (também em https://portal.$dominio/)
  GLPI ........... https://glpi.$dominio/
  SSO (Keycloak) . https://sso.$dominio/
  API (bridge) ... https://bridge.$dominio/docs

TXT

if [ -z "$(get_env GLPI_APP_TOKEN)" ] || [ -z "$(get_env GLPI_USER_TOKEN)" ]; then
  aviso "tokens do GLPI ainda não definidos: o painel só lista chamados depois deles."
  cat <<'TXT'
    1. Abra o GLPI > Configurar > Geral > API
    2. Habilite a API REST e o login com credenciais
    3. Crie um cliente de API (App-Token) e um token de usuário (User-Token)
    4. Rode: ./scripts/configure.sh --glpi-app-token <tok> --glpi-user-token <tok> --yes
    5. Aplique no bridge: make reload SERVICE=itsm-bridge
       (é `up -d`, não `restart`: variável nova só entra recriando o container)
TXT
fi
