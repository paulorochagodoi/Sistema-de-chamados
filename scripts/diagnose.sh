#!/usr/bin/env bash
# Retrato do ambiente para diagnóstico: configuração, containers, rotas e logs.
#
#   ./scripts/diagnose.sh            # tudo
#   ./scripts/diagnose.sh portal     # foca em um serviço
#
# Não altera nada. A saída cabe em uma tela e não mostra segredos.
set -uo pipefail

cd "$(dirname "$0")/.." || exit 1

FOCO="${1:-}"
COMPOSE=(docker compose --env-file .env -f deploy/compose/docker-compose.yml)
PERFIS=(--profile core --profile rmm --profile omnichannel --profile automation
        --profile bi --profile observability)

titulo() { printf '\n\033[1;36m== %s\033[0m\n' "$*"; }
item()   { printf '  %s\n' "$*"; }

if [ ! -f .env ]; then
  echo "erro: .env não existe neste diretório ($PWD)" >&2
  exit 1
fi

DOMAIN="$(sed -n 's/^DOMAIN=//p' .env | head -1)"
DOMAIN="${DOMAIN:-itsm.localhost}"

titulo "Configuração"
item "diretório .......... $PWD"
item "DOMAIN ............. $DOMAIN"
item "PORTAL_PROFILES .... $(sed -n 's/^PORTAL_PROFILES=//p' .env | head -1)"
portal_secret="$(sed -n 's/^PORTAL_SECRET=//p' .env | head -1)"
case "$portal_secret" in
  "")           item "PORTAL_SECRET ...... ausente (sessões do painel caem a cada restart)" ;;
  troque-me*)   item "PORTAL_SECRET ...... placeholder — rode ./scripts/gen-secrets.sh" ;;
  *)            item "PORTAL_SECRET ...... definido" ;;
esac
item "GLPI_APP_TOKEN ..... $([ -n "$(sed -n 's/^GLPI_APP_TOKEN=//p' .env | head -1)" ] && echo definido || echo ausente)"
item "GLPI_USER_TOKEN .... $([ -n "$(sed -n 's/^GLPI_USER_TOKEN=//p' .env | head -1)" ] && echo definido || echo ausente)"

titulo "Endereços (derivados do DOMAIN)"
item "painel ............. https://$DOMAIN/  e  https://portal.$DOMAIN/"
item "GLPI ............... https://glpi.$DOMAIN/"
item "bridge ............. https://bridge.$DOMAIN/docs"

titulo "Containers"
if ! docker info >/dev/null 2>&1; then
  item "sem acesso ao daemon do Docker — rode com sudo"
  exit 1
fi
containers="$("${COMPOSE[@]}" "${PERFIS[@]}" ps --format '{{.Service}} → {{.State}} ({{.Status}})' 2>/dev/null)"
if [ -n "$containers" ]; then
  printf '%s\n' "$containers" | sort | sed 's/^/  /'
else
  item "(nenhum container de pé)"
fi

titulo "Imagens próprias"
for imagem in itsm-portal:local itsm-bridge:local; do
  if docker image inspect "$imagem" >/dev/null 2>&1; then
    item "$imagem ... construída ($(docker image inspect -f '{{.Created}}' "$imagem" | cut -c1-19))"
  else
    item "$imagem ... NÃO existe — rode: docker compose ... build portal itsm-bridge"
  fi
done

titulo "Resposta HTTP (via Traefik, certificado auto-assinado)"
codigo() {
  local http
  http="$(curl -ksS -o /dev/null -w '%{http_code}' --max-time 10 "$1" 2>/dev/null)"
  case "$http" in
    ""|000) echo "sem resposta (nada escutando neste host)" ;;
    *)      echo "$http" ;;
  esac
}
item "https://$DOMAIN/ .................. $(codigo "https://$DOMAIN/")"
item "https://portal.$DOMAIN/ ........... $(codigo "https://portal.$DOMAIN/")"
item "https://portal.$DOMAIN/healthz .... $(codigo "https://portal.$DOMAIN/healthz")"
item "https://portal.$DOMAIN/api/portal/services (401 = correto) ... $(codigo "https://portal.$DOMAIN/api/portal/services")"
item "https://glpi.$DOMAIN/ ............. $(codigo "https://glpi.$DOMAIN/")"
item "https://bridge.$DOMAIN/healthz .... $(codigo "https://bridge.$DOMAIN/healthz")"

titulo "Portal por dentro da rede (sem passar pelo Traefik)"
if docker ps --format '{{.Names}}' | grep -q 'portal'; then
  item "nginx -t ......... $("${COMPOSE[@]}" exec -T portal nginx -t 2>&1 | tail -1)"
  item "GET /healthz ..... $("${COMPOSE[@]}" exec -T portal wget -qO- http://127.0.0.1/healthz 2>&1 | tail -1)"
  # Container unhealthy é motivo suficiente para o Traefik não registrar a rota:
  # ele filtra containers que não estão saudáveis, e a requisição vira 404.
  cid="$(docker ps -q --filter 'label=com.docker.compose.service=portal' | head -1)"
  saude="$(docker inspect --format '{{if .State.Health}}{{.State.Health.Status}}{{else}}sem healthcheck{{end}}' "$cid" 2>/dev/null)"
  item "healthcheck ...... ${saude:-desconhecido}"
  if [ "$saude" = "unhealthy" ]; then
    ultima="$(docker inspect --format '{{range .State.Health.Log}}{{.Output}}{{end}}' "$cid" 2>/dev/null |
      tr -d '\r' | grep -v '^[[:space:]]*$' | tail -1)"
    item "última saída ..... ${ultima:0:120}"
    item "atenção .......... o Traefik não roteia container unhealthy: por isso 404 e não 502"
  fi
else
  item "container do portal não está de pé"
fi

titulo "Erros recentes do Traefik"
"${COMPOSE[@]}" logs --tail=200 traefik 2>/dev/null | grep -iE "ERR|error=" | tail -8 |
  sed 's/^/  /' || item "(sem erros)"

for servico in ${FOCO:-portal itsm-bridge}; do
  titulo "Logs de $servico (últimas 25 linhas)"
  "${COMPOSE[@]}" logs --tail=25 "$servico" 2>&1 | sed 's/^/  /'
done

printf '\n\033[1;33mEnvie esta saída inteira para diagnóstico.\033[0m\n'
