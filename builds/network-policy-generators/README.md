# Generated policy source corrections

`source.json` pins the upstream source and SHA-256 of each local patch. Run
`python3 builds/network-policy-generators/verify-source.py` to clone the tagged
sources, verify their exact commits and licenses, apply both patches, and run
the targeted Go tests. For offline verification, pass `--cordium-repo` and
`--octelium-repo` paths to existing clones at the pinned tags. The verifier
clones those repositories before applying patches, so local edits cannot
silently become the tested source.

The Cordium patch removes the public IPv4/IPv6 all-port egress from generated
`cordium/ws-main`; internal TCP 8080 and DNS rules remain. The Octelium patch
removes the equivalent egress from generated `octelium/svc-upstream` and requires
a digest-pinned homelab Harbor Genesis image for `octops init` and `upgrade`.
This intentionally denies service-upstream egress until a reviewed per-service
allow rule and actual traffic qualification exist. Additive Kubernetes policies
cannot subtract either upstream-generated all-port rule.

These patches are source candidates only. Before using them, build and review
the Cordium Genesis, Octelium Genesis, and octops artifacts from these pinned
sources; publish and pin exact Harbor digests through a protected workflow;
wire the repository's current `scripts/octelium-cluster-bootstrap.sh` wrapper
to pass the reviewed Genesis digest to the patched octops binary; render the
real generated policies and refresh the expected-spec fixtures; then prove
required destinations and private-range denial through actual traffic on an
isolated canary. The current wrapper cannot pass `--genesis-image`, and these
patches have not produced or deployed any image. Keep enforcement disabled
until the other T018/T027 gates and live capacity admit it. Retain the upstream
`LICENSE` files in each source and any distributed artifacts. Cordium Genesis
uses Apache-2.0; Octelium Genesis is AGPL-3.0; octops is Apache-2.0.
