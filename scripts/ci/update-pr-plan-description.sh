#!/usr/bin/env bash
set -euo pipefail

: "${PR_NUMBER:?PR_NUMBER is required}"
: "${TERRAGRUNT_PLAN_MARKDOWN:?TERRAGRUNT_PLAN_MARKDOWN is required}"

if [[ -z "${GH_TOKEN:-}${GITHUB_TOKEN:-}" ]]; then
  echo "GH_TOKEN or GITHUB_TOKEN is required so gh can update the pull request description." >&2
  exit 1
fi

if [[ ! -s "$TERRAGRUNT_PLAN_MARKDOWN" ]]; then
  echo "No Terragrunt plan markdown was generated at ${TERRAGRUNT_PLAN_MARKDOWN}." >&2
  exit 1
fi

start_marker="<!-- terragrunt-plan:start -->"
end_marker="<!-- terragrunt-plan:end -->"
max_body_bytes="${TERRAGRUNT_PR_BODY_MAX_BYTES:-64000}"
max_plan_bytes="${TERRAGRUNT_PLAN_MARKDOWN_MAX_BYTES:-56000}"

tmp_dir="$(mktemp -d)"
trap 'rm -rf "$tmp_dir"' EXIT

current_body="$tmp_dir/current.md"
plan_body="$tmp_dir/plan.md"
section="$tmp_dir/section.md"
updated_body="$tmp_dir/updated.md"

gh pr view "$PR_NUMBER" --json body --jq '.body // ""' >"$current_body"

if (($(wc -c <"$TERRAGRUNT_PLAN_MARKDOWN") > max_plan_bytes)); then
  {
    head -c "$max_plan_bytes" "$TERRAGRUNT_PLAN_MARKDOWN"
    printf '\n\n> Plan output was truncated to keep the pull request description within GitHub limits. Re-run `nix develop --command bash scripts/ci/terragrunt-plan.sh` locally for the full saved plan output.\n'
  } >"$plan_body"
else
  cp "$TERRAGRUNT_PLAN_MARKDOWN" "$plan_body"
fi

{
  printf '%s\n' "$start_marker"
  cat "$plan_body"
  printf '\n%s\n' "$end_marker"
} >"$section"

awk -v start="$start_marker" -v end="$end_marker" -v section_file="$section" '
  BEGIN {
    in_section = 0
    inserted = 0
  }
  $0 == start {
    while ((getline line < section_file) > 0) {
      print line
    }
    close(section_file)
    in_section = 1
    inserted = 1
    next
  }
  $0 == end {
    in_section = 0
    next
  }
  !in_section {
    print
  }
  END {
    if (!inserted) {
      print ""
      while ((getline line < section_file) > 0) {
        print line
      }
      close(section_file)
    }
  }
' "$current_body" >"$updated_body"

if (($(wc -c <"$updated_body") > max_body_bytes)); then
  echo "Updated pull request description is larger than ${max_body_bytes} bytes after truncation." >&2
  exit 1
fi

if cmp -s "$current_body" "$updated_body"; then
  echo "Pull request description already contains the current Terragrunt plan output."
  exit 0
fi

gh pr edit "$PR_NUMBER" --body-file "$updated_body"
