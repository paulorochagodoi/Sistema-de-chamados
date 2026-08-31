#!/usr/bin/env bash
# Instalação completa da stack ITSM em um Ubuntu limpo (22.04 ou 24.04):
# dependências, Docker Engine, firewall, configuração, subida dos serviços,
# unidade systemd e backup agendado.
#
#   sudo ./scripts/install-ubuntu.sh
#   sudo ./scripts/install-ubuntu.sh --domain itsm.acme.com --email ti@acme.com \
#        --profiles core,rmm,observability --tls --yes
#
# Idempotente: pode rodar de novo para atualizar a instalação.
set -euo pipefail

REPO_DIR="$(cd "$(dirname "$0")/.." && pwd)"
cd "$REPO_DIR"

# --- opções -----------------------------------------------------------------
DOMAIN_ARG=""
EMAIL_ARG=""
TZ_ARG=""
PROFILES=""
ASSUME_YES=0
SKIP_DOCKER=0
WITH_FIREWALL=1
WITH_SYSTEMD=1
WITH_BACKUP_CRON=1
WITH_TLS=0
DO_START=1
RUN_SMOKE=0

uso() {
  cat <<'TXT'
Uso: sudo ./scripts/install-ubuntu.sh [opções]

  --domain <dom>      Domínio da stack (padrão: pergunta; ex.: itsm.acme.com)
  --email <e-mail>    E-mail do Let's Encrypt
  --timezone <tz>     Fuso horário (padrão: o do host)
  --profiles <lista>  Perfis a subir, separados por vírgula. Sem esta opção,
                      reaproveita PORTAL_PROFILES do .env (ou 'core' em
                      instalação nova). Valores possíveis:
                      core,rmm,omnichannel,automation,bi,observability
  --tls               Sobe com Let's Encrypt (exige DNS público apontando aqui)
  --no-firewall       Não mexe no UFW
  --no-systemd        Não instala a unidade itsm.service
  --no-backup-cron    Não agenda o backup diário
  --no-start          Prepara tudo, mas não sobe os containers
  --skip-docker       Assume que o Docker já está instalado
  --smoke             Roda ./scripts/smoke-test.sh ao final
  -y, --yes           Não pergunta nada (usa os padrões e o que foi passado)
  -h, --help          Esta ajuda

Perfis:
  core           portal, GLPI, MariaDB, PostgreSQL, Redis, MinIO, Keycloak,
                 Traefik e itsm-bridge
  rmm            MeshCentral e RustDesk
  omnichannel    Chatwoot
  automation     n8n e RabbitMQ
  bi             Metabase
  observability  Prometheus, Grafana, Loki, exporters
TXT
}

while [ $# -gt 0 ]; do
  case "$1" in
    --domain)         DOMAIN_ARG="${2:?}"; shift 2 ;;
    --email)          EMAIL_ARG="${2:?}"; shift 2 ;;
    --timezone)       TZ_ARG="${2:?}"; shift 2 ;;
    --profiles)       PROFILES="${2:?}"; shift 2 ;;
    --tls)            WITH_TLS=1; shift ;;
    --no-firewall)    WITH_FIREWALL=0; shift ;;
    --no-systemd)     WITH_SYSTEMD=0; shift ;;
    --no-backup-cron) WITH_BACKUP_CRON=0; shift ;;
    --no-start)       DO_START=0; shift ;;
    --skip-docker)    SKIP_DOCKER=1; shift ;;
    --smoke)          RUN_SMOKE=1; shift ;;
    -y|--yes)         ASSUME_YES=1; shift ;;
    -h|--help)        uso; exit 0 ;;
    *) echo "opção desconhecida: $1" >&2; uso >&2; exit 2 ;;
  esac
done

# Sem --profiles, mantém os perfis já configurados: reinstalar não pode
# encolher silenciosamente a stack que está rodando.
if [ -z "$PROFILES" ] && [ -f .env ]; then
  PROFILES="$(sed -n 's/^PORTAL_PROFILES=//p' .env | head -1)"
fi
PROFILES="${PROFILES:-core}"

etapa() { printf '\n\033[1;36m==> %s\033[0m\n' "$*"; }
info()  { printf '    %s\n' "$*"; }
aviso() { printf '\033[33m !! %s\033[0m\n' "$*" >&2; }
erro()  { printf '\033[31merro: %s\033[0m\n' "$*" >&2; exit 1; }

confirmar() {
  [ "$ASSUME_YES" -eq 1 ] && return 0
  [ -t 0 ] || return 0
  local resposta
  read -r -p "$1 [S/n]: " resposta </dev/tty || resposta=""
  case "${resposta:-s}" in [sSyY]*) return 0 ;; *) return 1 ;; esac
}

# --- 1. verificações prévias ------------------------------------------------
etapa "Verificando o host"

[ "$(id -u)" -eq 0 ] || erro "rode com sudo: sudo ./scripts/install-ubuntu.sh"

# shellcheck disable=SC1091
. /etc/os-release 2>/dev/null || erro "não consegui identificar o sistema (/etc/os-release)"
if [ "${ID:-}" != "ubuntu" ]; then
  aviso "sistema '${PRETTY_NAME:-desconhecido}' não é Ubuntu; o script segue, mas sem garantias"
  confirmar "Continuar assim mesmo?" || exit 1
else
  case "${VERSION_ID:-}" in
    22.04|24.04) info "Ubuntu ${VERSION_ID} — versão suportada" ;;
    *) aviso "Ubuntu ${VERSION_ID:-?} não é testado (use 22.04 ou 24.04)" ;;
  esac
fi

case "$(uname -m)" in
  x86_64|aarch64) : ;;
  *) erro "arquitetura $(uname -m) sem imagens publicadas para toda a stack" ;;
esac

memoria_mb=$(awk '/MemTotal/ {printf "%d", $2/1024}' /proc/meminfo)
memoria_mb=${memoria_mb:-0}
disco_gb=$(df -BG --output=avail "$REPO_DIR" | tail -1 | tr -dc '0-9')
disco_gb=${disco_gb:-0}
perfis_qtd=$(printf '%s' "$PROFILES" | tr ',' '\n' | grep -c .)
memoria_min=$((2048 + perfis_qtd * 2048))
info "memória: ${memoria_mb} MB · disco livre: ${disco_gb} GB · perfis: $PROFILES"
if [ "$memoria_mb" -lt "$memoria_min" ]; then
  aviso "recomendado ~${memoria_min} MB de RAM para estes perfis; há ${memoria_mb} MB"
  confirmar "Continuar?" || exit 1
fi
if [ "$disco_gb" -lt 40 ]; then
  aviso "menos de 40 GB livres: bancos, imagens e backups enchem rápido"
  confirmar "Continuar?" || exit 1
fi

for porta in 80 443; do
  if ss -lntH "sport = :$porta" 2>/dev/null | grep -q .; then
    ocupante=$(ss -lntpH "sport = :$porta" 2>/dev/null | head -1 | sed 's/.*users:((//;s/).*//')
    if docker ps --format '{{.Ports}}' 2>/dev/null | grep -q ":$porta->"; then
      info "porta $porta já é do Traefik desta stack"
    else
      aviso "porta $porta ocupada por ${ocupante:-outro processo} — o Traefik não vai subir"
      confirmar "Continuar assim mesmo?" || exit 1
    fi
  fi
done

# --- 2. dependências do sistema ---------------------------------------------
etapa "Instalando dependências do sistema"
export DEBIAN_FRONTEND=noninteractive
apt-get update -qq
apt-get install -y -qq \
  ca-certificates curl gnupg git jq make openssl iproute2 cron >/dev/null
info "pacotes básicos prontos"

# --- 3. Docker Engine -------------------------------------------------------
etapa "Docker Engine e plugin Compose"
if [ "$SKIP_DOCKER" -eq 1 ]; then
  info "pulado por --skip-docker"
elif docker compose version >/dev/null 2>&1; then
  info "já instalado: $(docker --version), $(docker compose version --short 2>/dev/null || echo compose ok)"
else
  install -m 0755 -d /etc/apt/keyrings
  curl -fsSL "https://download.docker.com/linux/ubuntu/gpg" \
    | gpg --dearmor -o /etc/apt/keyrings/docker.gpg --yes
  chmod a+r /etc/apt/keyrings/docker.gpg
  cat > /etc/apt/sources.list.d/docker.list <<EOF
deb [arch=$(dpkg --print-architecture) signed-by=/etc/apt/keyrings/docker.gpg] https://download.docker.com/linux/ubuntu ${UBUNTU_CODENAME:-${VERSION_CODENAME:-jammy}} stable
EOF
  apt-get update -qq
  apt-get install -y -qq docker-ce docker-ce-cli containerd.io \
    docker-buildx-plugin docker-compose-plugin >/dev/null
  info "instalado: $(docker --version)"
fi

systemctl enable --now docker >/dev/null 2>&1 || true

# rotação de log do daemon: sem isso um container falante enche o disco
if [ ! -f /etc/docker/daemon.json ]; then
  install -d -m 0755 /etc/docker
  cat > /etc/docker/daemon.json <<'EOF'
{
  "log-driver": "json-file",
  "log-opts": { "max-size": "10m", "max-file": "3" },
  "live-restore": true
}
EOF
  systemctl restart docker
  info "/etc/docker/daemon.json criado (rotação de logs)"
fi

# quem chamou o sudo passa a usar o docker sem sudo (vale no próximo login)
if [ -n "${SUDO_USER:-}" ] && [ "$SUDO_USER" != "root" ]; then
  if ! id -nG "$SUDO_USER" | tr ' ' '\n' | grep -qx docker; then
    usermod -aG docker "$SUDO_USER"
    info "usuário $SUDO_USER adicionado ao grupo docker (relogue para valer)"
  fi
fi

# --- 4. ajustes de kernel ---------------------------------------------------
etapa "Ajustes de kernel"
# overcommit: o Redis avisa e pode falhar ao salvar o RDB sem isso.
# somaxconn: fila de conexões dos serviços web da stack.
cat > /etc/sysctl.d/99-itsm.conf <<'EOF'
# Ajustes para a stack ITSM (Redis, Traefik e serviços web)
vm.overcommit_memory = 1
net.core.somaxconn = 1024
EOF
sysctl -q --system >/dev/null 2>&1 || true
info "/etc/sysctl.d/99-itsm.conf aplicado"

# --- 5. configuração da stack (.env) ----------------------------------------
etapa "Configurando o .env"
CONFIGURE_ARGS=()
[ -n "$DOMAIN_ARG" ] && CONFIGURE_ARGS+=(--domain "$DOMAIN_ARG")
[ -n "$EMAIL_ARG" ] && CONFIGURE_ARGS+=(--email "$EMAIL_ARG")
if [ -n "$TZ_ARG" ]; then
  CONFIGURE_ARGS+=(--timezone "$TZ_ARG")
elif [ -f /etc/timezone ]; then
  CONFIGURE_ARGS+=(--timezone "$(cat /etc/timezone)")
fi
CONFIGURE_ARGS+=(--profiles "$PROFILES")
[ "$ASSUME_YES" -eq 1 ] && CONFIGURE_ARGS+=(--yes)

./scripts/configure.sh "${CONFIGURE_ARGS[@]}"

DOMAIN="$(sed -n 's/^DOMAIN=//p' .env | head -1)"
DOMAIN="${DOMAIN:-itsm.localhost}"

# o .env nasce 600 e de root; quem chamou o sudo precisa conseguir operar a stack
if [ -n "${SUDO_USER:-}" ] && [ "$SUDO_USER" != "root" ]; then
  chown "$SUDO_USER" .env
fi

if [ "$WITH_TLS" -eq 1 ]; then
  case "$DOMAIN" in
    *.localhost|localhost|"")
      erro "--tls exige um domínio público; '$DOMAIN' nunca receberá um certificado do Let's Encrypt" ;;
  esac
fi

# --- 6. firewall ------------------------------------------------------------
if [ "$WITH_FIREWALL" -eq 1 ]; then
  etapa "Firewall (UFW)"
  apt-get install -y -qq ufw >/dev/null
  ufw allow OpenSSH >/dev/null 2>&1 || ufw allow 22/tcp >/dev/null
  ufw allow 80/tcp >/dev/null
  ufw allow 443/tcp >/dev/null
  info "liberadas: SSH, 80/tcp, 443/tcp"
  case ",$PROFILES," in
    *,rmm,*)
      # RustDesk precisa de portas próprias: não passa pelo Traefik
      ufw allow 21115:21119/tcp >/dev/null
      ufw allow 21116/udp >/dev/null
      info "liberadas para o RustDesk: 21115-21119/tcp e 21116/udp"
      ;;
  esac
  if ufw status 2>/dev/null | grep -q '^Status: inactive'; then
    if confirmar "Ativar o UFW agora? (o acesso SSH já está liberado)"; then
      ufw --force enable >/dev/null
      info "UFW ativado"
    else
      info "UFW continua desativado; as regras ficam gravadas"
    fi
  else
    info "UFW já estava ativo"
  fi
fi

# --- 7. subida da stack -----------------------------------------------------
COMPOSE_ARGS=(--env-file "$REPO_DIR/.env" -f "$REPO_DIR/deploy/compose/docker-compose.yml")
[ "$WITH_TLS" -eq 1 ] && COMPOSE_ARGS+=(-f "$REPO_DIR/deploy/compose/docker-compose.tls.yml")
PROFILE_ARGS=()
for perfil in ${PROFILES//,/ }; do
  PROFILE_ARGS+=(--profile "$perfil")
done

if [ "$DO_START" -eq 1 ]; then
  etapa "Construindo as imagens próprias (portal e itsm-bridge)"
  docker compose "${COMPOSE_ARGS[@]}" "${PROFILE_ARGS[@]}" build portal itsm-bridge

  etapa "Subindo os serviços"
  docker compose "${COMPOSE_ARGS[@]}" "${PROFILE_ARGS[@]}" up -d

  etapa "Aguardando os serviços ficarem saudáveis"
  # O GLPI instala o schema na primeira subida: pode passar de um minuto.
  fim=$((SECONDS + 300))
  while [ "$SECONDS" -lt "$fim" ]; do
    pendentes=$(docker compose "${COMPOSE_ARGS[@]}" "${PROFILE_ARGS[@]}" ps \
      --format '{{.Service}} {{.Health}}' 2>/dev/null | awk '$2 == "starting"' | wc -l)
    quebrados=$(docker compose "${COMPOSE_ARGS[@]}" "${PROFILE_ARGS[@]}" ps \
      --format '{{.Service}} {{.Health}}' 2>/dev/null | awk '$2 == "unhealthy" {print $1}')
    if [ "$pendentes" -eq 0 ]; then
      [ -n "$quebrados" ] && aviso "sem saúde: $(echo "$quebrados" | tr '\n' ' ')"
      break
    fi
    sleep 5
  done
  docker compose "${COMPOSE_ARGS[@]}" "${PROFILE_ARGS[@]}" ps
fi

# --- 8. systemd -------------------------------------------------------------
if [ "$WITH_SYSTEMD" -eq 1 ]; then
  etapa "Unidade systemd (itsm.service)"
  # Os containers já reiniciam sozinhos (restart: unless-stopped). A unidade
  # existe para reconciliar o estado no boot e dar systemctl start/stop.
  cat > /etc/systemd/system/itsm.service <<EOF
[Unit]
Description=Stack ITSM (Sistema de Chamados)
Requires=docker.service
After=docker.service network-online.target
Wants=network-online.target

[Service]
Type=oneshot
RemainAfterExit=yes
WorkingDirectory=$REPO_DIR
TimeoutStartSec=0
ExecStart=/usr/bin/docker compose ${COMPOSE_ARGS[*]} ${PROFILE_ARGS[*]} up -d
ExecStop=/usr/bin/docker compose ${COMPOSE_ARGS[*]} ${PROFILE_ARGS[*]} down
ExecReload=/usr/bin/docker compose ${COMPOSE_ARGS[*]} ${PROFILE_ARGS[*]} up -d --remove-orphans

[Install]
WantedBy=multi-user.target
EOF
  systemctl daemon-reload
  systemctl enable itsm.service >/dev/null 2>&1
  info "ativada: systemctl start|stop|status itsm"
fi

# --- 9. backup agendado -----------------------------------------------------
if [ "$WITH_BACKUP_CRON" -eq 1 ]; then
  etapa "Backup diário"
  cat > /etc/cron.d/itsm-backup <<EOF
# Backup da stack ITSM, todo dia às 02:30. Log em /var/log/itsm-backup.log
SHELL=/bin/bash
PATH=/usr/local/sbin:/usr/local/bin:/usr/sbin:/usr/bin:/sbin:/bin
30 2 * * * root cd $REPO_DIR && ./scripts/backup.sh >> /var/log/itsm-backup.log 2>&1
EOF
  chmod 0644 /etc/cron.d/itsm-backup
  systemctl restart cron >/dev/null 2>&1 || true
  info "agendado: /etc/cron.d/itsm-backup (02:30, log em /var/log/itsm-backup.log)"
  aviso "backup local não é backup: replique $REPO_DIR/backups para fora deste host"
fi

# --- 10. verificação --------------------------------------------------------
if [ "$RUN_SMOKE" -eq 1 ] && [ "$DO_START" -eq 1 ]; then
  etapa "Verificação pós-deploy"
  ./scripts/smoke-test.sh || aviso "o smoke test apontou falhas — veja acima"
fi

# --- 11. resumo -------------------------------------------------------------
cat <<TXT

$(printf '\033[1;32m')Instalação concluída.$(printf '\033[0m')

  Painel unificado  https://$DOMAIN/            (ou https://portal.$DOMAIN/)
  GLPI              https://glpi.$DOMAIN/
  SSO (Keycloak)    https://sso.$DOMAIN/
  API (bridge)      https://bridge.$DOMAIN/docs

  Perfis ativos     $PROFILES
  Comandos          make ps · make logs SERVICE=portal · make smoke
                    systemctl status itsm

Próximos passos:
  1. Abra o GLPI, conclua o assistente e troque as senhas padrão (glpi/glpi).
  2. Em Configurar > Geral > API: habilite a API REST e o login com credenciais,
     gere App-Token e User-Token.
  3. Registre os tokens e reinicie o bridge:
       sudo ./scripts/configure.sh --glpi-app-token <tok> --glpi-user-token <tok> --yes
       make restart SERVICE=itsm-bridge
  4. Entre no painel com um usuário do GLPI: https://$DOMAIN/
TXT

if [ "$WITH_TLS" -eq 0 ]; then
  cat <<'TXT'

Os certificados são auto-assinados (aviso do navegador). Para Let's Encrypt:
aponte o DNS para este host e rode de novo com --tls.
TXT
fi
