# Roadmap e estado atual

Legenda: ✅ entregue neste repositório · 🔧 configuração na UI do produto
(exige o serviço no ar) · ⬜ não iniciado

## Fase 1 — Núcleo ITSM

| Item | Estado |
|---|---|
| GLPI containerizado com cron isolado do web | ✅ |
| MariaDB com pré-requisitos do GLPI (utf8mb4, timezones, READ-COMMITTED) | ✅ |
| PostgreSQL com bancos separados por serviço | ✅ |
| MinIO com buckets, política de retenção e nenhum bucket público | ✅ |
| Keycloak com realm, papéis, MFA e política de senha | ✅ |
| Traefik com TLS, HSTS e redirecionamento | ✅ |
| Segregação de rede (dados sem rota externa) | ✅ |
| Entidades por cliente (multi-tenant) | 🔧 criar na UI do GLPI |
| SSO OIDC ligado no GLPI | 🔧 instalar plugin e apontar para o realm |
| Catálogo de serviços e KB | 🔧 conteúdo é do negócio |

**Critério de aceite:** `make up && make smoke` verde; login no GLPI; abertura
de chamado em uma entidade de cliente; anexo salvo.

## Fase 2 — Acesso remoto e monitoramento

| Item | Estado |
|---|---|
| MeshCentral atrás do Traefik, com iframe liberado para embutir no chamado | ✅ |
| RustDesk (hbbs + hbbr) para sessão sob demanda | ✅ |
| Alerta do RMM abre chamado, com dedupe e correlação | ✅ (`itsm-bridge`) |
| Vínculo automático do chamado ao ativo da CMDB | ✅ |
| Resolução de entidade pelo código do cliente | ✅ |
| Agentes instalados no parque | 🔧 |
| Gravação de sessão apontando para o MinIO | 🔧 configurar no MeshCentral |
| Wake-on-LAN e scripts remotos | 🔧 recurso nativo do MeshCentral |

**Critério de aceite:** derrubar um serviço numa máquina de teste e ver o
chamado nascer na entidade certa, com o ativo vinculado; repetir o alerta e
confirmar que não nasce um segundo chamado.

## Fase 3 — Omnichannel e automação

| Item | Estado |
|---|---|
| Chatwoot (web + worker) com storage no MinIO | ✅ |
| Conversa vira chamado; mensagens seguintes viram acompanhamento | ✅ |
| n8n em modo fila com worker dedicado | ✅ |
| Workflow de alerta → chamado com filtro de ruído | ✅ |
| Workflow de escalonamento de SLA a cada 15 min | ✅ |
| Canais (WhatsApp Business, e-mail, chat do portal) | 🔧 credenciais do cliente |
| Triagem por IA / sugestão de artigos | ⬜ |

**Critério de aceite:** mensagem enviada no canal de teste abre chamado; a
resposta do agente no Chatwoot chega ao cliente; chamado com prazo a vencer
dispara escalonamento.

## Fase 4 — Contratos e faturamento

| Item | Estado |
|---|---|
| Motor de faturamento (5 modelos de cobrança, franquia, arredondamento) | ✅ |
| Desconto, imposto e validação de vigência | ✅ |
| Workflow mensal de prévia de fatura por contrato | ✅ |
| Cadastro de contratos no GLPI (vigência, SLA, ativos cobertos) | 🔧 |
| Emissão fiscal (ERPNext ou gateway) | ⬜ ponto de integração pronto no workflow |
| Alertas de vencimento de contrato e licença | 🔧 tarefa nativa do GLPI |

**Critério de aceite:** apontamentos de um mês reproduzem, na prévia, a fatura
conferida manualmente — linha a linha.

## Fase 5 — Escala e observabilidade

| Item | Estado |
|---|---|
| Prometheus com alertas de disponibilidade, capacidade, latência e SLA | ✅ |
| Grafana provisionado (datasources + dashboard) | ✅ |
| Loki + Promtail coletando logs por serviço | ✅ |
| Métricas de negócio expostas pelo bridge | ✅ |
| Manifests Kubernetes (Deployment, HPA, PDB, NetworkPolicy, Ingress) | ✅ |
| Values de Helm para MariaDB (com réplica de leitura), Redis e MinIO | ✅ |
| Metabase para dashboards por cliente | ✅ (serviço) / 🔧 (perguntas e painéis) |
| Alertmanager com rota para plantão | ⬜ |
| KEDA para escalar por profundidade de fila | ⬜ |

**Critério de aceite:** derrubar um container e ver o alerta disparar; p95 do
Traefik visível no dashboard; `kubectl apply -k deploy/k8s/base/` sobe a
aplicação num cluster de teste.

## Fora de escopo (assumido)

* **Chatbot/IA de triagem** (2.11) — depende de decisão sobre provedor de LLM,
  custo por conversa e política de dados; nada foi implementado.
* **Descoberta ativa SNMP/WMI** (2.3) — recurso do GLPI Agent/FusionInventory,
  configurado na UI, sem código próprio necessário.
* **CAB formal / Gestão de Mudanças** (2.8) — o GLPI cobre com `Change` e
  aprovações; é parametrização de processo, não de infraestrutura.
* **Emissão de nota fiscal** — exige credenciais fiscais e homologação com o
  emissor; o workflow entrega a fatura calculada no ponto de integração.
