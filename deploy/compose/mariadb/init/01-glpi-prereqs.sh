#!/bin/bash
# Pré-requisitos de banco do GLPI 10.x, aplicados no primeiro start do volume.
#
#  * O GLPI valida se o usuário da aplicação enxerga mysql.time_zone_name;
#    sem isso o diagnóstico acusa "Time zones seem not loaded" e o campo de
#    fuso horário fica vazio. As tabelas em si já são populadas pelo
#    entrypoint do MariaDB — aqui apenas concedemos leitura.
#  * Garante utf8mb4 no banco da aplicação.
set -euo pipefail

DB_NAME="${MARIADB_DATABASE:-glpi}"
DB_USER="${MARIADB_USER:-glpi}"

mariadb --user=root --password="${MARIADB_ROOT_PASSWORD}" <<SQL
GRANT SELECT ON \`mysql\`.\`time_zone_name\` TO '${DB_USER}'@'%';
ALTER DATABASE \`${DB_NAME}\` CHARACTER SET utf8mb4 COLLATE utf8mb4_unicode_ci;
FLUSH PRIVILEGES;
SQL

echo "[init] pré-requisitos do GLPI aplicados em ${DB_NAME} (usuário ${DB_USER})"
