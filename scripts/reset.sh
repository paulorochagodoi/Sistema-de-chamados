#!/usr/bin/env bash
# Apaga a instalação: containers, redes, volumes (dados!) e configuração.
#
#   ./scripts/reset.sh                 # containers, redes, volumes e .env
#   ./scripts/reset.sh --keep-env      # preserva o .env (mesmos segredos ao subir de novo)
#   ./scripts/reset.sh --keep-volumes  # preserva os dados
#   sudo ./scripts/reset.sh --all -y   # tudo, inclusive imagens e artefatos do host
#
# O escopo é sempre o projeto `itsm` deste repositório: nada de `docker system
# prune`, que levaria junto containers de outros projetos do host.
set -euo pipefail

cd "$(dirname "$0")/.."

REPO_DIR="$PWD"
PROJETO="itsm"
COMPOSE_FILE="deploy/compose/docker-compose.yml"

KEEP_ENV=0
KEEP_VOLUMES=0
COM_IMAGENS=0
COM_HOST=0
COM_FIREWALL=0
COM_BACKUPS=0
ASSUME_YES=0
DRY_RUN=0

uso() {
  cat <<'TXT'
Uso: ./scripts/reset.sh [opções]

Por padrão remove os containers, as redes, os volumes (TODOS OS DADOS) e o .env
do projeto itsm.

  --keep-env        Preserva o .env (segredos e domínio continuam valendo)
  --keep-volumes    Preserva os volumes: bancos, anexos e configuração dos apps
  --images          Remove também as imagens usadas pela stack
  --host            Remove o que o instalador criou no host: itsm.service,
                    /etc/cron.d/itsm-backup e /etc/sysctl.d/99-itsm.conf (root)
  --firewall        Remove as regras de UFW da stack (80, 443 e RustDesk).
                    Nunca mexe na regra de SSH (root)
  --backups         Apaga também o diretório backups/
  --all             Tudo acima (mantém apenas o repositório e o Docker Engine)
  --dry-run         Mostra o que seria feito, sem apagar nada
  -y, --yes         Não pede confirmação
  -h, --help        Esta ajuda

O Docker Engine, o /etc/docker/daemon.json e o código do repositório nunca são
removidos — o daemon é compartilhado com outras stacks do host.
TXT
}

while [ $# -gt 0 ]; do
  case "$1" in
    --keep-env)      KEEP_ENV=1; shift ;;
    --keep-volumes)  KEEP_VOLUMES=1; shift ;;
    --images)        COM_IMAGENS=1; shift ;;
    --host)          COM_HOST=1; shift ;;
    --firewall)      COM_FIREWALL=1; shift ;;
    --backups)       COM_BACKUPS=1; shift ;;
    --all)           COM_IMAGENS=1; COM_HOST=1; COM_FIREWALL=1; COM_BACKUPS=1; shift ;;
    --dry-run)       DRY_RUN=1; shift ;;
    -y|--yes)        ASSUME_YES=1; shift ;;
    -h|--help)       uso; exit 0 ;;
    *) echo "opção desconhecida: $1" >&2; uso >&2; exit 2 ;;
  esac
done

etapa() { printf '\n\033[1;36m==> %s\033[0m\n' "$*"; }
info()  { printf '    %s\n' "$*"; }
aviso() { printf '\033[33m !! %s\033[0m\n' "$*" >&2; }
erro()  { printf '\033[31merro: %s\033[0m\n' "$*" >&2; exit 1; }

executar() {
  if [ "$DRY_RUN" -eq 1 ]; then
    printf '    [dry-run] %s\n' "$*"
  else
    "$@" >/dev/null 2>&1 || true
  fi
}

command -v docker >/dev/null 2>&1 || erro "docker não encontrado neste host"
docker info >/dev/null 2>&1 || erro "sem acesso ao daemon do Docker — rode com sudo"

# --- 1. inventário ----------------------------------------------------------
# Filtrar pelo label do projeto pega tudo o que o Compose criou, mesmo que o
# .env tenha sumido ou o docker-compose.yml tenha mudado desde a subida.
por_projeto() {
  docker "$1" ls -q --filter "label=com.docker.compose.project=$PROJETO" 2>/dev/null
}

containers="$(docker ps -aq --filter "label=com.docker.compose.project=$PROJETO" 2>/dev/null || true)"
volumes="$(por_projeto volume || true)"
redes="$(docker network ls -q --filter "label=com.docker.compose.project=$PROJETO" 2>/dev/null || true)"

qtd() {
  if [ -z "$1" ]; then
    echo 0
    return 0
  fi
  printf '%s\n' "$1" | grep -c . || true
}

etapa "O que será removido"
info "containers do projeto $PROJETO .... $(qtd "$containers")"
info "redes do projeto $PROJETO .......... $(qtd "$redes")"
if [ "$KEEP_VOLUMES" -eq 1 ]; then
  info "volumes ......................... preservados (--keep-volumes)"
else
  info "volumes (TODOS OS DADOS) ........ $(qtd "$volumes")"
fi
if [ "$KEEP_ENV" -eq 1 ]; then
  info ".env ............................. preservado (--keep-env)"
elif [ -f .env ]; then
  info ".env ............................. será apagado"
else
  info ".env ............................. não existe"
fi
[ "$COM_IMAGENS" -eq 1 ]  && info "imagens da stack ................. serão removidas"
[ "$COM_HOST" -eq 1 ]     && info "host ............................. itsm.service, cron de backup, sysctl"
[ "$COM_FIREWALL" -eq 1 ] && info "firewall ......................... regras 80, 443 e RustDesk (SSH intacto)"
[ "$COM_BACKUPS" -eq 1 ]  && info "backups/ ......................... será apagado"

if [ "$KEEP_VOLUMES" -eq 0 ] && [ -n "$volumes" ]; then
  echo
  aviso "os volumes guardam o banco do GLPI, os anexos do MinIO e a configuração"
  aviso "do Keycloak, Chatwoot e n8n. Isso não tem desfazer."
  aviso "Se quiser guardar antes: ./scripts/backup.sh"
fi

# --- 2. confirmação ---------------------------------------------------------
if [ "$DRY_RUN" -eq 0 ] && [ "$ASSUME_YES" -eq 0 ]; then
  if [ ! -t 0 ]; then
    erro "sem terminal para confirmar; use -y se tem certeza"
  fi
  echo
  read -r -p "Digite APAGAR para confirmar: " resposta </dev/tty || resposta=""
  [ "$resposta" = "APAGAR" ] || erro "cancelado"
fi

# --- 3. containers, redes e volumes ----------------------------------------
etapa "Parando e removendo containers"
# O caminho normal é pelo Compose (respeita ordem e remove órfãos); ele precisa
# de um env file válido, então caímos no .env.example quando o .env já não está.
ENV_PARA_COMPOSE=".env"
[ -f .env ] || ENV_PARA_COMPOSE=".env.example"
if [ -f "$ENV_PARA_COMPOSE" ]; then
  down_args=(--env-file "$ENV_PARA_COMPOSE" -f "$COMPOSE_FILE"
             --profile core --profile rmm --profile omnichannel
             --profile automation --profile bi --profile observability
             down --remove-orphans)
  [ "$KEEP_VOLUMES" -eq 0 ] && down_args+=(--volumes)
  executar docker compose "${down_args[@]}"
fi

# Rede de segurança: o que o Compose não alcançou (container renomeado, arquivo
# alterado desde a subida) ainda tem o label do projeto.
if [ -n "$containers" ]; then
  # shellcheck disable=SC2086  # a lista de ids é separada por espaço de propósito
  executar docker rm -f $containers
fi
info "containers: $(qtd "$containers")"

if [ "$KEEP_VOLUMES" -eq 0 ] && [ -n "$volumes" ]; then
  etapa "Removendo volumes"
  # shellcheck disable=SC2086
  executar docker volume rm $volumes
  info "volumes: $(qtd "$volumes")"
fi

if [ -n "$redes" ]; then
  etapa "Removendo redes"
  # shellcheck disable=SC2086
  executar docker network rm $redes
  info "redes: $(qtd "$redes")"
fi

# --- 4. imagens -------------------------------------------------------------
if [ "$COM_IMAGENS" -eq 1 ]; then
  etapa "Removendo imagens da stack"
  imagens="itsm-portal:local itsm-bridge:local"
  if [ -f "$ENV_PARA_COMPOSE" ]; then
    imagens="$imagens $(docker compose --env-file "$ENV_PARA_COMPOSE" -f "$COMPOSE_FILE" \
      --profile core --profile rmm --profile omnichannel --profile automation \
      --profile bi --profile observability config --images 2>/dev/null | sort -u | tr '\n' ' ')"
  fi
  for imagem in $imagens; do
    # imagem em uso por outra stack faz o rmi falhar — e é isso que queremos
    executar docker rmi "$imagem"
  done
  info "imagens tratadas (as em uso por outros projetos foram mantidas)"
fi

# --- 5. configuração local --------------------------------------------------
etapa "Configuração local"
if [ "$KEEP_ENV" -eq 0 ] && [ -f .env ]; then
  executar rm -f .env
  info ".env removido"
else
  info ".env mantido"
fi

if [ "$COM_BACKUPS" -eq 1 ] && [ -d backups ]; then
  executar rm -rf backups
  info "backups/ removido"
fi

# --- 6. artefatos do host ---------------------------------------------------
if [ "$COM_HOST" -eq 1 ] || [ "$COM_FIREWALL" -eq 1 ]; then
  if [ "$(id -u)" -ne 0 ]; then
    aviso "--host e --firewall exigem root; pulando (rode com sudo)"
  else
    if [ "$COM_HOST" -eq 1 ]; then
      etapa "Artefatos do host"
      if [ -f /etc/systemd/system/itsm.service ]; then
        executar systemctl disable --now itsm.service
        executar rm -f /etc/systemd/system/itsm.service
        executar systemctl daemon-reload
        info "itsm.service removido"
      fi
      if [ -f /etc/cron.d/itsm-backup ]; then
        executar rm -f /etc/cron.d/itsm-backup
        info "cron de backup removido"
      fi
      if [ -f /etc/sysctl.d/99-itsm.conf ]; then
        executar rm -f /etc/sysctl.d/99-itsm.conf
        executar sysctl --system
        info "sysctl da stack removido"
      fi
    fi

    if [ "$COM_FIREWALL" -eq 1 ] && command -v ufw >/dev/null 2>&1; then
      etapa "Regras de firewall"
      for regra in "80/tcp" "443/tcp" "21115:21119/tcp" "21116/udp"; do
        executar ufw delete allow "$regra"
      done
      info "regras da stack removidas (SSH intacto)"
    fi
  fi
fi

# --- 7. resumo --------------------------------------------------------------
if [ "$DRY_RUN" -eq 1 ]; then
  printf '\n\033[1;33mDry-run: nada foi apagado.\033[0m\n'
  exit 0
fi

cat <<TXT

$(printf '\033[1;32m')Ambiente apagado.$(printf '\033[0m')

O Docker Engine e o código em $REPO_DIR continuam onde estavam.

Para subir de novo, do zero:
  ./scripts/configure.sh          # gera .env e segredos novos
  make up                         # ou: sudo ./scripts/install-ubuntu.sh
TXT
