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

Enquanto os tokens não existirem, o painel responde
`GLPI não configurado: defina BRIDGE_GLPI_APP_TOKEN` no login — é o passo que
falta, não um erro de instalação.

1. Entre no GLPI (`https://glpi.<DOMAIN>/`). Na instalação nova, o usuário é
   `glpi` com senha `glpi` — troque-a antes de qualquer outra coisa.
2. **Configurar → Geral → aba API**: ative "Habilitar API REST" e "Habilitar
   login com credenciais" — a segunda é o que permite ao painel autenticar as
   pessoas com usuário e senha do próprio GLPI. Salve.
3. Ainda na aba API, em **Clientes da API**, abra o cliente `full access from
   localhost` (ou crie um): deixe ativo, apague o filtro de IPv4 se o bridge
   não vier de 127.0.0.1, marque **Regenerar** ao lado de "Token da aplicação
   (app_token)" e salve. O valor gerado é o **App-Token**.
4. No usuário de serviço (um perfil com permissão de criar chamados em todas as
   entidades), vá em **Preferências → aba API**, clique em *Regenerar* na
   "Chave de API remota" e salve. Esse é o **User-Token**.
5. Registre os dois e aplique:

```bash
./scripts/configure.sh --glpi-app-token <app> --glpi-user-token <user> --yes
make reload SERVICE=itsm-bridge
```

Os valores ficam no `.env` como `GLPI_APP_TOKEN` e `GLPI_USER_TOKEN`; o Compose
os injeta no bridge como `BRIDGE_GLPI_APP_TOKEN` e `BRIDGE_GLPI_USER_TOKEN`.
Use `reload` (que é `up -d`), não `restart`: variável de ambiente nova só entra
quando o container é recriado.

Para conferir sem abrir o painel:

```bash
curl -k https://bridge.<DOMAIN>/readyz     # {"ready":true,...} quando os dois existem
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

## 10. Painel unificado (portal)

A API do painel vive no `itsm-bridge`, sob `/api/portal`, e o navegador a
alcança pela mesma origem do portal (`https://<DOMAIN>/api/portal/...`), via
proxy do nginx. Fora `/auth/login`, todo endpoint exige um usuário autenticado.

### 10.1 Sessão

```http
POST /api/portal/auth/login
Content-Type: application/json

{"username": "ana", "password": "..."}
```

```json
{
  "access_token": "eyJhbGciOiJIUzI1NiIs...",
  "token_type": "bearer",
  "expires_in": 28800,
  "user": {"id": 7, "username": "ana", "full_name": "Ana Técnica",
           "profile": "Técnico", "source": "glpi"}
}
```

As credenciais são validadas no GLPI (`initSession` com `Authorization: Basic`)
e a sessão do GLPI é encerrada em seguida: o painel guarda apenas a identidade.
O token é um JWT HS256 assinado com `BRIDGE_PORTAL_SECRET` e vale
`BRIDGE_PORTAL_SESSION_MINUTES` minutos. Nas demais chamadas, envie
`Authorization: Bearer <token>`.

`GET /api/portal/auth/me` devolve o usuário da sessão — é o que o SPA usa para
decidir entre mostrar o painel ou o formulário de login.

**SSO.** Com um proxy OIDC na frente do portal (oauth2-proxy, Authelia), ligue
`BRIDGE_PORTAL_TRUST_FORWARDED_AUTH=true`: o bridge passa a aceitar a identidade
do cabeçalho `X-Auth-Request-User` e o formulário some. Só ligue se ninguém além
do proxy alcançar o portal — um cabeçalho não é prova de nada por si só.

### 10.2 Catálogo e status

| Endpoint | Devolve |
|---|---|
| `GET /api/portal/services` | catálogo: slug, nome, categoria, perfil, URL pública, se pode ser embutido |
| `GET /api/portal/services/status` | `online`/`offline`/`unknown` e latência de cada serviço |

O status é sondado por dentro da rede do Compose (`http://glpi/`,
`http://keycloak:9000/health/ready`, TCP em `rustdesk-hbbs:21116`, …), com cache
de `BRIDGE_PORTAL_STATUS_TTL_SECONDS` segundos. Não depende de DNS externo nem
do certificado — um serviço pode estar de pé e o DNS errado, e a página mostra
exatamente isso.

### 10.3 Chamados

| Endpoint | O que faz |
|---|---|
| `GET /api/portal/tickets?status=notold&search=&limit=50&offset=0` | fila (status: id 1..6, `notold`, `old`, `all`) |
| `GET /api/portal/summary` | agregados do painel: por status, prioridade e técnico, mais vencidos e sem atribuição |
| `POST /api/portal/tickets` | abre chamado com quem está logado como solicitante |
| `GET /api/portal/tickets/{id}` | detalhe com acompanhamentos |
| `POST /api/portal/tickets/{id}/followups` | registra acompanhamento (assinado com o nome de quem escreveu) |
| `POST /api/portal/tickets/{id}/solution` | registra a solução e move para *solucionado* |

As leituras traduzem as *searchoptions* do GLPI (`{"1": "título", "12": 2, …}`)
para campos nomeados, e o conteúdo HTML dos chamados vira texto puro no bridge —
o painel nunca injeta HTML de terceiros na página.

O bridge fala com o GLPI pela conta de serviço (`GLPI_APP_TOKEN` /
`GLPI_USER_TOKEN`): o usuário autenticado define *quem pediu*, não com quais
permissões a operação corre. Se o seu caso exige permissão por usuário, coloque
o portal atrás do SSO e restrinja o perfil da conta de serviço.

### 10.4 Variáveis

| Variável (`.env`) | Efeito |
|---|---|
| `PORTAL_SECRET` | chave de assinatura das sessões (vazia = chave efêmera por processo) |
| `PORTAL_SESSION_MINUTES` | validade do token (padrão 480) |
| `PORTAL_PROFILES` | perfis do Compose que o menu deve listar |
| `PORTAL_TRUST_FORWARDED_AUTH` | aceita identidade repassada por proxy de SSO |
