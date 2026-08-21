#!/bin/sh
set -eu

valid_config() {
  candidate="$1"

  [ -s "$candidate" ] &&
    grep -q '<Config>' "$candidate" &&
    [ "$(grep -c '</Config>' "$candidate" || true)" -eq 1 ] &&
    [ "$(grep -c '<ApiKey>[^<][^<]*</ApiKey>' "$candidate" || true)" -eq 1 ]
}

generate_api_key() {
  LC_ALL=C tr -dc 'A-Za-z0-9' </dev/urandom | head -c 32
}

legacy_has_migration_content() {
  legacy_dir="$1"

  find "$legacy_dir" -mindepth 1 \
    ! -path "$legacy_dir/local-backups" \
    ! -path "$legacy_dir/local-backups/*" \
    ! -name 'lost+found' \
    \( -type f -o -type l \) \
    -print -quit 2>/dev/null | grep -q .
}

select_recovery_source() {
  legacy_dir="$1"
  recovered="$2"
  selected_source=""

  if valid_config "$legacy_dir/config.xml"; then
    cp "$legacy_dir/config.xml" "$recovered"
    selected_source="$legacy_dir/config.xml"
    return
  fi

  selected_source="$(
    find "$legacy_dir/Backups" -maxdepth 3 -type f \
      -name 'sonarr_backup_*.zip' -exec ls -1t {} + 2>/dev/null |
      while IFS= read -r archive; do
        if unzip -p "$archive" config.xml >"$recovered" 2>/dev/null &&
          valid_config "$recovered"; then
          printf '%s\n' "$archive"
          break
        fi
      done
  )"
  [ -z "$selected_source" ] || return 0

  selected_source="$(
    find "$legacy_dir" -maxdepth 1 -type f \
      -name 'config.xml.auth-recovery.*' 2>/dev/null | sort -r |
      while IFS= read -r candidate; do
        if valid_config "$candidate"; then
          cp "$candidate" "$recovered"
          printf '%s\n' "$candidate"
          break
        fi
      done
  )"
  [ -z "$selected_source" ] || return 0

  if ! legacy_has_migration_content "$legacy_dir"; then
    api_key="$(generate_api_key)"
    printf '<Config>\n  <ApiKey>%s</ApiKey>\n</Config>\n' "$api_key" >"$recovered"
    selected_source="fresh local bootstrap"
    return 0
  fi

  rm -f "$recovered"
  echo "No Sonarr config with a closing Config tag and API key was recoverable" >&2
  return 1
}

migrate_config() {
  config_dir="$1"
  legacy_dir="$2"
  marker="$config_dir/.nfs-migration-complete"
  recovered="$config_dir/.nfs-recovered-config.partial"

  mkdir -p "$config_dir"
  if [ -e "$marker" ]; then
    echo "Sonarr config migration already completed"
    return
  fi

  rm -f "$recovered"
  select_recovery_source "$legacy_dir" "$recovered" || return 1

  find "$config_dir" -mindepth 1 -maxdepth 1 \
    ! -name '.nfs-recovered-config.partial' -exec rm -rf -- {} +
  find "$legacy_dir" -mindepth 1 -maxdepth 1 \
    ! -name local-backups \
    -exec cp -R {} "$config_dir"/ \;

  if ! valid_config "$config_dir/config.xml"; then
    if [ -e "$config_dir/config.xml" ]; then
      timestamp="$(date -u +%Y%m%dT%H%M%SZ)"
      mv "$config_dir/config.xml" \
        "$config_dir/config.xml.nfs-corrupt-${timestamp}"
    fi
  fi

  cp "$recovered" "$config_dir/config.xml"
  rm -f "$recovered"
  chmod 0600 "$config_dir/config.xml"
  sync

  touch "$marker"
  sync

  echo "Recovered Sonarr config from $selected_source"
}

self_test() {
  test_root="$(mktemp -d)"
  trap 'rm -rf "$test_root"' 0 1 2 15
  sync() { :; }

  mkdir -p \
    "$test_root/config" \
    "$test_root/fixture" \
    "$test_root/newest-fixture" \
    "$test_root/legacy/Backups/manual archives" \
    "$test_root/legacy/Backups/scheduled" \
    "$test_root/legacy/local-backups" \
    "$test_root/legacy/MediaCover"
  : >"$test_root/legacy/config.xml"
  printf 'old backup archive\n' >"$test_root/legacy/local-backups/sonarr-config.tar.gz"
  printf 'recoverable\n' >"$test_root/legacy/MediaCover/poster.jpg"
  printf '<Config>\n  <ApiKey>fixture</ApiKey>\n</Config>\n' \
    >"$test_root/fixture/config.xml"
  (
    cd "$test_root/fixture"
    zip -q \
      "$test_root/legacy/Backups/scheduled/sonarr_backup_v9_2099.01.01.zip" \
      config.xml
  )
  printf '<Config>\n  <ApiKey>fixture-newest</ApiKey>\n</Config>\n' \
    >"$test_root/newest-fixture/config.xml"
  (
    cd "$test_root/newest-fixture"
    zip -q \
      "$test_root/legacy/Backups/manual archives/sonarr_backup_v1_2000.01.01.zip" \
      config.xml
  )
  touch -t 209901010000 \
    "$test_root/legacy/Backups/scheduled/sonarr_backup_v9_2099.01.01.zip"
  touch -t 209902010000 \
    "$test_root/legacy/Backups/manual archives/sonarr_backup_v1_2000.01.01.zip"

  migrate_config "$test_root/config" "$test_root/legacy"
  valid_config "$test_root/config/config.xml"
  grep -q '<ApiKey>fixture-newest</ApiKey>' "$test_root/config/config.xml"
  test -f "$test_root/config/MediaCover/poster.jpg"
  test ! -e "$test_root/config/local-backups"
  find "$test_root/config" -maxdepth 1 -type f \
    -name 'config.xml.nfs-corrupt-*' -size 0 | grep -q .

  before="$(cksum "$test_root/config/config.xml")"
  migrate_config "$test_root/config" "$test_root/legacy"
  test "$before" = "$(cksum "$test_root/config/config.xml")"

  rm -rf "$test_root/config" "$test_root/legacy"
  mkdir -p "$test_root/config" "$test_root/legacy/local-backups"
  migrate_config "$test_root/config" "$test_root/legacy"
  valid_config "$test_root/config/config.xml"
  test ! -e "$test_root/config/local-backups"

  rm -rf "$test_root"
  trap - 0 1 2 15
  echo "Sonarr config migration self-test passed"
}

if [ "${1:-}" = "--self-test" ]; then
  self_test
  exit
fi

migrate_config /config /legacy-config
