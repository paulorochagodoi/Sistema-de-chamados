# Especificação de Sistema ITSM Containerizado e Escalável
### Baseado em referências de mercado (Tiflux, SolarWinds Service Desk, Zendesk) com stack 100% open-source

> Documento de origem do projeto, preservado como referência. As decisões de
> implementação que divergem dele (e o porquê) estão em
> [08-decisoes-tecnicas.md](08-decisoes-tecnicas.md).

---

## 1. Visão Geral

Sistema de ITSM (IT Service Management) para equipes de TI internas e MSPs (Managed Service Providers), cobrindo o ciclo completo de atendimento: chamados, gestão de clientes, inventário de máquinas/ativos, contratos e faturamento, acesso remoto integrado e monitoramento proativo — tudo containerizado, multi-tenant e horizontalmente escalável.

**Referências de mercado analisadas:** Tiflux, SolarWinds Service Desk, Zendesk (ITSM/Zendesk for IT).

---

## 2. Módulos Funcionais

### 2.1 Gestão de Chamados (Service Desk / Help Desk)
- Abertura multicanal: e-mail, portal do cliente, chat, WhatsApp, telefone, formulário embutido
- Categorização por Incidente, Requisição de Serviço, Problema e Mudança (ITIL)
- SLA configurável por cliente/contrato, com escalonamento automático
- Atribuição automática por regras (round-robin, carga de trabalho, especialidade)
- Apontamento de horas por chamado (billável x não billável)
- Fusão/vínculo de chamados duplicados, chamados-filho
- Aprovações (workflow de aprovação de mudanças/requisições)

### 2.2 Gestão de Clientes (Multi-tenant / Multi-empresa)
- Cadastro de empresas-clientes com hierarquia (matriz/filiais, contatos, departamentos)
- Visão isolada por cliente (dados segregados) — essencial para operação MSP
- Portal de autoatendimento por cliente (abertura e acompanhamento de chamados)
- Histórico consolidado de interações por cliente

### 2.3 Gestão de Ativos / CMDB
- Inventário automático de máquinas (hardware, SO, softwares instalados)
- Descoberta ativa de rede (agentes + varredura SNMP/WMI)
- Controle de licenças de software e auditoria de conformidade
- Relacionamento entre ativos, serviços, contratos e chamados (CMDB relacional)
- Gestão de ciclo de vida do ativo (compra → uso → descarte)

### 2.4 Gestão de Contratos e Faturamento
- Contratos vinculados a clientes, SLAs e ativos
- Modelos de cobrança: por chamado, por hora, por ativo monitorado, recorrência fixa
- Faturamento automático a partir dos apontamentos de horas
- Alertas de vencimento/renovação de contrato e de licenças
- Integração com emissores de nota fiscal/gateway de pagamento

### 2.5 Acesso Remoto Integrado
- Acesso remoto direto a partir do chamado (sem sair da ferramenta)
- Suporte não supervisionado (fleet/inventário) e supervisionado (sob demanda, com consentimento do usuário)
- Gravação de sessão para auditoria (compliance)
- Transferência de arquivos e terminal remoto

### 2.6 Monitoramento Proativo (RMM)
- Monitoramento de CPU, disco, memória, serviços críticos, patches
- Gatilhos automáticos que abrem chamados a partir de alertas
- Automação de scripts remotos (manutenção, correções recorrentes)
- Wake-on-LAN, gerenciamento de energia

### 2.7 Base de Conhecimento e Autoatendimento
- Artigos internos e públicos (KB interna x KB do cliente)
- Catálogo de serviços (o que pode ser solicitado, com SLA e aprovações)
- Chatbot/IA para triagem inicial e sugestão de artigos

### 2.8 Automação e Workflows (ITIL)
- Motor de regras (gatilhos → condições → ações)
- Gestão de Mudanças (Change Advisory Board) com aprovação formal
- Gestão de Problemas (causa raiz vinculada a incidentes recorrentes)
- Integrações via webhook/API com ERPs, WhatsApp, GitHub, Slack

### 2.9 Relatórios, Dashboards e BI
- Indicadores em tempo real: SLA cumprido, tempo médio de resolução, satisfação (CSAT)
- Dashboards executivos por cliente e por técnico
- Exportação e relatórios agendados

### 2.10 Gestão de Equipes e Permissões
- Grupos de permissão granulares, papéis (agente, supervisor, admin, cliente)
- Métricas de carga de trabalho por colaborador
- Escalas e turnos de atendimento

### 2.11 Atendimento Omnichannel e IA
- Chat ao vivo, WhatsApp Business, redes sociais, e-mail unificados em uma caixa
- Agente de IA para respostas automáticas, resumo de chamados e sugestão de solução

---

## 3. Mapeamento de Funcionalidade → Solução Open-Source

| Módulo | Solução recomendada | Licença | Papel na arquitetura |
|---|---|---|---|
| Núcleo ITSM (chamados, CMDB, contratos, KB, catálogo de serviços) | **GLPI** | GPL | Hub central — nativamente multi-entidade (multi-tenant) |
| ITIL avançado (opcional) | **iTop** | AGPL | Alternativa ao GLPI para times com processos ITIL maduros |
| Atendimento omnichannel | **Chatwoot** | MIT | Caixa de entrada unificada, integrada ao GLPI via API/webhook |
| Acesso remoto sob demanda | **RustDesk** (self-hosted) | AGPL | Sessões de suporte pontual, iniciadas a partir do chamado |
| Fleet + acesso não supervisionado + RMM | **MeshCentral** / **Tactical RMM** | Apache 2.0 / AGPL | Inventário, terminal remoto, Wake-on-LAN, alertas → chamado |
| Automação/orquestração | **n8n** | Sustainable Use License | Barramento de integração |
| Identidade e SSO | **Keycloak** | Apache 2.0 | Autenticação única para agentes, clientes e portais |
| Faturamento/ERP | **ERPNext** | GPL | Módulo financeiro/fiscal, integrado via API |
| BI e dashboards | **Metabase** | AGPL | Dashboards de SLA, faturamento e desempenho |
| Observabilidade | **Prometheus + Grafana + Loki** | Apache 2.0 | Métricas e logs dos containers |
| Banco relacional | **PostgreSQL** / **MariaDB** | PostgreSQL License / GPL | Persistência principal |
| Cache / fila | **Redis** + **RabbitMQ** | BSD / MPL 2.0 | Sessões, filas de jobs assíncronos |
| Armazenamento de objetos | **MinIO** | AGPL | Anexos e backups (compatível com S3) |
| Busca full-text | **OpenSearch** | Apache 2.0 | Busca em tickets e artigos de KB |
| Proxy reverso / Ingress | **Traefik** / **NGINX Ingress** | MIT / BSD | Roteamento e TLS |
| Orquestração | **Kubernetes** / Docker Compose | Apache 2.0 | Escalonamento horizontal, self-healing |

> Observação sobre licenças: AGPL exige que, se o código for modificado e oferecido como serviço para terceiros, as modificações sejam publicadas. Para uso interno (equipe de TI própria ou MSP oferecendo o serviço, não revendendo o software em si), isso normalmente não é um bloqueio, mas vale revisão jurídica antes de customizações profundas em GLPI/iTop/Zammad/RustDesk/MeshCentral.

---

## 4. Arquitetura Técnica

### 4.1 Padrão arquitetural
Serviços containerizados comunicando-se via API REST/Webhooks, orquestrados em Kubernetes (produção) ou Docker Compose (piloto/ambientes menores).

```
                            ┌─────────────────────┐
                            │  Ingress / Traefik  │  ← TLS, roteamento
                            └──────────┬──────────┘
                                       │
        ┌──────────────┬───────────────┼──────────────┬───────────────┐
   ┌────▼────┐   ┌─────▼─────┐  ┌──────▼─────┐  ┌─────▼─────┐   ┌─────▼─────┐
   │  GLPI   │   │ Chatwoot  │  │MeshCentral │  │ Keycloak  │   │ Metabase  │
   │(núcleo) │   │(omnichan.)│  │  (RMM)     │  │  (SSO)    │   │   (BI)    │
   └────┬────┘   └─────┬─────┘  └──────┬─────┘  └───────────┘   └─────┬─────┘
        └───────┬──────┴───────────────┘                              │
           ┌────▼──────┐  ┌────────────┐                      ┌───────▼─────┐
           │    n8n    │  │  RabbitMQ  │                      │ PostgreSQL/ │
           │(automação)│  │  + Redis   │                      │  MariaDB    │
           └───────────┘  └────────────┘                      └───────┬─────┘
                                                              ┌───────▼─────┐
                                                              │    MinIO    │
                                                              └─────────────┘
```

### 4.2 Multi-tenancy
- **Aplicação:** entidades nativas do GLPI — cada cliente isolado logicamente numa única instalação.
- **Infraestrutura (opcional):** namespace e banco dedicados por cliente enterprise.

### 4.3 Escalabilidade
- HPA para GLPI/Chatwoot/n8n conforme CPU/memória ou fila
- Container dedicado para cron/background
- Réplicas de leitura para relatórios pesados
- Cache de sessão via Redis
- Filas assíncronas (RabbitMQ) para e-mails, faturas e webhooks

### 4.4 Segurança e Compliance
- SSO via Keycloak (MFA, políticas de senha, AD/LDAP)
- TLS ponta a ponta via Ingress
- Gravação de sessões de acesso remoto
- Backups automatizados e testados (restore drill)
- Segregação de rede entre dados e aplicação

### 4.5 Observabilidade
- Métricas via Prometheus + Grafana
- Logs centralizados via Loki
- Alertas de indisponibilidade e de SLA em risco

---

## 5. Entidades Principais

- **Cliente** (empresa) → possui Contratos, Ativos, Contatos, Chamados
- **Contrato** → vinculado a Cliente, define SLA, modelo de cobrança, vigência
- **Ativo/Máquina** → vinculado a Cliente, com histórico de inventário, softwares, chamados
- **Chamado** → vinculado a Cliente, Ativo (opcional), Contrato, Agente, SLA
- **Agente/Técnico** → pertence a Grupo/Equipe, com permissões e métricas
- **Sessão de Acesso Remoto** → vinculada a Chamado e Ativo, com log de auditoria
- **Fatura** → gerada a partir de apontamentos de horas + Contrato

---

## 6. Requisitos Não-Funcionais

| Categoria | Requisito |
|---|---|
| Disponibilidade | 99,5% (mínimo) para o núcleo ITSM e portal do cliente |
| Escalabilidade | Suportar crescimento de 10x no volume de chamados sem redesenho |
| Performance | Abertura de chamado e resposta de API < 500ms sob carga normal |
| Segurança | MFA obrigatório para agentes, TLS 1.2+, backups criptografados |
| Auditoria | Todo acesso remoto e alteração de permissão logado e rastreável |
| Portabilidade | 100% dos serviços em containers, sem dependência de nuvem específica |

---

## 7. Roadmap de Implementação

1. **Fase 1 — Núcleo:** GLPI + banco + MinIO + Keycloak via Docker Compose, multi-entidade
2. **Fase 2 — Acesso remoto e monitoramento:** MeshCentral/Tactical RMM, alertas → chamados
3. **Fase 3 — Omnichannel:** Chatwoot (WhatsApp, chat do portal), automações via n8n
4. **Fase 4 — Faturamento:** apontamento → fatura, integração com contrato e ERPNext
5. **Fase 5 — Escala e observabilidade:** Kubernetes com HPA, Prometheus/Grafana, Metabase

---

## 8. Referências consultadas
- Documentação e blog Tiflux (gestão de contratos, acesso remoto, atendimento)
- Comparativos de mercado GLPI, iTop, Zammad e outros ITSM open-source
- Comparativos de acesso remoto self-hosted: Apache Guacamole, RustDesk, MeshCentral
- Documentação oficial de containerização do GLPI (Docker/Kubernetes/Helm)
