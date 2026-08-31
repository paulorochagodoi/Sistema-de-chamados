# Decisões técnicas (ADRs)

Registro curto das escolhas que divergem da especificação de origem ou que
custariam caro para reverter depois.

---

## ADR-001 — GLPI usa MariaDB, não PostgreSQL

**Contexto.** A especificação lista "PostgreSQL ou MariaDB" como banco
principal. O GLPI 10.x suporta **apenas MySQL/MariaDB** — não há driver
PostgreSQL no produto.

**Decisão.** Dois bancos no stack:

* **MariaDB 11.4** — exclusivo do GLPI, com `utf8mb4`, `READ-COMMITTED` e as
  tabelas de fuso horário liberadas para o usuário da aplicação.
* **PostgreSQL 16** — Keycloak, Chatwoot, n8n e Metabase, cada um com banco e
  usuário próprios.

**Consequências.** Dois motores para operar e fazer backup (o `backup.sh` cobre
os dois). Em troca, cada aplicação roda no banco que seus mantenedores
efetivamente testam. Consolidar em um só motor exigiria trocar o núcleo ITSM,
que é a decisão mais cara do sistema.

---

## ADR-002 — GLPI como núcleo, não iTop

**Contexto.** A especificação cita o iTop como alternativa para times com
processos ITIL maduros.

**Decisão.** GLPI.

**Justificativa.** Multi-entidade nativo (multi-tenant sem replicar
infraestrutura), inventário e CMDB no mesmo produto, contratos e catálogo de
serviços incluídos, imagem oficial mantida (`glpi/glpi`) com worker de cron
parametrizável. Para um MSP, "cliente = entidade" resolve o requisito mais
estruturante com configuração, não com código.

**Quando reconsiderar.** Se CAB formal e modelagem de CI profunda virarem o
centro da operação, o iTop é mais forte nesse recorte — mas a migração custa o
histórico de chamados.

---

## ADR-003 — Serviço próprio de integração (itsm-bridge) além do n8n

**Contexto.** A especificação coloca o n8n como barramento "sem código
customizado".

**Decisão.** Manter o n8n como orquestrador e adicionar um serviço FastAPI
próprio para as regras que precisam de teste automatizado.

**Justificativa.** Três regras não cabem bem em workflow visual:

1. deduplicação/correlação de alertas (estado com TTL, compartilhado entre
   réplicas);
2. cálculo de SLA com janela de atendimento, fim de semana e feriado;
3. faturamento com arredondamento por apontamento, franquia, excedente,
   desconto e imposto.

Erro em qualquer uma vira chamado duplicado, SLA furado ou nota fiscal errada.
No bridge, cada regra tem teste; num workflow, a verificação seria manual.

**Consequências.** Um serviço a mais para manter e publicar como imagem. O n8n
continua dono do "quando" e do "para quem notificar"; o bridge, do "quanto" e
do "quando vence".

---

## ADR-004 — Cron do GLPI em container separado

**Decisão.** `glpi` sobe com `GLPI_CRONTAB_ENABLED=0`; `glpi-cron` sobe com
`=1`, réplica única e `strategy: Recreate` no Kubernetes.

**Justificativa.** Escalar o web com o cron embutido faria N réplicas
executarem as mesmas tarefas: e-mails duplicados, escalonamento duplicado,
sincronização de inventário concorrente. É o mesmo motivo pelo qual a própria
imagem oficial expõe essa variável.

---

## ADR-005 — MeshCentral e RustDesk, os dois

**Decisão.** MeshCentral para acesso **não supervisionado** (fleet gerenciado,
inventário, terminal, Wake-on-LAN) e RustDesk para acesso **sob demanda**
(máquina não gerenciada, com consentimento na ponta).

**Justificativa.** São casos de uso diferentes, ambos na especificação. Forçar
um só significaria instalar agente permanente em máquina de terceiro (excesso)
ou pedir consentimento manual para manutenção de madrugada (inviável).

**Consequências.** RustDesk publica portas TCP/UDP diretas, fora do Traefik —
protocolo próprio não passa por proxy HTTP. Restrinja por firewall.

---

## ADR-006 — Correlação de alertas no Redis, com TTL

**Decisão.** `rmm:<alert_id> → ticket_id` no Redis, TTL de 15 min (ajustável).
Sem Redis, fallback em memória.

**Justificativa.** Deduplicar em banco exigiria tabela e limpeza; em memória
não sobrevive a réplicas nem a restart. TTL curto é proposital: se o problema
persiste depois da janela, um novo chamado é informação legítima, não ruído.

**Consequências.** Reiniciar o bridge sem Redis perde a correlação — a
normalização do alerta não encontra o chamado e é registrada como `ignored`.
Por isso `BRIDGE_REDIS_URL` está configurado por padrão no Compose.

---

## ADR-007 — Alerta resolvido não fecha o chamado

**Decisão.** `status: resolved` registra acompanhamento e libera a dedupe, mas
não encerra o chamado.

**Justificativa.** Disco que voltou a ter espaço porque um log rotacionou não é
problema resolvido. Fechar automaticamente esconde incidente recorrente e
destrói a base da gestão de problemas (causa raiz). O técnico encerra.

---

## ADR-008 — Configuração estática do Traefik por CLI, não por arquivo

**Decisão.** Flags no `command:` do serviço; o arquivo em `traefik/dynamic/`
carrega só a configuração dinâmica.

**Justificativa.** O Traefik lê a configuração estática de **uma** fonte (CLI,
env ou arquivo — não mescladas). Com CLI, o Compose interpola `${ACME_EMAIL}` e
`${TRAEFIK_DASHBOARD}` do `.env`; com arquivo estático, não haveria como
parametrizar sem template externo.

---

## ADR-009 — Profiles do Compose espelham as fases do roadmap

**Decisão.** `core`, `rmm`, `omnichannel`, `automation`, `bi`, `observability`.

**Justificativa.** Um piloto sobe 9 containers, não 25. A adoção segue o
roadmap sem manter arquivos de compose divergentes por fase — que sempre
acabam desatualizados entre si.

---

## ADR-010 — Kustomize para o que é nosso, Helm para o que é de terceiros

**Decisão.** `deploy/k8s/base/` traz GLPI, bridge, Ingress e NetworkPolicy;
bancos, cache e objetos vêm de charts oficiais com values versionados.

**Justificativa.** Reescrever o operador de MariaDB ou de MinIO não agrega
nada: são projetos maduros. O valor está na integração e nas cargas próprias.

**Consequência.** O `glpi-data` precisa de storage class **ReadWriteMany**
(web + cron compartilham `/var/glpi`). Sem RWX, fixe o web em uma réplica ou
mova os anexos para o MinIO via plugin S3 do GLPI.
