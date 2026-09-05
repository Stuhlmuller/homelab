# NOFX catalog reconciliation

NOFX's repository Service disables anonymous access and attaches
`homelab-human-web-access`. The native Octelium catalog is a separate declared
apply boundary from Kubernetes Argo CD. Merging the manifest alone does not
reconcile that native Service.

`scripts/octelium-nofx-reconcile.py` is the fixed operator path for this change.
It reads only NOFX by default, using an existing operator Octelium session.
The Nix shell supplies the pinned Cloudflare client. Install Octelium CLI 0.35.0
from the fixed release archives with committed SHA-256 checksums:

```sh
bash scripts/install-octeliumctl.sh "$HOME/.local/bin"
```

Keep that directory on your normal PATH. Reconciliation rejects a missing client,
a different release, or a different source commit before opening the transport.

```sh
nix develop --command python3 scripts/octelium-nofx-reconcile.py
```

The command starts a temporary unprivileged TCP carrier and a loopback CONNECT
proxy restricted to the canonical API hostname. Only its child native-client
processes receive that dynamically allocated proxy address. Inner TLS remains
verified; it changes no hosts file, DNS settings, or saved client config.
Temporary files and both listeners are removed afterward. Use `--homedir`
only to select a different existing private operator login directory.

## Apply and verify

After this path is reviewed and merged, check out the exact reviewed main
commit, pass the repository validation gate, and execute:

```sh
nix develop --command python3 scripts/octelium-nofx-reconcile.py \
  --execute --expected-sha FULL_REVIEWED_MAIN_SHA
```

The command requires local HEAD and remote main to equal that commit and
rejects changes to its tracked code or catalog. It selects only Service `nofx`
from the committed catalog and explicitly names `nofx.default` during apply.
It cannot apply Users, Policies, credentials, or another Service. It applies
through the native catalog API twice, requires the second run to report no
changes, and verifies anonymous access is disabled and the human policy is
attached. Private native output is withheld on failures.

Then verify unauthenticated NOFX requests are rejected or redirected to login,
authorized human access works, and the console records the access decision and
resource change. A successful controller rollout or CLI exit alone is not this
acceptance test. Local regression tests cover the fixed resource scope,
read-only default, commit mismatch, reported apply errors, convergence, and
post-apply anonymous-access verification.

## Rollback

Keep anonymous access disabled. Repair the declared human policy or upstream
routing through a reviewed catalog change and rerun the same path. This helper
refuses an anonymous catalog contract. Retiring the helper does not modify the
live Service; do not use broad catalog pruning or ad hoc policy edits.
