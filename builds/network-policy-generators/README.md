# Generated policy source corrections

`source.json` pins the upstream source and SHA-256 of each local patch. Run
`python3 builds/network-policy-generators/verify-source.py` to clone the tagged
sources, verify their exact commits and licenses, apply both patches, and run
the targeted Go tests. For offline verification, pass `--cordium-repo` and
`--octelium-repo` paths to existing clones at the pinned tags. The verifier
clones those repositories before applying patches, so local edits cannot
silently become the tested source.

`candidate-networkpolicies.json` records full policy specs rendered by the
unpatched and patched constructors at those exact revisions. Reproduce it with
`verify-source.py --check-render`; `--write-render` is for an intentional
reviewed fixture update. The check first matches the unpatched constructors to
the current source-reviewed fixtures, then requires the patched objects to
differ only by removal of each all-port IPv4/IPv6 egress rule. The protected
image build repeats this check before registry credentials. This file is a
candidate source render, not an installed policy fixture or canary receipt.

The Cordium patch removes the public IPv4/IPv6 all-port egress from generated
`cordium/ws-main`; internal TCP 8080 and DNS rules remain. The Octelium patch
removes the equivalent egress from generated `octelium/svc-upstream` and requires
a digest-pinned homelab Harbor Genesis image for `octops init` and `upgrade`.
This intentionally denies service-upstream egress until a reviewed per-service
allow rule and actual traffic qualification exist. Additive Kubernetes policies
cannot subtract either upstream-generated all-port rule.

The protected `policy-generator-images.yml` workflow checks the exact current
`main` commit, verifies the two pinned source revisions and patch hashes, runs
the targeted tests, and builds three Linux/amd64 images before receiving
registry credentials. `build.sh` sets upstream GitCommit, GitTag, image registry,
and image prefix in each
binary, overlays it on the exact pinned upstream runtime image, checks that
the upstream user, entrypoint, environment, commands, and runtime tools remain,
and keeps the relevant upstream license files in each image. The guarded
publisher pushes fixed Harbor names,
pulls each exact digest with authentication, signs them, verifies signatures,
and emits `cordium_genesis`, `octelium_genesis`, and `octops` digest references.
The publication receipts contain a `:homelab-<main SHA>` tag as well as the
digest; the future `octops --genesis-image` consumer must pass the tagless
`harbor.stinkyboi.com/homelab/homelab-octelium-genesis@sha256:<digest>` form.
The workflow has not been dispatched, and no image has been published by this
change. A failed protected publication retains only a one-day encrypted private
diagnostic; public logs carry a generic error.

The bootstrap wrapper reads `octelium.publishedGenesisImage` from
`source.json`. It is `null` until a protected publication has produced an
authenticated digest. Once a reviewed digest is committed, the wrapper accepts
only the fixed tagless Harbor Genesis reference, checks that both installed
`octops` commands support `--genesis-image`, and passes the digest to init or
upgrade before any live writes. While the pin is absent, it checks for the
network-policy enforcer before prerequisite waits and again when octops runs;
either check fails closed if the DaemonSet is installed or unreadable. The
wrapper does not yet install the patched octops binary. Its `--help` check
proves flag support, not binary provenance. Before using these artifacts, pin
both successful Harbor digests and provide a reviewed installation path that
verifies the patched octops binary came from its authenticated, signed image
digest. Compare the published generator's installed policies to these candidate
renders and refresh installed expected-spec fixtures only after review. Prove
required destinations and private-range denial through actual traffic on an
isolated canary. These patches have not
deployed any image. Keep enforcement disabled until the other T018/T027 gates
and live capacity admit it. Retain the upstream `LICENSE` files in each source
and any distributed artifacts. Cordium Genesis
uses Apache-2.0; Octelium Genesis is AGPL-3.0; octops is Apache-2.0.
