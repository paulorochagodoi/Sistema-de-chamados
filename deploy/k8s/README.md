# Deploy em Kubernetes (Fase 5)

O Compose é o caminho para piloto e ambientes pequenos. Quando o volume exigir
escala horizontal real, esta pasta é o ponto de partida.

## Divisão de responsabilidades

| Camada | Como é entregue | Onde |
|---|---|---|
| Cargas próprias (GLPI web, GLPI cron, itsm-bridge, Ingress, NetworkPolicy) | manifests Kustomize | `base/` |
| Componentes com estado (MariaDB, Redis, MinIO, PostgreSQL) | Helm charts oficiais + values | `helm/` |
| Chatwoot, n8n, Keycloak, Metabase, Prometheus/Grafana/Loki | Helm charts oficiais dos projetos | — |

Não reescrevemos charts que já existem: o valor está na integração, não em
reimplementar operadores de banco.

## Ordem de instalação

```bash
kubectl apply -f base/namespace.yaml

# 1) segredos (External Secrets / Sealed Secrets / SOPS — nunca em Git)
kubectl create secret generic glpi-db -n itsm \
  --from-literal=username=glpi --from-literal=password="$(openssl rand -hex 24)"

# 2) dados
helm install mariadb bitnami/mariadb -n itsm-data -f helm/values-mariadb.yaml
helm install redis   bitnami/redis   -n itsm-data -f helm/values-redis.yaml
helm install minio   bitnami/minio   -n itsm-data -f helm/values-minio.yaml
helm install postgresql bitnami/postgresql -n itsm-data   # Keycloak/Chatwoot/n8n/Metabase

# 3) aplicação
kubectl apply -k base/
```

## Pontos de atenção

**PVC ReadWriteMany.** O `glpi-data` é compartilhado entre o pod web e o pod de
cron. Sem uma storage class RWX (NFS, CephFS, EFS, Azure Files), fixe o web em
`replicas: 1` — ou migre os anexos para o MinIO via plugin S3 do GLPI e reduza o
volume compartilhado a configuração.

**Cron único.** `glpi-cron` usa `strategy: Recreate` e uma réplica. Duas
instâncias de cron duplicam e-mails, escalonamentos e sincronização de
inventário.

**HPA.** Configurado por CPU/memória. Para escalar por profundidade de fila
(cenário mais fiel para picos de abertura de chamado), use KEDA com o
`ScaledObject` apontando para a fila do RabbitMQ ou para
`itsm_bridge_webhook_duration_seconds` no Prometheus.

**Isolamento por cliente.** Clientes enterprise que exigem isolamento total
ganham namespace e banco dedicados: replique `base/` com um overlay Kustomize
por cliente. O padrão continua sendo isolamento lógico por entidade do GLPI —
uma instalação, muitos clientes.

**Imagem do itsm-bridge.** `base/itsm-bridge.yaml` referencia
`ghcr.io/OWNER/itsm-bridge:1.0.0`. Publique a imagem do `services/itsm-bridge`
no seu registry e ajuste o campo (ou use `images:` no Kustomize).
