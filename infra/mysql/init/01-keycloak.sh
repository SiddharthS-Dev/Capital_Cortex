#!/bin/sh
# Sourced by the mysql:8.4 entrypoint on first initialisation of the data volume only.
# Keycloak (KC_DB=mysql) needs its own database; MYSQL_DATABASE only creates the application schema.
# For an already-initialised volume, run the same two statements once as root.
# No `set -eu`: the entrypoint sources this file, so shell options would leak into it.

# MYSQL_PWD keeps the root password out of the process list (`-p<pw>` is visible in `ps`).
MYSQL_PWD="${MYSQL_ROOT_PASSWORD}" mysql --protocol=socket -uroot <<SQL
CREATE DATABASE IF NOT EXISTS keycloak CHARACTER SET utf8mb4 COLLATE utf8mb4_0900_ai_ci;
GRANT ALL PRIVILEGES ON keycloak.* TO '${MYSQL_USER}'@'%';
SQL
