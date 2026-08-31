# Sistema de Chamados — ITSM containerizado

Plataforma de ITSM para equipes de TI internas e MSPs: chamados, clientes
multi-tenant, CMDB, contratos e faturamento, acesso remoto, monitoramento
proativo e omnichannel — tudo em containers, com stack 100% open-source.

Implementação da especificação em [docs/01-especificacao.md](docs/01-especificacao.md).

```
┌──────────────────────── Traefik (TLS) ────────────────────────┐
│            portal — painel único em https://<domínio>          │
├────────────────────────────────────────────────────────────────┤
│  GLPI     Keycloak    Chatwoot   MeshCentral   n8n   Metabase  │
│  (ITSM)     (SSO)     (chat)      (RMM)      (autom.)  (BI)    │
└───────────────────────────┬────────────────────────────────────┘
              rede interna  │  MariaDB · PostgreSQL · Redis
                            │  RabbitMQ · MinIO · itsm-bridge
```

Todos os serviços são acessados pelo mesmo painel: um menu só, chamados e
prazos resolvidos ali mesmo, e as interfaces dos demais serviços abertas dentro
do próprio painel.

## Instalar em um Ubuntu novo (um comando)

```bash
git clone <repo> /opt/itsm && cd /opt/itsm
sudo ./scripts/install-ubuntu.sh --domain itsm.acme.com --email ti@acme.com \
     --profiles core,rmm,observability --tls --yes
```

O script instala Docker Engine e dependências, gera o `.env` com segredos,
configura o firewall, sobe os serviços, cria a unidade `itsm.service` e agenda
o backup diário. É idempotente — rodar de novo atualiza a instalação. Opções
em `--help` e no [runbook](docs/05-operacao-runbook.md#0-instalação-em-um-ubuntu-novo).

## Começar em 3 comandos (host que já tem Docker)

```bash
./scripts/configure.sh   # .env: domínio, e-mail, fuso, perfis e segredos
make up                  # sobe o núcleo (Fase 1)
make smoke               # verifica containers, bancos, HTTP e regras de negócio
```

Acesse `https://itsm.localhost` — o painel (certificado auto-assinado em dev).
O login é o do GLPI. Depois, siga o checklist pós-instalação no
[runbook](docs/05-operacao-runbook.md#1-subir-o-ambiente).

## O que já está pronto

| Camada | Entregue |
|---|---|
| Painel unificado | `portal`: menu único com chamados, SLA, faturamento, status da stack e as interfaces dos demais serviços embutidas |
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
services/portal      painel unificado (React + Vite + Tailwind, servido por nginx)
services/itsm-bridge serviço FastAPI de integração e API do painel (com testes)
automation/n8n/      workflows prontos para importar
scripts/             install-ubuntu, configure, gen-secrets, backup, restore,
                     smoke-test
docs/                especificação, arquitetura, integrações, runbook, ADRs
```

## O painel

`https://<domínio>/` (e `https://portal.<domínio>/`) é a porta de entrada. O
login usa as credenciais do GLPI; com um proxy OIDC na frente, o painel aceita a
identidade do SSO (`PORTAL_TRUST_FORWARDED_AUTH=true`).

| No painel | O que dá para fazer |
|---|---|
| Painel | chamados abertos, prazos estourados, fila sem técnico e saúde de todos os serviços |
| Chamados | filtrar, buscar, abrir, acompanhar e solucionar — sem sair da tela |
| Prazos de SLA | calcular resposta e resolução pela janela do contrato |
| Faturamento | prévia da fatura a partir dos apontamentos |
| Status dos serviços | disponibilidade e latência, checadas por dentro da rede |
| GLPI, MeshCentral, Chatwoot, n8n, Grafana | interface do serviço aberta dentro do painel |
| Keycloak, MinIO, Metabase | abrem em nova aba (o próprio serviço recusa iframe) |

Detalhes de arquitetura em
[02-arquitetura.md](docs/02-arquitetura.md#8-o-painel-unificado-portal) e a API
em [04-integracoes.md](docs/04-integracoes.md#10-painel-unificado-portal).

## Desenvolvimento do portal

```bash
cd services/portal
npm install
VITE_DEV_API_PROXY=http://localhost:8000 npm run dev   # http://localhost:3000
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
pytest          # 87 testes
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

1. `./scripts/configure.sh` (ou `gen-secrets.sh`) e troque os
   `TROQUE-ESTE-SECRET-*` do realm do Keycloak.
2. Ajuste `DOMAIN`, `ACME_EMAIL` e os `redirectUris` do realm para o seu domínio.
3. Suba com o overlay TLS: `docker compose -f deploy/compose/docker-compose.yml -f deploy/compose/docker-compose.tls.yml --profile core up -d`.
4. Defina os segredos dos webhooks (`BRIDGE_*_WEBHOOK_SECRET`) — sem eles a validação de assinatura fica desligada.
5. Agende `scripts/backup.sh` no cron do host e marque o primeiro restore drill.

Detalhes e pendências conhecidas em
[06-seguranca-compliance.md](docs/06-seguranca-compliance.md#9-endurecimento-pendente-assumido-não-implementado).
