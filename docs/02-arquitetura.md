# Arquitetura implementada

Este documento descreve **o que existe neste repositório** e como as peças se
encaixam. A especificação de origem está em [01-especificacao.md](01-especificacao.md);
as escolhas que divergem dela estão justificadas em
[08-decisoes-tecnicas.md](08-decisoes-tecnicas.md).

## 1. Visão geral

```
                      Internet
                          │  443/tcp
                 ┌────────▼─────────┐
                 │  Traefik (edge)  │  TLS, redirect 80→443, headers, rate limit
                 └────────┬─────────┘
                          │
              ┌───────────▼────────────┐
              │  portal (painel único) │  <DOMAIN> e portal.<DOMAIN>
              │  SPA + proxy /api      │  menu, chamados, status, iframes
              └───────────┬────────────┘
        ┌─────────┬───────┼─────────┬──────────┬──────────┐
   ┌────▼───┐ ┌───▼────┐ ┌▼───────┐ ┌▼────────┐ ┌▼───────┐ ┌▼────────┐
   │  GLPI  │ │Keycloak│ │Chatwoot│ │MeshCentr│ │  n8n   │ │Metabase │
   │  web   │ │  SSO   │ │  web   │ │  RMM    │ │        │ │   BI    │
   └────┬───┘ └───┬────┘ └───┬────┘ └────┬────┘ └───┬────┘ └────┬────┘
        │         │          │           │          │           │
   ┌────▼─────────▼──────────▼───────────▼──────────▼───────────▼────┐
   │                     rede itsm_data (internal)                    │
   │  MariaDB   PostgreSQL   Redis   RabbitMQ   MinIO   itsm-bridge   │
   └──────────────────────────────────────────────────────────────────┘
        ▲                                              ▲
   glpi-cron (worker único)                    chatwoot-worker, n8n-worker
```

O portal não substitui os serviços: cada um continua no seu subdomínio, com sua
própria sessão. O que o painel faz é reunir todos em um menu, mostrar a saúde de
cada um e resolver no próprio painel o que é operação do dia a dia (fila de
chamados, prazos de SLA, prévia de fatura), abrindo os demais dentro do mesmo
enquadramento — ver [§8](#8-o-painel-unificado-portal).

Duas redes:

* **`itsm_edge`** — onde o Traefik publica e por onde os serviços falam com a
  internet (SMTP, APIs de WhatsApp, agentes remotos).
* **`itsm_data`** — `internal: true`. Bancos, cache e fila vivem só aqui; não há
  rota para fora nem portas publicadas no host.

## 2. Serviços e papéis

| Serviço | Papel | Profile |
|---|---|---|
| `traefik` | Ingress, TLS, headers de segurança, métricas | core |
| `portal` | Painel unificado: menu único, chamados, status e acesso a todos os serviços | core |
| `glpi` | Núcleo ITSM: chamados, CMDB, contratos, KB, catálogo | core |
| `glpi-cron` | Worker de tarefas agendadas do GLPI (réplica única) | core |
| `mariadb` | Banco do GLPI | core |
| `postgres` | Banco de Keycloak, Chatwoot, n8n e Metabase | core |
| `redis` | Cache, fila do n8n, correlação alerta→chamado do bridge | core |
| `minio` + `minio-init` | Anexos, gravações de sessão e backups (S3) | core |
| `keycloak` | SSO, MFA, papéis e federação AD/LDAP | core |
| `itsm-bridge` | Integrações próprias: RMM→chamado, chat→chamado, SLA, faturamento | core |
| `meshcentral` | RMM, inventário, terminal remoto, acesso não supervisionado | rmm |
| `rustdesk-hbbs` / `rustdesk-hbbr` | Acesso remoto sob demanda (signal + relay) | rmm |
| `chatwoot-web` / `chatwoot-worker` | Omnichannel (chat, WhatsApp, e-mail) | omnichannel |
| `n8n` / `n8n-worker` | Automação entre sistemas (modo fila) | automation |
| `rabbitmq` | Fila para jobs assíncronos pesados | automation |
| `metabase` | BI e dashboards por cliente | bi |
| `prometheus`, `grafana`, `loki`, `promtail`, `cadvisor`, `node-exporter` | Observabilidade | observability |

Os profiles espelham as fases do roadmap: subir a Fase 1 é
`docker compose --profile core up -d`.

## 3. Por que existe o itsm-bridge

O n8n cobre bem automação declarativa, mas três coisas precisam de código
testável, versionado e com contrato estável:

1. **Alerta → chamado** com deduplicação e correlação (um alerta que repete a
   cada minuto não pode gerar um chamado por minuto, e a normalização precisa
   voltar ao chamado certo).
2. **Prazos de SLA** com janela de atendimento, fim de semana e feriado —
   regra de negócio com dezenas de casos de borda, cada um coberto por teste.
3. **Faturamento** — arredondamento de apontamento, franquia, excedente,
   desconto e imposto. Erro aqui vira nota fiscal errada.

O bridge é um serviço FastAPI stateless (`services/itsm-bridge`) com 66 testes.
O n8n continua sendo o barramento: ele orquestra, o bridge decide.

### Endpoints

| Método | Rota | Uso |
|---|---|---|
| POST | `/webhooks/rmm/alert` | Alerta do RMM → abre/atualiza chamado |
| POST | `/webhooks/chatwoot` | Evento do Chatwoot → abre/atualiza chamado |
| POST | `/api/sla/deadline` | Prazos de resposta e resolução |
| POST | `/api/sla/at-risk` | Um prazo está a vencer? (gatilho de escalonamento) |
| POST | `/api/billing/invoices/preview` | Prévia da fatura do período |
| GET | `/healthz`, `/readyz`, `/metrics` | Liveness, readiness, Prometheus |

Detalhes de payload em [04-integracoes.md](04-integracoes.md).

## 4. Fluxos principais

### 4.1 Monitoramento proativo abre chamado

```
MeshCentral/Tactical  --POST assinado-->  itsm-bridge
                                              │
                              já existe chamado para o alerta?
                                   ├── sim → 200 duplicate (nada é criado)
                                   └── não → resolve entidade do cliente
                                             cria Ticket no GLPI
                                             vincula o Computer (CMDB)
                                             grava correlação no Redis (TTL)
                                             incrementa métrica Prometheus
```

Quando o alerta normaliza (`status: resolved`), o bridge registra um
acompanhamento e **não** encerra o chamado: o encerramento é decisão do técnico,
que valida a causa raiz — é o que evita fechar incidente recorrente sem tratar.

### 4.2 Conversa de WhatsApp/chat vira chamado

Chatwoot dispara webhook → o bridge cria o chamado na primeira mensagem e
espelha as mensagens seguintes do cliente como acompanhamentos, mantendo o
histórico consolidado no núcleo ITSM. Respostas do agente não são espelhadas
(já estão no Chatwoot; duplicá-las polui o chamado).

### 4.3 SLA e escalonamento

O workflow `02-escalonamento-de-sla.json` roda a cada 15 min, busca chamados
abertos com prazo no GLPI, pergunta ao bridge se cada um está em risco
(considerando a janela de atendimento do contrato) e escala os que estiverem.
Em paralelo, o bridge mantém a métrica `itsm_tickets_sla_at_risk`, que alimenta
o alerta `SLAEmRisco` no Prometheus e o dashboard do Grafana.

### 4.4 Apontamento vira fatura

Workflow mensal: coleta apontamentos do período no GLPI → agrupa por contrato →
pede a prévia ao bridge → envia para revisão humana antes de emitir a nota.
O cálculo é determinístico e reproduzível: a mesma entrada gera a mesma fatura.

## 5. Multi-tenancy

**Padrão — isolamento lógico.** Cada cliente é uma *entidade* do GLPI. Uma
instalação, um banco, N clientes. Chamados, ativos, contratos e usuários herdam
a entidade; o portal do cliente enxerga apenas a sua. O bridge respeita isso:
todo chamado nasce com `entities_id` resolvido a partir do `client_code` do
alerta (ou explicitamente via `entity_id`).

**Exceção — isolamento físico.** Cliente com exigência contratual de dados
separados ganha namespace e banco dedicados no Kubernetes (overlay Kustomize por
cliente). Isso multiplica custo de operação: use só quando o contrato exigir.

## 6. Escalabilidade

| Componente | Como escala | Limite prático |
|---|---|---|
| GLPI web | horizontal (`--scale glpi=N` / HPA) | sessão em Redis + `/var/glpi` RWX |
| GLPI cron | **não escala** — réplica única por desenho | duplicaria e-mails e escalonamentos |
| itsm-bridge | horizontal, stateless | exige Redis para correlação compartilhada |
| Chatwoot | web + N workers Sidekiq | banco |
| n8n | modo fila (`EXECUTIONS_MODE=queue`) + N workers | Redis |
| MariaDB | vertical + réplica de leitura para BI | escrita continua única |
| MinIO | distribuído (4+ nós no Helm) | — |

O ponto de saturação esperado primeiro é o banco do GLPI. Por isso o Metabase
deve apontar para a **réplica de leitura** (`values-mariadb.yaml` já provisiona
uma): relatório pesado não pode competir com abertura de chamado.

## 7. Requisitos não-funcionais → onde são atendidos

| Requisito | Implementação |
|---|---|
| Disponibilidade 99,5% | healthchecks em todos os serviços, `restart: unless-stopped`, PDB e HPA no K8s, alerta `ServicoIndisponivel` |
| Escala 10x | profiles, HPA, workers separados, réplica de leitura, filas |
| Resposta < 500ms | alerta `LatenciaAcimaDoRequisito` sobre o p95 do Traefik |
| MFA e TLS 1.2+ | Keycloak com `CONFIGURE_TOTP` obrigatório; `tls.options.default.minVersion: VersionTLS12` |
| Auditoria | eventos de admin no Keycloak, gravação de sessão no MinIO com retenção de 365 dias, logs no Loki |
| Portabilidade | tudo em container, sem serviço gerenciado de nuvem; Compose e Kubernetes a partir das mesmas imagens |

## 8. O painel unificado (portal)

Antes, cada serviço tinha a sua URL e o técnico decorava seis endereços. O
`portal` é a porta única: responde no domínio raiz (e em `portal.<DOMAIN>`),
serve um SPA React e faz proxy de `/api` para o `itsm-bridge`.

```
navegador ──► portal (nginx)  ──► /            SPA (React)
                              └─► /api/portal  itsm-bridge (mesma origem)
                    │
                    └─ iframe ──► glpi. / rmm. / chat. / n8n. / grafana.
```

**Por que proxy e não chamada direta ao `bridge.<DOMAIN>`**: mantendo tudo na
mesma origem não há CORS, o token não circula entre domínios e a API do painel
herda o controle de acesso do portal.

**O que é nativo e o que é embutido.** É nativo o que se ganha em consolidar —
o resumo de chamados (que atravessa status, prazo e técnico), a fila com filtro
e abertura, o detalhe com acompanhamento e solução, o cálculo de SLA, a prévia
de fatura e o status de toda a stack. O resto é a interface do próprio serviço,
aberta dentro do painel via iframe (GLPI, MeshCentral, Chatwoot, n8n, Grafana)
ou em nova aba quando o serviço não aceita ser enquadrado (Keycloak, MinIO,
Metabase). Reimplementar a UI do GLPI ou do Grafana seria manter um clone
desatualizado de cada um.

**Como o enquadramento é liberado.** O middleware `portal-embed@docker`
(definido nos labels do serviço `portal`) remove o `X-Frame-Options` das
respostas desses serviços e coloca no lugar
`Content-Security-Policy: frame-ancestors 'self' https://portal.<DOMAIN>
https://<DOMAIN>` — mais restritivo que o padrão, porque só o painel pode
enquadrar. Os cookies continuam funcionando porque portal e serviços são
subdomínios do mesmo site (`SameSite=Lax` não bloqueia same-site).

**Catálogo e status.** O `itsm-bridge` conhece o catálogo
(`app/portal.py`): slug, categoria, perfil do Compose, URL pública derivada de
`BRIDGE_PORTAL_DOMAIN` e como sondar o serviço por dentro da rede — HTTP para os
serviços web, TCP para o relay do RustDesk. As sondas rodam em paralelo, com
cache curto, e alimentam tanto a página de status quanto o alerta vermelho no
menu. `BRIDGE_PORTAL_PROFILES` filtra o catálogo para os perfis que o operador
realmente subiu.

**Sessão.** O login do painel valida usuário e senha no próprio GLPI
(`initSession` com Basic auth) e devolve um JWT HS256 assinado com
`BRIDGE_PORTAL_SECRET` — não há base de usuários paralela. Quando o portal está
atrás de um proxy OIDC (oauth2-proxy, Authelia), o bridge aceita a identidade
repassada no cabeçalho, desde que `BRIDGE_PORTAL_TRUST_FORWARDED_AUTH=true`.
Detalhes em [04-integracoes.md](04-integracoes.md#10-painel-unificado-portal).
