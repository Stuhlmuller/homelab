#!/bin/sh
# Synthetic data only. The entire test is invoked through the launcher.
set -eu
umask 077
mkdir /work/socket
initdb -D /work/db -U fixture --auth-local=trust --auth-host=reject --locale=C >/work/init.log
pg_ctl -D /work/db -l /work/postgres.log -w \
  -o '-c listen_addresses= -c unix_socket_directories=/work/socket' start
trap 'pg_ctl -D /work/db -m immediate -w stop >/dev/null' EXIT
psql -h /work/socket -U fixture -d postgres -v ON_ERROR_STOP=1 <<'SQL'
CREATE DATABASE fixture;
SQL
psql -h /work/socket -U fixture -d fixture -v ON_ERROR_STOP=1 <<'SQL'
CREATE TABLE recovery (id integer PRIMARY KEY);
INSERT INTO recovery VALUES (7);
SQL
pg_dump -h /work/socket -U fixture -d fixture -Fc -f /work/recovery.dump
dropdb -h /work/socket -U fixture fixture
pg_restore -h /work/socket -U fixture -d postgres --create --exit-on-error /work/recovery.dump
test "$(psql -h /work/socket -U fixture -d fixture -Atc 'SELECT id FROM recovery')" = 7
psql -h /work/socket -U fixture -d fixture -v ON_ERROR_STOP=1 <<'SQL'
CREATE TABLE child_probe (id integer);
COPY child_probe FROM PROGRAM '/tests/probe denied && printf "1\n"';
\! /tests/probe denied && touch /work/psql-child-passed
SQL
test -f /work/psql-child-passed
test "$(psql -h /work/socket -U fixture -d fixture -Atc 'SELECT id FROM child_probe')" = 1
# PostgreSQL14's UDP statistics collector fails closed to track_counts=off.
test "$(psql -h /work/socket -U fixture -d fixture -Atc 'SHOW track_counts')" = off
printf '%s\n' 'Filtered PostgreSQL restore and SQL subprocess probes passed'
