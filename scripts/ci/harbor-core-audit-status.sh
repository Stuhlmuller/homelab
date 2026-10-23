#!/usr/bin/env bash
set -euo pipefail
test "$#" -eq 1
diagnostic="$(cat -- "$1" 2>/dev/null || true)"
case "$diagnostic" in
  launcher|image-inspect|image-export|scanner-build|scanner-run|report-validation|\
  validation:identity-source|validation:identity-image-id|validation:identity-archive|\
  validation:identity-archive-structure|validation:identity-archive-config-hash|\
  validation:identity-archive-inspect-id|validation:identity-report-config|\
  validation:identity-platform|validation:identity-distro|\
  validation:scanner|validation:database|validation:freshness|\
  validation:filtering|validation:schema|validation:remediation|validation:clearance)
    ;;
  *) diagnostic=unknown ;;
esac
printf '::error::Runtime audit failed (%s); private output withheld.\n' "$diagnostic"
