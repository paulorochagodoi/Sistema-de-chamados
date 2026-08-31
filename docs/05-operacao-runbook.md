# Runbook de operação

## 1. Subir o ambiente

```bash
cp .env.example .env
./scripts/gen-secrets.sh          # gera todos os "troque-me-*"
# ajuste DOMAIN, ACME_EMAIL e TZ no .env

make up                            # perfil core (Fase 1)
make up-rmm                        # + MeshCentral e RustDesk (Fase 2)
make up-all                        # todos os perfis
make ps
```

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

Requer DNS dos subdomínios (`glpi.`, `sso.`, `chat.`, `rmm.`, `n8n.`, `bi.`,
`s3.`, `minio.`, `bridge.`, `grafana.`) apontando para o host e portas 80/443
acessíveis pela internet.

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

## 9. Limpeza

```bash
make down          # para os containers, preserva volumes
make clean         # remove containers, redes E volumes (destrutivo)
```
