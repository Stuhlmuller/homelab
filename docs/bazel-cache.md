# Homelab Bazel remote cache

Run the offline checks from the root of the Git checkout.

```sh
nix run .#bazel-offline
```

The pinned Bazel command runs the offline fixture suite, manifest policy,
OpenWiki setup, and XERJ autoindex as four test targets. A single target can
be selected with `--target`. Each action includes the exact corresponding
Nix derivation and signature policy in its inputs. On a Bazel miss, Nix
can substitute a signed output or run the original check in the Nix sandbox.

To share your results with CI, use an x86-64 Linux Nix environment and an AWS
session allowed to decrypt `/homelab/octelium/bazel-cache-writer-password`.

```sh
nix develop --command nix run .#bazel-offline -- --publish
```

Publication verifies that an independent read-only Bazel run hits the cache.
The credential helper sends the password only to
`https://bazel-cache.stinkyboi.com`. PR and main CI use anonymous read-only
access. The HTTP server requires authentication for writes. The offline suites
have no deployment credentials. Keep private or untracked inputs out of
published test runs. Successful test actions retain only Bazel's test results
and logs from the wrapper.

The tracked source tree and Nix platform participate in the Nix derivation.
An unchanged tree can reuse a result across machines. A changed PR merge tree
or a different platform can miss. The offline and manifest checks still read
the full tracked tree, so changes to unrelated tracked files can invalidate
those results. Live plans and network checks continue to run separately.

## Deployment and verification

1. Publish the pinned image with the protected **Mirror Kubernetes Images To
   Harbor** workflow, using `image_scope=bazel-cache` and current main.
2. After the workload merges, run the protected **Terragrunt Apply** workflow
   for `argocd_app=octelium-public` and exact current main. It declares the
   writer credential and reconciles the existing Application.
3. Use **Mastodon Public DNS** with `site=bazel-cache` and exact current main
   after the Application is Synced and Healthy. It publishes the fixed
   Cloudflare Tunnel hostname.
4. Confirm a public GET on a missing CAS object returns 404 and an anonymous
   PUT to a valid digest path returns 401. An authorized publisher can then
   run a test and an independent cache reader can run the same target from
   the same tree. A remote cache hit in the second Bazel invocation confirms
   reuse. Check the Terragrunt static job or the main repository job for
   subsequent CI hits.

The workload only accepts traffic from the Cloudflare Tunnel pods. The tunnel
publishes the Bazel `/ac/<digest>` and `/cas/<digest>` paths. Cache entries
are evicted when the 2 GiB cache fills and can disappear on Pod replacement.
They can be recreated by a later trusted test run.

To revoke a writer, rotate the generated credential through the protected
SSM apply, trigger External Secrets refresh with the declared annotation,
and roll out the cache Pod. If cached results may have been compromised, also
replace the Pod so it starts with an empty cache. To roll back CI, restore
the workflows' Nix check command. After removing the Cloudflare route,
requests to the hostname stop reaching the cache.
