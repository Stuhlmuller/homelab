#!/bin/sh
# Run only as a Recreate deployment init container, before ClickHouse starts.
# Match the pinned server's native permanent-detach markers; never move data.
set -eu
umask 077

data=/var/lib/clickhouse
database="$data/metadata/system.sql"
alias_path="$data/metadata/system"
fail() { printf '%s\n' "$1" >&2; exit 1; }

if [ ! -e "$database" ]; then
    [ ! -L "$database" ] && [ ! -e "$alias_path" ] && [ ! -L "$alias_path" ] ||
        fail 'System database metadata is incomplete; refusing quarantine.'
    exit 0
fi
[ -f "$database" ] && [ ! -L "$database" ] || fail 'Unexpected system database metadata type.'
uuid=$(sed -nE "s/^ATTACH DATABASE .* UUID '([0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12})'.*$/\1/p" "$database")
if [ "${#uuid}" -ne 36 ] || ! grep -Eq '^ENGINE = Atomic[[:space:]]*$' "$database"; then
    fail 'Expected pinned ClickHouse Atomic system database metadata.'
fi
directory="$data/store/$(printf '%.3s' "$uuid")/$uuid"
[ -d "$directory" ] && [ "$(readlink -f "$alias_path")" = "$directory" ] ||
    fail 'System database alias does not match its authoritative metadata directory.'

tables='error_log histogram_metric_log opentelemetry_span_log part_log query_log text_log'
# Validate all inputs before creating any marker. Existing native flags are no-ops.
for table in $tables; do
    metadata="$directory/$table.sql"
    marker="$metadata.detached"
    [ ! -L "$metadata" ] && [ ! -L "$marker" ] || fail "Unexpected symlink for system.$table."
    if [ -e "$metadata" ]; then
        [ -f "$metadata" ] && [ -s "$metadata" ] || fail "Invalid metadata for system.$table."
    else
        [ ! -e "$marker" ] || fail "Detached marker without metadata for system.$table."
    fi
    if [ -e "$marker" ]; then
        [ -f "$marker" ] && [ ! -s "$marker" ] || fail "Invalid detach marker for system.$table."
    fi
done

for table in $tables; do
    metadata="$directory/$table.sql"
    marker="$metadata.detached"
    if [ -f "$metadata" ] && [ ! -e "$marker" ]; then
        (set -C; : > "$marker")
        printf 'Permanently quarantined system.%s before metadata loading.\n' "$table"
    fi
done
