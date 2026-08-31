# Modelo de dados

O modelo conceitual da especificação é realizado majoritariamente **dentro do
GLPI** — não criamos um banco paralelo para o que ele já modela. O que o bridge
mantém é apenas estado de integração (correlação alerta→chamado, com TTL).

## 1. Entidades e onde vivem

| Entidade conceitual | Onde é armazenada | Objeto |
|---|---|---|
| Cliente (empresa) | GLPI | `Entity` (hierárquica: matriz → filial) |
| Contato do cliente | GLPI | `User` vinculado à entidade + `Contact` |
| Contrato | GLPI | `Contract` (+ `Contract_Item` para vincular ativos) |
| SLA | GLPI | `SLA`/`SLM` por entidade; o bridge calcula prazos fora da grade padrão |
| Ativo / Máquina | GLPI | `Computer`, `NetworkEquipment`, `Printer`, `Software` |
| Inventário automático | MeshCentral → GLPI | agente reporta; sincronização via API |
| Chamado | GLPI | `Ticket` (+ `Item_Ticket`, `ITILFollowup`, `ITILSolution`) |
| Apontamento de horas | GLPI | `TicketTask.actiontime` (billável via categoria/campo) |
| Agente / Técnico | Keycloak (identidade) + GLPI (perfil) | `User` + `Profile` + `Group` |
| Sessão de acesso remoto | MeshCentral (gravação → MinIO) | evento + arquivo em `session-recordings` |
| Fatura | itsm-bridge (cálculo) → ERP (emissão) | `Invoice` (transiente) / documento no ERPNext |
| Conversa omnichannel | Chatwoot | `Conversation` espelhada como `Ticket` |
| Correlação alerta→chamado | Redis | chave `rmm:<alert_id>` → `ticket_id`, com TTL |

## 2. Relacionamentos

```
Entity (Cliente)
  ├── User (contatos e agentes com acesso à entidade)
  ├── Contract ──┬── Contract_Item ── Computer/Software (ativos cobertos)
  │              └── SLA (prazos por prioridade)
  ├── Computer (CMDB) ──┬── Software instalado
  │                     └── Item_Ticket ── Ticket
  └── Ticket ──┬── ITILFollowup (interações, incluindo espelho do chat)
               ├── TicketTask (apontamento de horas → faturamento)
               ├── ITILSolution
               └── Ticket_Ticket (duplicidade, chamado-pai/filho)
```

## 3. Estruturas próprias do bridge

Nenhuma tabela: o bridge é stateless. O que ele guarda é efêmero.

**Correlação de alertas (Redis).**

| Chave | Valor | TTL padrão | Motivo |
|---|---|---|---|
| `rmm:<alert_id>` | `ticket_id` | 900s (`BRIDGE_DEDUPE_TTL_SECONDS`) | dedupe e correlação da normalização |
| `chatwoot:<conversation_id>` | `ticket_id` | 604800s (7 dias) | manter a conversa no mesmo chamado |

Sem Redis, o bridge cai para memória local — aceitável em instância única, mas
perde correlação no restart e não funciona com múltiplas réplicas.

**Modelos de cálculo (`services/itsm-bridge/app/models.py`).** São contratos de
API, não persistência: `Contract`, `TimeEntry`, `Invoice`, `InvoiceLine`,
`BusinessHours`, `RMMAlert`, `ChatwootEvent`.

## 4. Contrato e faturamento

O `Contract` que o bridge recebe é a projeção do contrato do GLPI/ERP nos
campos que afetam o cálculo:

| Campo | Efeito na fatura |
|---|---|
| `billing_model` | `hourly`, `per_ticket`, `per_asset`, `fixed`, `fixed_plus_hourly` |
| `hourly_rate`, `per_ticket_rate`, `per_asset_rate`, `fixed_amount` | preço unitário de cada modelo |
| `included_hours` | franquia; só o excedente é cobrado em `fixed_plus_hourly` |
| `minimum_billable_minutes` | mínimo cobrado por atendimento (ex.: 30 min) |
| `rounding_increment_minutes` | múltiplo de arredondamento (ex.: 15 min) |
| `discount_percent`, `tax_percent` | aplicados nessa ordem: desconto sobre o subtotal, imposto sobre o líquido |
| `valid_from`, `valid_until` | vigência; período fora dela é recusado |

O arredondamento é **por apontamento**, não sobre o total — é o que o cliente
confere linha a linha na fatura. `TimeEntry.rate_override` gera linha própria
(plantão, deslocamento, especialista).

## 5. SLA

`BusinessHours` descreve a janela do contrato: `start`, `end`, `workdays`
(0=segunda … 6=domingo), `holidays` e `around_the_clock` para 24x7.

Regras: chamado aberto fora da janela só começa a consumir SLA na próxima
abertura; fim de semana e feriado não consomem prazo; contrato 24x7 usa tempo
corrido. Um prazo já estourado conta como "em risco" — o escalonamento não pode
parar de disparar justamente depois de furar o SLA.

## 6. Onde ficam os binários

| Conteúdo | Bucket MinIO | Retenção |
|---|---|---|
| Anexos de chamado | `glpi-attachments` | vida do chamado |
| Mídia das conversas | `chatwoot-uploads` | política do Chatwoot |
| Gravações de acesso remoto | `session-recordings` | 365 dias (compliance) |
| Dumps e backups | `backups` | 90 dias, versionado |

Nenhum bucket é público: acesso sempre por credencial ou URL assinada.
