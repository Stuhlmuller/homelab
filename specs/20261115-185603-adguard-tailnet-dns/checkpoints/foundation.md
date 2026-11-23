# Foundation source increment — T004–T007

Canonical branch feat/adguard-tailnet-dns, base48e8b9e4627f4a37f30d00f2d28b96d64133996e.
Publication remains active under T003/run43777917412; this increment is unmerged
source and has not created a live credential/Application or changed DNS.

T004: added generated /homelab/adguard/admin-password (32 ASCII characters,
no special characters, explicit exact ESO reader access). Existing encrypted
state/SSM module owns generation. Existing module tests now cover its length,
character classes, no prefix, SecureString type and exact reader names. Rendered
authoritative SSM inputs agree; full reader inventory120 names/5 policy chunks,
with no wildcard and unchanged external-secrets reader identity. No values read
or printed. ESO credential/config rendering remains T011, not claimed complete.

T005: added shared stack/terragrunt.stack registration for automation in
homelab-workloads, main source clusters/homelab/apps/adguard, and exactly
external-secrets/tailscale/traefik/tailnet-dns/platform-storage dependencies.
Generated and inspected Application; existing project and store already permit
automation. No AppProject, namespace or ClusterSecretStore changes.

T006–007: offline fixture first demonstrated22 failing assertions without the
AdGuard preflight. Extended the existing targeted apply path: correct namespace
and project, healthy exact upstreams, ESO CRDs/store and namespace scope, NFS
existence, then checked SSM plan/apply and app registration. Existing current-main
guards and unrelated-target exclusion retained. Existing-only fixture now
includes AdGuard in its absent-app exclusion, preventing accidental registration.

Validation: full terragrunt-apply-test.py34 tests passed after correcting the
existing-only fixture expectations; all3 SSM module tests passed; shellcheck -x,
affected Terragrunt HCL formatting, module formatting, generated manifest/input
assertions and git diff --check passed. Initial shellcheck invocation omitted -x
and reported SC1091; corrected invocation follows the existing sourced helper.
One parallel Nix-shell startup hit the environment wrapper's tmpbin/git symlink
race before stack generation; sequential retry succeeded. Generated units,
provider locks and caches remain ignored. No full static rerun for incomplete
app source; full integration validation remains T030.

Pending: no AdGuard runtime manifests yet (T008+), no consuming PR, no live
SSM/app apply, no DNS changes. Docs and source checks must be completed
in the app PR before merge. Next distinct turn: scoped speckit-converge for this
foundation increment, then direct-filtering story implementation T008–015.
Continue monitoring existing publisher via session80837/log image-publisher-watch.log;
never mark T003 complete until the authenticated complete-pull run succeeds.
