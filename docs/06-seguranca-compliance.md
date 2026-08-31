# Segurança e compliance

## 1. Identidade e acesso

**SSO centralizado (Keycloak).** O realm `itsm` já vem com:

* política de senha: 12+ caracteres, maiúscula, minúscula, dígito, especial,
  diferente do usuário, histórico de 5;
* proteção contra força bruta: 5 falhas → espera progressiva até 15 min;
* **TOTP obrigatório** (`CONFIGURE_TOTP` como ação padrão) — atende ao requisito
  de MFA para agentes. Como a ação vale para todos os usuários do realm, clientes
  do portal também configuram MFA; se isso for atrito demais na sua operação,
  mova os clientes para um realm próprio em vez de desligar o MFA dos agentes;
* eventos de login e eventos administrativos habilitados com retenção de 90 dias
  (rastreabilidade de alteração de permissão).

**Papéis.** `admin-itsm`, `supervisor`, `agente`, `cliente` — mapeados para
grupos e projetados para casar com os perfis do GLPI. O princípio é o de menor
privilégio: o usuário de serviço da API tem permissão de criar chamados, não de
administrar o sistema.

## 2. Rede

* TLS termina no Traefik; `minVersion: VersionTLS12` e cipher suites modernas.
* HTTP redireciona para HTTPS permanentemente.
* HSTS com `max-age` de 1 ano e `includeSubdomains`.
* Rede `itsm_data` é `internal: true`: bancos, Redis e RabbitMQ não têm rota
  para a internet nem porta publicada no host.
* Middleware `internal-only` (faixas RFC1918) disponível para rotas
  administrativas — aplique no dashboard do Traefik, no console do MinIO e, se
  o Chatwoot não assinar seus webhooks, na rota `/webhooks/chatwoot`.
* No Kubernetes, `NetworkPolicy` restringe o namespace `itsm-data` a tráfego
  vindo de `itsm`.

Exceção consciente: RustDesk publica 21115-21119 (TCP/UDP) diretamente — é
protocolo próprio, não HTTP, e não passa por proxy reverso. Restrinja por
firewall às faixas de origem dos clientes quando possível.

## 3. Segredos

* Nada de segredo versionado: `.env` está no `.gitignore`; o repositório carrega
  apenas `.env.example` com placeholders `troque-me-*`.
* `./scripts/gen-secrets.sh` gera valores aleatórios e aplica permissão 600.
* Em Kubernetes, use External Secrets Operator, Sealed Secrets ou SOPS —
  `deploy/k8s/base/secrets.example.yaml` é só referência.
* Os `secret` dos clients do realm (`TROQUE-ESTE-SECRET-*`) precisam ser
  trocados antes de qualquer exposição pública.

**Verificação rápida antes de subir em produção:**

```bash
grep -rn "troque-me\|TROQUE-ESTE" .env deploy/compose/keycloak/realms/ && \
  echo "AINDA HÁ PLACEHOLDERS — não suba assim"
```

## 4. Webhooks

Assinatura HMAC-SHA256 sobre o corpo bruto, comparada em tempo constante
(`hmac.compare_digest`). Sem segredo configurado a validação é **desligada** —
isso é intencional para desenvolvimento e perigoso em produção. O
`readyz` do bridge não bloqueia por isso; a checagem é sua, no deploy:

```bash
test -n "$BRIDGE_RMM_WEBHOOK_SECRET" || { echo "webhook sem segredo"; exit 1; }
```

## 5. Auditoria

| O que | Onde fica | Retenção |
|---|---|---|
| Login e alteração de permissão | eventos do Keycloak | 90 dias |
| Alterações em chamados e ativos | histórico nativo do GLPI | vida do registro |
| Sessões de acesso remoto | gravação no bucket `session-recordings` | 365 dias |
| Chamados criados por automação | log do bridge + métrica `itsm_bridge_tickets_created_total` | logs 30 dias (Loki) |
| Webhooks rejeitados | `itsm_bridge_webhook_rejected_total` + log | 30 dias |

Toda sessão de acesso remoto deve ser rastreável até um chamado: é o que torna
defensável, em auditoria, o acesso de um técnico à máquina de um cliente.

## 6. Dados pessoais (LGPD)

O sistema armazena dados pessoais de contatos e de agentes (nome, e-mail,
telefone) e conteúdo de conversas.

* **Minimização:** não colete CPF/documento em chamado quando não for
  necessário ao atendimento.
* **Retenção:** defina o prazo de guarda de chamados encerrados por contrato e
  aplique a purga pelas tarefas automáticas do GLPI.
* **Titular:** pedidos de exclusão exigem varrer GLPI, Chatwoot e backups —
  documente o procedimento antes do primeiro pedido, não depois.
* **Transferência internacional:** com tudo self-hosted, os dados ficam onde
  seus servidores estiverem; se usar WhatsApp Business API, os metadados
  trafegam pela Meta — declare isso no contrato com o cliente.

## 7. Licenças

| Componente | Licença | Implicação prática |
|---|---|---|
| GLPI, ERPNext | GPL | uso e distribuição livres; publicar modificações distribuídas |
| MinIO, RustDesk, Metabase, iTop | AGPL | modificar **e oferecer como serviço** obriga publicar as modificações |
| MeshCentral, Keycloak, Prometheus, Grafana | Apache 2.0 | permissiva |
| Chatwoot | MIT | permissiva |
| n8n | Sustainable Use License | uso interno permitido; revenda do n8n como produto, não |

Operar um MSP com estes softwares **sem modificá-los** não dispara a obrigação
da AGPL. Customização profunda (fork do GLPI, patch no MinIO) oferecida como
serviço a terceiros dispara — nesse caso, publique as modificações ou revise
com o jurídico antes. O código deste repositório (`itsm-bridge`, manifests,
scripts) é seu e não altera a licença de nenhum dos componentes acima.

## 8. Backups

* Envio automático para o bucket `backups` (versionado, expiração em 90 dias).
* Criptografia em repouso: habilite SSE-KMS no MinIO ou criptografe os dumps
  antes do envio (`gpg --symmetric`) — o requisito da especificação é backup
  criptografado, e o script entrega o dump em claro por padrão.
* Restore drill trimestral obrigatório (ver runbook).

## 9. Endurecimento pendente (assumido, não implementado)

Itens conscientemente fora do escopo desta entrega, listados para não virarem
surpresa:

1. **Criptografia dos dumps** no `backup.sh` (hoje: gzip sem cifra).
2. **SSO efetivo no GLPI** — o realm está pronto; falta instalar e configurar o
   plugin OIDC na instância (requer a UI do GLPI no ar).
3. **Rate limit por rota** — o middleware existe, mas não está aplicado nas
   rotas de login; avalie o volume real antes de calibrar.
4. **WAF/ModSecurity** à frente do Traefik, se o portal do cliente ficar
   exposto na internet pública.
