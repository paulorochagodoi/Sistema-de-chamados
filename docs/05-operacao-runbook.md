# Runbook de operação

## 0. Instalação em um Ubuntu novo

Em um servidor Ubuntu 22.04/24.04 recém-provisionado, um comando faz tudo —
dependências, Docker Engine, `.env` com segredos, firewall, subida dos serviços,
unidade systemd e backup agendado:

```bash
git clone <repo> /opt/itsm && cd /opt/itsm
sudo ./scripts/install-ubuntu.sh --domain itsm.acme.com --email ti@acme.com \
     --profiles core,rmm,observability --tls --yes --smoke
```

| Opção | Efeito |
|---|---|
| `--profiles` | perfis a subir; sem ela, reaproveita o que já está no `.env` |
| `--tls` | usa Let's Encrypt (exige DNS público apontando para o host) |
| `--no-firewall` / `--no-systemd` / `--no-backup-cron` | pula a etapa |
| `--no-start` | prepara tudo sem subir containers |
| `--skip-docker` | o host já tem Docker |
| `--smoke` | roda `scripts/smoke-test.sh` ao final |
| `-y` | não pergunta nada |

O script é idempotente: rodar de novo atualiza a instalação sem recriar
segredos. Ele **não** sorteia senhas novas em cima de bancos existentes.

O que ele deixa configurado no host:

* Docker Engine + plugin Compose do repositório oficial, com rotação de log em
  `/etc/docker/daemon.json` e o usuário do `sudo` no grupo `docker`;
* `/etc/sysctl.d/99-itsm.conf` (`vm.overcommit_memory=1` para o Redis,
  `net.core.somaxconn=1024`);
* UFW liberando SSH, 80/443 e, com o perfil `rmm`, 21115-21119/tcp e 21116/udp;
* `itsm.service` (`systemctl start|stop|status itsm`), que reconcilia a stack no
  boot;
* `/etc/cron.d/itsm-backup`, backup diário às 02:30 em `/var/log/itsm-backup.log`.

Só a configuração, sem tocar no host:

```bash
./scripts/configure.sh --domain itsm.acme.com --email ti@acme.com --yes
./scripts/configure.sh --glpi-app-token <tok> --glpi-user-token <tok> --yes
```

## 1. Subir o ambiente

```bash
cp .env.example .env
./scripts/gen-secrets.sh          # gera todos os "troque-me-*"
# ajuste DOMAIN, ACME_EMAIL e TZ no .env
# (ou, de uma vez: ./scripts/configure.sh)

make up                            # perfil core (Fase 1)
make up-rmm                        # + MeshCentral e RustDesk (Fase 2)
make up-all                        # todos os perfis
make ps
```

Primeiro acesso do time: `https://<DOMAIN>/` — o painel unificado. Ele pede
usuário e senha do GLPI e, dali, dá acesso a todos os serviços da stack.

Primeiro acesso: `https://glpi.<DOMAIN>` (em dev o certificado é auto-assinado;
aceite o aviso). O GLPI instala o schema sozinho no primeiro start.

**Checklist pós-instalação do GLPI** — o instalador cria contas padrão com
senhas conhecidas. Antes de expor o serviço:

1. Troque as senhas de `glpi`, `tech`, `normal` e `post-only` (ou desative-as).
2. Remova `install/install.php` (a imagem oficial já faz isso; confirme em
   *Configurar → Geral → Diagnóstico*).
3. Crie a hierarquia de entidades (uma por cliente) — é a base do multi-tenant.
4. Habilite a API REST e gere os tokens (ver [04-integracoes.md](04-integracoes.md#2-glpi)).

## 2. Produção com TLS público

```bash
docker compose --env-file .env \
  -f deploy/compose/docker-compose.yml \
  -f deploy/compose/docker-compose.tls.yml \
  --profile core up -d
```

Requer o domínio raiz (painel) e os subdomínios (`portal.`, `glpi.`, `sso.`,
`chat.`, `rmm.`, `n8n.`, `bi.`, `s3.`, `minio.`, `bridge.`, `grafana.`)
apontando para o host, e portas 80/443 acessíveis pela internet.

## 3. Verificação e diagnóstico

```bash
make smoke              # testa containers, bancos, HTTP e regras de negócio
make logs SERVICE=glpi  # logs de um serviço
make ps
```

| Sintoma | Causa provável | Ação |
|---|---|---|
| GLPI em 502 no Traefik | container ainda instalando o schema | `make logs SERVICE=glpi`; a primeira subida leva ~1 min |
| "Time zones seem not loaded" no GLPI | grant de `mysql.time_zone_name` não aplicado | volume do MariaDB criado antes do script de init: recrie o volume ou aplique o grant manualmente |
| Alerta do RMM não vira chamado | assinatura ou token do GLPI | `curl https://bridge.<DOMAIN>/readyz` e veja `itsm_bridge_webhook_rejected_total` |
| Chamados duplicados por alerta repetido | `alert_id` instável na origem | garanta id estável no RMM; o dedupe depende dele |
| Sessão do GLPI caindo com múltiplas réplicas | sessão em disco local | configure o handler de sessão no Redis ou fixe `--scale glpi=1` |
| n8n não executa workflows | modo fila sem worker | `docker compose --profile automation up -d n8n-worker` |
| Painel abre mas não lista chamados | tokens do GLPI ausentes | `curl -k https://bridge.<DOMAIN>/readyz`; preencha `GLPI_APP_TOKEN`/`GLPI_USER_TOKEN` e reinicie o bridge |
| Login do painel recusa credenciais certas | login com credenciais desabilitado no GLPI | *Configurar → Geral → API*: ative "login com credenciais externas" |
| Serviço abre em branco dentro do painel | serviço recusou o iframe | use "Nova aba"; se for um dos embutíveis, confira o middleware `<serviço>-embed` nos labels dele |
| 404 em texto puro (`404 page not found`) em um subdomínio | nenhum roteador casou com o Host | confira o `DOMAIN` do `.env` e, nos logs do Traefik, `middleware ... does not exist` ou `Host(...)`: `make logs SERVICE=traefik` |
| Menu do painel sem os serviços de um perfil | `PORTAL_PROFILES` desatualizado | ajuste no `.env` e `make restart SERVICE=itsm-bridge` |

## 4. Backup e restore

```bash
make backup                          # dumps + volumes + envio ao MinIO
./scripts/restore.sh backups/<data>  # DESTRUTIVO
```

O `backup.sh` gera: dump do MariaDB (GLPI), `pg_dumpall` do PostgreSQL, tar dos
volumes `glpi_data` e `meshcentral_data`, e um tar da configuração. Sobe tudo
para o bucket `backups` (versionado, expira em 90 dias).

**Agende em cron do host** (o container não deve orquestrar o próprio backup):

```cron
0 3 * * * cd /opt/itsm && ./scripts/backup.sh >> /var/log/itsm-backup.log 2>&1
```

**Restore drill trimestral.** Backup não testado não é backup. A cada trimestre:
restaure em ambiente separado, faça login, abra um chamado, abra um anexo antigo
e rode `make smoke`. Registre a data e o tempo de recuperação.

## 5. Escala

```bash
# Compose: mais réplicas web (o cron permanece único, por desenho)
docker compose --env-file .env -f deploy/compose/docker-compose.yml \
  --profile core up -d --scale glpi=3 --scale itsm-bridge=3
```

Antes de escalar o GLPI horizontalmente, garanta sessão compartilhada (Redis) e
`/var/glpi` em volume compartilhado. Para Kubernetes com HPA, veja
[deploy/k8s/README.md](../deploy/k8s/README.md).

Sinais de que é hora de escalar (Grafana → *ITSM — Visão Geral*):

* p95 do Traefik passando de 500ms de forma sustentada;
* CPU do container de GLPI acima de 70% por mais de 10 min;
* fila do n8n crescendo sem drenar.

## 6. Atualização de versão

```bash
# 1. backup ANTES de qualquer upgrade
make backup

# 2. suba a tag no .env (ex.: GLPI_IMAGE=glpi/glpi:10.0.27)
# 3. recrie apenas o serviço afetado
docker compose --env-file .env -f deploy/compose/docker-compose.yml \
  --profile core up -d glpi glpi-cron

# 4. valide
make smoke
```

A imagem do GLPI aplica migrações de schema no start (`GLPI_SKIP_AUTOUPDATE`
não definido no container web). O container de cron sobe com
`GLPI_SKIP_AUTOINSTALL/AUTOUPDATE=true` justamente para não competir pela
migração. Faça upgrade de uma versão minor por vez e leia o changelog do GLPI.

## 7. Keycloak otimizado (produção)

O Compose usa `start` (augment em tempo de subida), o que custa ~20s a mais no
boot. Para produção, buildar uma imagem otimizada elimina esse passo:

```dockerfile
FROM quay.io/keycloak/keycloak:26.7.0 AS builder
ENV KC_DB=postgres KC_HEALTH_ENABLED=true KC_METRICS_ENABLED=true
RUN /opt/keycloak/bin/kc.sh build

FROM quay.io/keycloak/keycloak:26.7.0
COPY --from=builder /opt/keycloak/ /opt/keycloak/
ENTRYPOINT ["/opt/keycloak/bin/kc.sh", "start", "--optimized"]
```

## 8. Rotação de segredos

| Segredo | Como rotacionar | Impacto |
|---|---|---|
| `GLPI_USER_TOKEN` | regenerar em *Preferências → API* e atualizar o `.env` | reiniciar `itsm-bridge` |
| `BRIDGE_*_WEBHOOK_SECRET` | novo valor no `.env` **e** na origem do webhook | alertas rejeitados até alinhar |
| `N8N_ENCRYPTION_KEY` | **não rotacione sem exportar credenciais antes** | perda das credenciais salvas |
| Senhas de banco | alterar no banco e no `.env`, recriar os serviços | downtime curto |
| `PORTAL_SECRET` | novo valor no `.env` e `make restart SERVICE=itsm-bridge` | todas as sessões do painel caem (é o efeito desejado ao revogar acesso) |

## 9. Limpeza

```bash
make down          # para os containers, preserva volumes
make clean         # remove containers, redes E volumes (destrutivo)
make reset         # apaga a instalação inteira (destrutivo, pede confirmação)
```

`scripts/reset.sh` é o "voltar à estaca zero": remove containers, redes, volumes
e o `.env` do projeto `itsm` — e só dele. Não existe `docker system prune` aqui;
containers de outros projetos do host ficam intactos, porque a varredura é pelo
label `com.docker.compose.project=itsm`.

| Opção | Efeito |
|---|---|
| `--dry-run` | lista o que seria apagado, sem apagar |
| `--keep-env` | preserva o `.env` (mesmos segredos e domínio ao subir de novo) |
| `--keep-volumes` | preserva os dados (bancos, anexos, config dos apps) |
| `--images` | remove também as imagens da stack |
| `--host` | remove `itsm.service`, o cron de backup e o sysctl (precisa de root) |
| `--firewall` | remove as regras de UFW da stack; nunca mexe na de SSH (root) |
| `--backups` | apaga `backups/` |
| `--all` | tudo acima |
| `-y` | não pede confirmação (sem ela, é preciso digitar `APAGAR`) |

Reinstalação limpa, do jeito mais curto:

```bash
sudo ./scripts/reset.sh --all -y
sudo ./scripts/install-ubuntu.sh --domain <dom> --email <e-mail> --yes
```

O Docker Engine, o `/etc/docker/daemon.json` e o código do repositório nunca são
removidos.
