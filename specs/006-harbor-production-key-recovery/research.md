# Research: Pinned signing semantics

No unresolved implementation unknowns remain for this local proposal. Actual
live execution/receipt recovery evidence is explicitly deferred.

- Installed CLI1.92.3 reports commit9a08e8f1c2021d5c85895e660cf01d8bb1bc9df0.
  Its official source was fetched/read through GitHub contents API:
  [installed CLI implementation](https://github.com/tailscale/tailscale/blob/9a08e8f1c2021d5c85895e660cf01d8bb1bc9df0/cmd/tailscale/cli/network-lock.go)
- Also checked pinned workflow version1.102.3:
  [workflow CLI implementation](https://github.com/tailscale/tailscale/blob/v1.102.3/cmd/tailscale/cli/tailnet-lock.go)
- Decision: use the installed pinned CLI with lock sign file:/dev/stdin.
  Source reads the argument file, generates a distinct pre-auth signing key,
  wraps the authkey, adds its public authority, then prints the wrapped key.
  Therefore nonzero exit/lost stdout cannot establish no remote mutation.
- Decision: durable intent before invocation and direct0600 stdout capture;
  recover-only after uncertainty. Complete output can reconcile trust/cache;
  lost/partial output stops. Do not repeat sign based on absence in one netmap.
- Trust metadata binds purpose,authkey_stableid,wrapper_stableid and creation
  interval. Preserve previous authority keys,metadata and vote weights;accept exactly one
  addition with the pinned operation's Votes=1.
- Public NL key JSON and CLI prefixes are equivalent per pinned types/key/nl.go;
  use the already approved production helper's canonicalization.
- Rejected: full three-identity publisher,automatic receipt deletion/re-signing,
  raw keys in arguments/output,new provider keys and automatic authority removal.
- Per-run direct node signing avoids a pre-auth delegation but needs a different
  reviewed workflow/request path. None is introduced here. New persistent
  delegation remains a distinct approval decision with cluster-admin exposure.
