#!/bin/bash
# Bootstrap do PostgreSQL: cria um banco e um usuário dedicados por serviço.
# Executado uma única vez, no primeiro start do volume postgres_data.
set -euo pipefail

create_db() {
  local db="$1" user="$2" password="$3"

  if [ -z "$password" ]; then
    echo "[init] senha vazia para '$user' — banco '$db' não criado" >&2
    return 0
  fi

  echo "[init] criando banco '$db' e usuário '$user'"
  psql -v ON_ERROR_STOP=1 --username "$POSTGRES_USER" --dbname postgres <<-SQL
	DO \$\$
	BEGIN
	  IF NOT EXISTS (SELECT FROM pg_roles WHERE rolname = '${user}') THEN
	    CREATE ROLE ${user} LOGIN PASSWORD '${password}';
	  END IF;
	END
	\$\$;
	SQL

  # CREATE DATABASE não roda dentro de bloco DO/transação
  if ! psql -tAc "SELECT 1 FROM pg_database WHERE datname = '${db}'" --username "$POSTGRES_USER" --dbname postgres | grep -q 1; then
    psql -v ON_ERROR_STOP=1 --username "$POSTGRES_USER" --dbname postgres \
      -c "CREATE DATABASE ${db} OWNER ${user} ENCODING 'UTF8'"
  fi

  psql -v ON_ERROR_STOP=1 --username "$POSTGRES_USER" --dbname postgres \
    -c "GRANT ALL PRIVILEGES ON DATABASE ${db} TO ${user}"
  # necessário no PG15+ : o schema public deixa de ser gravável por padrão
  psql -v ON_ERROR_STOP=1 --username "$POSTGRES_USER" --dbname "${db}" \
    -c "GRANT ALL ON SCHEMA public TO ${user}"
}

create_db keycloak keycloak "${KEYCLOAK_DB_PASSWORD:-}"
create_db chatwoot chatwoot "${CHATWOOT_DB_PASSWORD:-}"
create_db n8n      n8n      "${N8N_DB_PASSWORD:-}"
create_db metabase metabase "${METABASE_DB_PASSWORD:-}"

# Chatwoot exige a extensão pgcrypto/vector no seu próprio banco
psql -v ON_ERROR_STOP=1 --username "$POSTGRES_USER" --dbname chatwoot \
  -c "CREATE EXTENSION IF NOT EXISTS pgcrypto" || true

echo "[init] bancos de aplicação prontos"
