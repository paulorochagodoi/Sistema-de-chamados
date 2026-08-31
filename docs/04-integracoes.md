# Integrações

Referência dos contratos de API do `itsm-bridge` e do que configurar em cada
sistema para as integrações funcionarem.

## 1. Autenticação dos webhooks

Todo webhook é assinado com HMAC-SHA256 sobre o **corpo bruto**, no cabeçalho
`X-ITSM-Signature: sha256=<hex>`.

```bash
BODY='{"alert_id":"a-1","hostname":"srv","check":"cpu","severity":"high"}'
SIG="sha256=$(printf '%s' "$BODY" | openssl dgst -sha256 -hmac "$BRIDGE_RMM_WEBHOOK_SECRET" -r | cut -d' ' -f1)"

curl -X POST https://bridge.exemplo.com.br/webhooks/rmm/alert \
  -H "Content-Type: application/json" -H "X-ITSM-Signature: $SIG" -d "$BODY"
```

Sem segredo configurado a validação é desativada — só para desenvolvimento.
Em produção, defina `BRIDGE_RMM_WEBHOOK_SECRET` e
`BRIDGE_CHATWOOT_WEBHOOK_SECRET` (ver [06-seguranca-compliance.md](06-seguranca-compliance.md)).

## 2. GLPI

### 2.1 Habilitar a API

1. **Configurar → Geral → API**: ative "Habilitar API REST" e "Habilitar login
   com credenciais externas".
2. Crie um **App-Token** (cliente de API) com a faixa de IP do bridge.
3. No usuário de serviço (perfil com permissão de criar chamados em todas as
   entidades), gere o **user_token** em *Preferências → API*.
4. Preencha no `.env`:

```dotenv
GLPI_APP_TOKEN=...
GLPI_USER_TOKEN=...
```

O bridge abre uma sessão por requisição (`initSession`) e sempre a encerra
(`killSession`) — o GLPI limita sessões simultâneas.

### 2.2 Mapeamento de severidade

| Severidade do alerta | Urgência/impacto no GLPI | Tipo |
|---|---|---|
| `critical` | 5 (muito alta) | Incidente |
| `high` | 4 (alta) | Incidente |
| `warning` | 3 (média) | Incidente |
| `low` | 2 (baixa) | Incidente |
| `info` | 1 (muito baixa) | Incidente |

Conversas do Chatwoot entram como **Requisição** (tipo 2), não incidente.

## 3. RMM → chamado

`POST /webhooks/rmm/alert`

```json
{
  "alert_id": "mesh-7789",
  "status": "firing",
  "severity": "critical",
  "hostname": "srv-fileserver",
  "check": "disk-free",
  "message": "Espaço livre em C: abaixo de 5%",
  "metric_value": 3.2,
  "threshold": 5.0,
  "asset_serial": "SN-ABC123",
  "client_code": "ACME",
  "occurred_at": "2026-08-31T03:14:00"
}
```

| Campo | Obrigatório | Observação |
|---|---|---|
| `alert_id` | sim | chave de deduplicação; deve ser estável na origem |
| `hostname`, `check` | sim | compõem o título do chamado |
| `status` | não | `firing` (padrão) ou `resolved` |
| `severity` | não | padrão `warning` |
| `client_code` | não | resolvido para entidade do GLPI |
| `entity_id` | não | entidade explícita; tem precedência sobre `client_code` |
| `asset_serial` | não | usado para vincular o ativo (busca por série, depois por nome) |

Respostas (`200`): `created`, `duplicate`, `updated` (normalização), `ignored`.
Erros: `401` assinatura, `422` payload, `502` GLPI indisponível.

**Deduplicação.** Enquanto a chave `rmm:<alert_id>` existir no Redis (TTL de
`BRIDGE_DEDUPE_TTL_SECONDS`, 15 min por padrão), repetições devolvem
`duplicate` com o `ticket_id` original. Alertas *flapping* não geram enxurrada
de chamados.

**Normalização.** `status: "resolved"` registra acompanhamento no chamado e
libera a correlação. O chamado **não** é fechado automaticamente — quem valida
causa raiz é o técnico.

### 3.1 Configurando no MeshCentral / Tactical RMM

* **Tactical RMM**: em *Alerts → Alert Templates*, adicione uma ação de webhook
  apontando para `https://bridge.<dominio>/webhooks/rmm/alert` com o corpo no
  formato acima e o cabeçalho de assinatura.
* **MeshCentral**: use o `webhook` de eventos ou um script agendado que POSTe o
  payload. Alternativa: passe pelo n8n
  (`automation/n8n/workflows/01-alerta-rmm-para-chamado.json`), que já filtra
  ruído (`severity: info`) e notifica o plantão em alertas críticos.

## 4. Chatwoot → chamado

Em *Configurações → Integrações → Webhooks*, aponte para
`https://bridge.<dominio>/webhooks/chatwoot` e assine os eventos
`conversation_created` e `message_created`.

* Primeira mensagem do cliente → cria o chamado (Requisição).
* Mensagens seguintes → acompanhamentos no mesmo chamado, por até 7 dias
  (`BRIDGE_CONVERSATION_TTL_SECONDS`).
* Mensagens do agente (`message_type: outgoing`) são ignoradas.

O Chatwoot não assina webhooks nativamente com HMAC; se
`BRIDGE_CHATWOOT_WEBHOOK_SECRET` estiver definido, coloque o n8n no meio para
assinar, ou restrinja a rota por IP no Traefik (middleware `internal-only`).

## 5. SLA

`POST /api/sla/deadline`

```json
{
  "opened_at": "2026-08-31T17:00:00",
  "response_minutes": 30,
  "resolution_minutes": 180,
  "business_hours": {
    "start": "08:00", "end": "18:00",
    "workdays": [0, 1, 2, 3, 4],
    "holidays": ["2026-09-07"],
    "around_the_clock": false
  }
}
```

```json
{
  "opened_at": "2026-08-31T17:00:00",
  "response_due_at": "2026-08-31T17:30:00",
  "resolution_due_at": "2026-09-01T10:00:00",
  "business_minutes_to_response": 30,
  "business_minutes_to_resolution": 180
}
```

`POST /api/sla/at-risk` responde `{ "at_risk", "breached", "business_minutes_remaining" }`
— é o gatilho de escalonamento do workflow 02.

## 6. Faturamento

`POST /api/billing/invoices/preview`

```json
{
  "contract": {
    "id": "CT-2026-014",
    "client": "ACME Ltda",
    "billing_model": "fixed_plus_hourly",
    "fixed_amount": "3000.00",
    "included_hours": "10",
    "hourly_rate": "200.00",
    "minimum_billable_minutes": 30,
    "rounding_increment_minutes": 15,
    "tax_percent": "5"
  },
  "period_start": "2026-08-01",
  "period_end": "2026-08-31",
  "time_entries": [
    { "ticket_id": 101, "minutes": 750, "billable": true, "performed_at": "2026-08-12" }
  ]
}
```

A resposta traz `lines[]` (mensalidade, excedente, desconto, imposto),
`subtotal`, `discount`, `tax`, `total`, `billable_minutes` e
`non_billable_minutes`. Nada é gravado: é uma prévia para revisão humana antes
da emissão fiscal.

## 7. Acesso remoto a partir do chamado

**Não supervisionado (MeshCentral).** Com `IFRAME=true`, a console do
MeshCentral abre embutida. Adicione no GLPI um link no formulário do chamado
apontando para o dispositivo:

```
https://rmm.<dominio>/?viewmode=11&gotodevice=<mesh-node-id>
```

Guarde o `mesh-node-id` num campo customizado do `Computer` na CMDB — o mesmo
inventário que o agente já alimenta.

**Sob demanda (RustDesk).** Portas 21115-21119 publicadas fora do Traefik
(TCP/UDP puro). O cliente informa ID e senha temporária ao técnico; a sessão
exige consentimento na ponta.

**Auditoria.** Habilite a gravação de sessão no MeshCentral e aponte o destino
para o bucket `session-recordings` (retenção de 365 dias já configurada).

## 8. Keycloak (SSO)

O realm `itsm` é importado no primeiro start
(`deploy/compose/keycloak/realms/itsm-realm.json`) com papéis `admin-itsm`,
`supervisor`, `agente`, `cliente`, política de senha, brute-force protection e
TOTP obrigatório.

Antes de subir em produção:

1. Troque os `secret` dos clients (`TROQUE-ESTE-SECRET-*`).
2. Ajuste `redirectUris`/`webOrigins` do `itsm.localhost` para o seu domínio:
   ```bash
   sed -i "s/itsm.localhost/seu-dominio.com.br/g" deploy/compose/keycloak/realms/itsm-realm.json
   ```
3. No GLPI, instale e configure o plugin de SSO OIDC apontando para
   `https://sso.<dominio>/realms/itsm`.

## 9. n8n

Workflows prontos em `automation/n8n/workflows/` (importe por
*Workflows → Import from File*):

| Arquivo | O que faz |
|---|---|
| `01-alerta-rmm-para-chamado.json` | recebe alerta, descarta ruído, chama o bridge, notifica plantão em crítico |
| `02-escalonamento-de-sla.json` | a cada 15 min avalia chamados abertos e escala os que estão em risco |
| `03-faturamento-mensal.json` | todo dia 1º monta a prévia de fatura por contrato para revisão |

Os workflows usam as variáveis `GLPI_API_URL`, `GLPI_APP_TOKEN`,
`GLPI_USER_TOKEN` e `BRIDGE_URL`, já injetadas no container do n8n. Os nós
`noOp` marcados como "notifica"/"revisão" são pontos de plugue: troque por
Slack, Teams, e-mail ou WhatsApp conforme o canal da equipe.
