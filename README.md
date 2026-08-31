# Sistema de Chamados — ITSM containerizado

Plataforma de ITSM para equipes de TI internas e MSPs: chamados, clientes
multi-tenant, CMDB, contratos e faturamento, acesso remoto, monitoramento
proativo e omnichannel — tudo em containers, com stack 100% open-source.

Implementação da especificação em [docs/01-especificacao.md](docs/01-especificacao.md).

```
┌──────────────────────── Traefik (TLS) ────────────────────────┐
│  GLPI     Keycloak    Chatwoot   MeshCentral   n8n   Metabase  │
│  (ITSM)     (SSO)     (chat)      (RMM)      (autom.)  (BI)    │
└───────────────────────────┬────────────────────────────────────┘
              rede interna  │  MariaDB · PostgreSQL · Redis
                            │  RabbitMQ · MinIO · itsm-bridge
```

## Começar em 3 comandos

```bash
cp .env.example .env && ./scripts/gen-secrets.sh
make up            # sobe o núcleo (Fase 1)
make smoke         # verifica containers, bancos, HTTP e regras de negócio
```

Acesse `https://glpi.itsm.localhost` (certificado auto-assinado em dev).
Depois, siga o checklist pós-instalação no
[runbook](docs/05-operacao-runbook.md#1-subir-o-ambiente).

## O que já está pronto

| Camada | Entregue |
|---|---|
| Núcleo ITSM | GLPI 10 com cron isolado, MariaDB parametrizado, MinIO com buckets e retenção |
| Identidade | Keycloak com realm `itsm`, papéis, MFA obrigatório e política de senha |
| Integrações | `itsm-bridge`: RMM→chamado (com dedupe), Chatwoot→chamado, SLA, faturamento |
| RMM e acesso remoto | MeshCentral (não supervisionado) + RustDesk (sob demanda) |
| Omnichannel | Chatwoot (web + worker) com storage S3 |
| Automação | n8n em modo fila + 3 workflows prontos |
| Observabilidade | Prometheus (alertas de SLA, latência, capacidade), Grafana, Loki |
| Escala | Perfis do Compose, manifests Kubernetes com HPA/PDB/NetworkPolicy, values Helm |

Estado por fase do roadmap: [docs/07-roadmap.md](docs/07-roadmap.md).

## Estrutura

```
deploy/compose/      stack Docker Compose (profiles: core, rmm, omnichannel,
                     automation, bi, observability) + configs dos serviços
deploy/k8s/          manifests Kustomize e values Helm para a Fase 5
services/itsm-bridge serviço FastAPI de integração (com testes)
automation/n8n/      workflows prontos para importar
scripts/             gen-secrets, backup, restore, smoke-test
docs/                especificação, arquitetura, integrações, runbook, ADRs
```

## Perfis

```bash
make up              # core: Traefik, GLPI, MariaDB, PostgreSQL, Redis, MinIO, Keycloak, bridge
make up-rmm          # + MeshCentral e RustDesk
make up-omnichannel  # + Chatwoot
make up-automation   # + n8n e RabbitMQ
make up-observability# + Prometheus, Grafana, Loki
make up-all          # tudo
```

## Desenvolvimento do itsm-bridge

```bash
cd services/itsm-bridge
python -m venv .venv && . .venv/bin/activate
pip install -r requirements-dev.txt
pytest          # 66 testes
ruff check .
```

Ou pela raiz: `make test` e `make lint`.

## Documentação

| Documento | Conteúdo |
|---|---|
| [01-especificacao.md](docs/01-especificacao.md) | especificação de origem |
| [02-arquitetura.md](docs/02-arquitetura.md) | arquitetura implementada, fluxos, escala |
| [03-modelo-de-dados.md](docs/03-modelo-de-dados.md) | entidades e onde cada uma vive |
| [04-integracoes.md](docs/04-integracoes.md) | contratos de API, webhooks, configuração de cada sistema |
| [05-operacao-runbook.md](docs/05-operacao-runbook.md) | subir, diagnosticar, backup/restore, escalar, atualizar |
| [06-seguranca-compliance.md](docs/06-seguranca-compliance.md) | SSO/MFA, rede, segredos, auditoria, LGPD, licenças |
| [07-roadmap.md](docs/07-roadmap.md) | o que está pronto, o que é configuração, o que falta |
| [08-decisoes-tecnicas.md](docs/08-decisoes-tecnicas.md) | ADRs — por que cada escolha |

## Antes de ir para produção

1. `./scripts/gen-secrets.sh` e troque os `TROQUE-ESTE-SECRET-*` do realm do Keycloak.
2. Ajuste `DOMAIN`, `ACME_EMAIL` e os `redirectUris` do realm para o seu domínio.
3. Suba com o overlay TLS: `docker compose -f deploy/compose/docker-compose.yml -f deploy/compose/docker-compose.tls.yml --profile core up -d`.
4. Defina os segredos dos webhooks (`BRIDGE_*_WEBHOOK_SECRET`) — sem eles a validação de assinatura fica desligada.
5. Agende `scripts/backup.sh` no cron do host e marque o primeiro restore drill.

Detalhes e pendências conhecidas em
[06-seguranca-compliance.md](docs/06-seguranca-compliance.md#9-endurecimento-pendente-assumido-não-implementado).
