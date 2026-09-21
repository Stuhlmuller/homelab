# NOFX catalog reconciliation

NOFX's repository Service disables anonymous access and attaches
`homelab-human-web-access`. The native Octelium catalog is a separate declared
apply boundary from Kubernetes Argo CD. Merging the manifest alone does not
reconcile that native Service.

`scripts/octelium-nofx-reconcile.py` is the fixed operator path for this change.
It reads only NOFX by default, using an existing operator Octelium session.
The Nix shell supplies the pinned Cloudflare client. Install Octelium CLI 0.35.0
from the fixed release archives with committed SHA-256 checksums. The installer
uses `sha256sum` when available (including the Linux Nix shell), with `shasum`
as the Darwin fallback; checksum failure prevents installation.

```sh
bash scripts/install-octeliumctl.sh "$HOME/.local/bin"
```

Keep that directory on your normal PATH. Reconciliation rejects a missing client,
a different release, or a different source commit before opening the transport.

```sh
nix develop --command python3 -I scripts/octelium-nofx-reconcile.py
```

Run previews from an already trusted checkout and shell. Isolated Python does
not sandbox Nix evaluation; use the pre-Nix caller gate below for execution.

Use `python3 -I` for both preview and execution. The entrypoint refuses ordinary
Python invocation before importing other modules. Isolated mode excludes the
script directory, current directory, user packages, and `PYTHONPATH` from
module lookup, so an untracked `scripts/json.py` cannot execute before the
clean-checkout guard. The guard still rejects untracked files during execution.

The command starts a temporary unprivileged TCP carrier and a loopback CONNECT
proxy restricted to the canonical API hostname. Only its child native-client
processes receive that dynamically allocated proxy address. Inner TLS remains
verified; it changes no hosts file, DNS settings, or saved client config.
Temporary files and both listeners are removed afterward. Use `--homedir`
only to select a different existing private operator login directory.
The helper rejects inherited `OCTELIUM_INSECURE_TLS=true` or a nonempty
`OCTELIUM_AUTH_PROXY_SOCKET` before opening transport: the pinned native client
would otherwise bypass certificate verification or use its authentication
proxy socket instead of the reviewed TLS path.

## Read-only observation: 2026-09-12

The earlier 45-second native lookup timeout did not recur with the unmodified
helper. The pinned client completed an authenticated lookup through the
verified TLS carrier; bounded transport diagnostics confirmed the expected
API CONNECT requests. No transport or authentication changes were required.
The read-only result still reported `NOFX anonymous access: True`.

This confirms native catalog drift remains. Merging the manifest or applying
Kubernetes does not satisfy catalog acceptance: run the guarded reconciliation
below, then verify convergence, human authorization, and audit evidence.

## Apply and verify

After this path is reviewed and merged, check out the exact reviewed main
commit, pass the repository validation gate, and execute:

```sh
(
  set -euo pipefail
  reviewed_main_sha=FULL_REVIEWED_MAIN_SHA
  checkout_changes="$(git status --porcelain=v1 \
    --untracked-files=all --ignore-submodules=none)"
  checkout_head="$(git rev-parse --verify HEAD)"
  remote_head="$(git ls-remote \
    https://github.com/Stuhlmuller/homelab.git refs/heads/main | cut -f1)"
  test -z "$checkout_changes"
  test "$checkout_head" = "$reviewed_main_sha"
  test "$remote_head" = "$reviewed_main_sha"
  nix develop --command python3 -I scripts/octelium-nofx-reconcile.py \
    --execute --expected-sha "$reviewed_main_sha"
)
```

The caller checks the clean, exact local/remote commit before entering Nix,
so an unreviewed flake or shell hook cannot run ahead of that check. The Python
helper then repeats the commit and cleanliness checks before reading the
catalog or opening transport. Keep local scratch files outside the checkout.
This includes dependency changes in `flake.nix`/`flake.lock` and untracked
Python modules. It selects only Service `nofx`
from the committed catalog and explicitly names `nofx.default` during apply.
It cannot apply Users, Policies, credentials, or another Service. It applies
through the native catalog API twice, requires the second run to report no
changes, and verifies anonymous access is disabled and the human policy is
attached, with `config.http.header.authorizationMode: PASS` retained for NOFX's
session JWT. Missing or changed authorization passthrough fails verification.
An authenticated `NotFound` reports an absent Service during preview and
allows execution to recreate only `nofx.default` from its declaration.
Authentication, authorization, and transport errors fail before any apply;
a Service still absent after applying also fails. Private native output is
withheld on failures.

Then verify unauthenticated NOFX requests are rejected or redirected to login,
authorized human access works, and the console records the access decision and
resource change. A successful controller rollout or CLI exit alone is not this
acceptance test. Local regression tests cover the fixed resource scope,
read-only default, commit mismatch, dirty dependency files and untracked
modules, reported apply errors, convergence, and
post-apply anonymous-access verification.

## Rollback

Keep anonymous access disabled. Repair the declared human policy or upstream
routing through a reviewed catalog change and rerun the same path. This helper
refuses an anonymous catalog contract. Retiring the helper does not modify the
live Service; do not use broad catalog pruning or ad hoc policy edits.
