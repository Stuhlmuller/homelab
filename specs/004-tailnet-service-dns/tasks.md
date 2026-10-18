# Tasks: Private Tailnet Service DNS

**Input**: [spec.md](spec.md), [plan.md](plan.md), [research.md](research.md), [data-model.md](data-model.md), [contracts](contracts/), and [quickstart.md](quickstart.md)

**Scope boundary**: Implement and deploy the resolver, verify its assigned tailnet IPv4 and direct DNS path, then pause for the owner to add that IP as the restricted `stinkyboi.com` nameserver. Implement the guarded public-retirement path now; do not execute it before the owner handoff and later cutover acceptance.

## Phase 1: Setup — publish the pinned DNS image

**Purpose**: The consuming Argo Application must not reach `main` until the exact Codeberg image is present and pullable in Harbor. The unrelated full-catalog LiteLLM failure is not a reason to bypass publication.

- [X] T001 Add `codeberg.org/k8s-gateway/k8s_gateway:1.9.0@sha256:0b556f261d46873d7d2e86e5d345bb99db30de6b3869b83e32d273a466e980e4` to `scripts/config/harbor-images.json` and create the one-entry `scripts/config/harbor-dns-images.json` scope.
- [X] T002 [P] Add the Codeberg registry to the strict Talos mirror declaration in `.talos/patches/harbor-mirrors.yaml` and its upstream recovery declaration in `.talos/patches/harbor-mirrors-rollback.yaml`; do not apply a Talos change merely to pull the direct Harbor image.
- [X] T003 Extend `scripts/ci/harbor-publish.sh` with the exact `mirror-dns` mode, Codeberg source allowlist, and one-entry catalog subset guard; accept no caller-supplied image or destination.
- [X] T004 Extend `.github/workflows/harbor-mirror.yml` with fixed `dns` dispatch, update its matching OPA rule in `policy/workflows.rego` and tests in `policy/workflows_test.rego`, then refresh the publisher hash in those files and the workflow hash in `scripts/ci/offline-static-checks.sh`.
- [X] T005 Add positive and negative tests for the DNS scope, Codeberg allowlist, subset guard, publication status pin, and Talos catalog coverage in `scripts/ci/harbor-publish-test.py`, `scripts/ci/harbor-images-check.py`, and `scripts/ci/talos-harbor-mirrors-test.py`.
- [X] T006 Run the focused publisher, mirror-coverage, policy, and repository validation gates against `scripts/ci/harbor-publish-test.py`, `scripts/ci/harbor-images-check.py`, `policy/workflows_test.rego`, and `scripts/ci/offline-static-checks.sh`; merge a publisher-only reviewed PR containing T001–T005 before the DNS Application PR.
- [X] T007 Dispatch `.github/workflows/harbor-mirror.yml` on the exact merged `main` SHA with `image_scope=dns`; require its successful copy and complete authenticated Harbor pull receipt for the pinned image before T014–T018 can merge.

---

## Phase 2: Foundational — reviewed name and trust boundaries

**Purpose**: Declare the only allowed publication source, tailnet access, and signing contract shared by the user stories.

- [X] T008 [P] Admit the exact k8s_gateway OCI chart source and `tailnet-dns` destination namespace in `clusters/homelab/argocd/self-management/appproject.yaml`.
- [X] T009 [P] Verify `scripts/config/tailscale-policy.json` already gives the Kubernetes operator ownership of `tag:homelab-ingress` and ordinary members a wildcard grant covering UDP/TCP 53; preserve the policy and Tailnet Lock configuration.
- [X] T010 Extend `scripts/ci/tailscale-access-check-test.py` to prove the existing ingress-tag ownership/member grant and that restricted CI tags receive no new DNS grant.
- [X] T011 [P] Add the private-DNS approval label and `coredns.io/hostname` annotation with exactly the 27 migration names to `service.private` in `clusters/homelab/apps/traefik/values.yaml`; leave Traefik HTTPS routes, Fleet denial, Harbor registry listener, and Funnel routes unchanged.
- [X] T012 [P] Extend the fixed proxy identity list and namespace-aware inspection in `scripts/tailscale-ingress-sign.py` for only `tailnet-dns/tailnet-dns` named `homelab-dns` with the existing `tag:homelab-ingress`.
- [X] T013 Extend `scripts/ci/tailscale-ingress-sign-test.py` with valid signed DNS peer, unsigned DNS peer, wrong tag/namespace/IP, and changed-identity rejection cases for `scripts/tailscale-ingress-sign.py`.

**Checkpoint**: Only one reviewed Traefik Service can publish the migration names, and the DNS proxy has an explicit tailnet trust path.

---

## Phase 3: User Story 1 — reach private apps by existing names (Priority: P1) 🎯 MVP

**Goal**: A separately hosted resolver answers the 27 approved names with the current private Traefik IPv4, preserves unrelated public names and apex non-address records, and accepts UDP/TCP 53 over Tailscale.

**Independent test**: Render the chart and namespace overlay; after GitOps rollout, query the assigned DNS tailnet IP from an ordinary tailnet client over UDP and TCP for every approved
exact name and a concrete Cordium child. Compare A answers with live `traefik-private` Service status; check approved AAAA NODATA, apex MX/TXT, unrelated public A, and representative HTTPS
routes. Normal OS lookup acceptance waits for the owner's nameserver setting.

- [X] T014 [P] [US1] Create the `tailnet-dns` namespace and supporting Kustomize source in `clusters/homelab/platform/tailnet-dns/namespace.yaml` and `clusters/homelab/platform/tailnet-dns/kustomization.yaml`.
- [X] T015 [US1] Set the pinned `4.0.0` chart's CoreDNS A/AAAA `view`, Service-only k8s_gateway watch, private label selector, LoadBalancer-status IPv4 preference, 30-second TTL/cache, public fallthrough/other-type forwarding, two stateless replicas, restrictive Pod settings, direct Harbor image digest, and Tailscale UDP/TCP 53 Service in `clusters/homelab/platform/tailnet-dns/values.yaml`.
- [X] T016 [P] [US1] Register a `main`-tracking multi-source Argo Application with Tailscale and Traefik dependencies in `IaC/stacks/tailnet-dns/stack.hcl` and `IaC/terragrunt.stack.hcl`.
- [X] T017 [US1] Add the exact new OCI chart source/version to `scripts/config/harbor-image-charts.json`, using the rendered chart and its observed OCI digest as the review evidence.
- [X] T018 [US1] Add a focused render/contract check in `scripts/ci/tailnet-dns-test.py` for the selected Service source, the initial 27-name migration fixture, one-label Cordium wildcard,
  TCP/UDP 53, existing `tag:homelab-ingress`, Service-only RBAC, IPv4-only target, public query-type forwarding, pinned Harbor image, and no CoreDNS cluster-service replacement. Do not make
  exact 27-name equality a permanent merge gate.
- [X] T019 [P] [US1] Add a read-only direct resolver health command in `scripts/tailnet-dns-check.py` that compares the observed resolver Service/online signed peer IP with the supplied
  server, queries the currently approved Service-annotation names over UDP/TCP, checks apex MX/TXT and unrelated public names, and fails if answers are public fallthrough or differ from the
  live Traefik Service IPv4. An explicit `--initial-handoff` mode also requires exact 27-name equality.
- [X] T020 [US1] Cover successful direct answers, mismatched peer/Service IP, public-address leakage, missing wildcard answer, UDP/TCP failure, preserved public records, and a later approved add/remove in `scripts/ci/tailnet-dns-check-test.py`.

**Checkpoint**: The resolver can be rendered and directly verified without changing the tailnet DNS setting or public records.

---

## Phase 4: User Story 2 — register only approved names automatically (Priority: P2)

**Goal**: Reviewed route-plus-Service-annotation changes update k8s_gateway answers through its Service watch; no second per-name DNS record writer is introduced.

**Independent test**: Fixture changes that add, change, and remove a route/annotation pair pass only when both declarations agree. Unapproved Service, discovery-only Ingress, public-only route, duplicate, retired, and out-of-zone names fail. The rendered resolver watches only the selected Service; observe convergence on the first later reviewed live name change.

- [X] T021 [US2] Implement route/annotation parity in `scripts/ci/tailnet-dns-test.py`, including fixture mutations for approved add/change/remove, mismatch, duplicate, retired, public-only,
  Compass-only, and second selected Service. An explicit `--initial-migration` mode also checks exact 27-name equality for the first rollout; the default check must accept later reviewed
  name changes without editing the migration JSON.
- [X] T022 [US2] Wire the continuing route/annotation parity and rendered resolver checks into `scripts/ci/static-checks.sh`, and the offline declaration and handoff-check tests into `scripts/ci/offline-checks.sh`; keep the initial-migration assertion outside these permanent gates.

**Checkpoint**: A paired GitOps exposure change is the continuing approval action; DNS answer synchronization is controller-managed.

---

## Phase 5: User Story 3 — prepare safe public retirement (Priority: P3)

**Goal**: Implement a guarded, idempotent deletion path for the 27 public A/AAAA/CNAME names, with no way for the old publication mode to recreate them. Do not execute deletion in this run.

**Independent test**: Mock Cloudflare API records and cutover evidence. Before owner handoff or with missing live baseline/TTL/off-tailnet acceptance, execution fails before writes. A valid preview lists only exact approved record IDs; execution deletes/readbacks only those records, preserving unrelated names and non-address types, and a retry resumes partial deletion safely.

- [X] T023 [US3] Add an exact-main, fixed-27 retirement preflight and validated private evidence input to `scripts/tailscale-private-dns-check.py`; require owner DNS confirmation, normal-client/HTTPS/critical-path acceptance, live baseline and maximum prior TTL, and apex/Cordium off-tailnet impact decision before any write.
- [X] T024 [US3] Replace the old active-name A/AAAA publication mode with a guarded, idempotent `--retire-private` dry-run/execute path in `scripts/tailscale-private-dns.sh`; target only the 27 inventory names' A/AAAA/CNAME records, read back deletions, and preserve retired exclusions, unrelated names, and MX/TXT/CAA/NS/SOA.
- [X] T025 [US3] Add mocked precondition, exact-record, wildcard, partial-retry, unrelated-record, and no-republication cases in `scripts/ci/tailscale-private-dns-test.py` for `scripts/tailscale-private-dns.sh` and `scripts/tailscale-private-dns-check.py`.

**Checkpoint**: Retirement code is reviewable but remains unexecuted until the owner applies the restricted nameserver and later cutover gates pass.

---

## Phase 6: Polish, delivery, and owner handoff

- [X] T026 [P] Explain architecture, DNS query behavior, on-demand tailnet-path health check, signed proxy recovery, restricted nameserver setting, exit-node option, record-retirement gates, cache wait, and fail-closed rollback in `clusters/homelab/platform/tailnet-dns/README.md`, `docs/networking-tailnet-ingress.md`, and `clusters/homelab/apps/traefik/CUTOVER.md`.
- [X] T027 Refresh the affected platform inventory/topology and validation notes through the repository's native OpenWiki update path for `openwiki/workloads/inventory.md`, `openwiki/architecture/cluster-topology.md`, and `openwiki/operations/validation-gates.md`; keep generated page provenance intact.
- [ ] T028 Run `python3 -I scripts/ci/tailnet-dns-test.py`, its one-time `--initial-migration` mode, `python3 -I scripts/ci/tailnet-dns-check-test.py`,
  `python3 -I scripts/ci/tailscale-private-dns-test.py`, Helm render, Kustomize build, the Nix flake/offline/static gates, affected Terragrunt formatting/saved plan, and live pre-apply validation from
  `specs/004-tailnet-service-dns/quickstart.md`; record any unavailable gate before live changes.
- [ ] T029 After the T007 Harbor receipt and T028 gates, merge the reviewed Application/Traefik/tooling PR into `main`, then apply `IaC/stacks/tailnet-dns/stack.hcl` through the declared Terragrunt/Argo path and inspect Application, Deployment, Pod, and Service status read-only.
- [ ] T030 From the trusted signer, preview and sign only the fixed DNS proxy with `scripts/tailscale-ingress-sign.py`; then run `scripts/tailnet-dns-check.py --initial-handoff` and the
  UDP/TCP, 27-name, apex mail, unrelated-public, and HTTPS checks in `specs/004-tailnet-service-dns/quickstart.md` against the actual online Service/peer IPv4. Record the verified address
  and peer identity in private rollout evidence, not as invented static values. The initial 27-name registration and offline mutation checks establish handoff evidence; observe later live
  change convergence on the first actual reviewed name change.
- [ ] T031 Give the owner the verified IPv4 and restricted `stinkyboi.com` nameserver instruction from `docs/networking-tailnet-ingress.md`, then pause before changing tailnet DNS or executing `scripts/tailscale-private-dns.sh --retire-private`.

## Dependencies and execution order

- **Publication gate**: T001–T005 → T006 publisher-only PR merge → T007 exact-image publication. T007 blocks T029, not local manifest work.
- **Shared foundation**: T008–T013 precede the final render/approval gates and consuming PR merge. T008, T009, T011, and T012 can be developed in parallel.
- **US1**: T014–T020 depend on the foundation; T016 and T019 can proceed alongside chart authoring, then T017/T018/T020 validate the finished source.
- **US2**: T021–T022 depend on T011 and T015, and can be implemented alongside US1 validation.
- **US3**: T023–T025 depend on the 27-name baseline and reviewed cutover contract, not on a live DNS change; their execution path stays disabled by preconditions until after T031 and later owner acceptance.
- **Delivery**: T026–T028 follow code completion; T029 requires T007 and T028; T030 requires T029; T031 requires T030. The owner-controlled DNS setting and public record retirement are subsequent work, outside this handoff.

## Parallel examples

- **Foundation**: Implement `clusters/homelab/argocd/self-management/appproject.yaml`, `clusters/homelab/apps/traefik/values.yaml`, and `scripts/tailscale-ingress-sign.py`; verify existing `scripts/config/tailscale-policy.json` grants with shared tests.
- **US1**: Draft `IaC/stacks/tailnet-dns/stack.hcl` while `clusters/homelab/platform/tailnet-dns/values.yaml` is rendered and `scripts/tailnet-dns-check.py` is developed; reconcile names, image, and ports before T028.
- **US3**: Implement the `scripts/tailscale-private-dns-check.py` preflight and `scripts/tailscale-private-dns.sh` deletion path as separate reviews, then test their combined no-write and partial-retry behavior in `scripts/ci/tailscale-private-dns-test.py`.

## Implementation strategy

Publish the exact DNS image first. Build the shared approval and trust declarations, then the stateless resolver and direct-check path (US1 MVP). Enforce future reviewed registration (US2)
and prepare guarded public retirement (US3). Validate and roll out through protected `main`, sign and directly query the assigned DNS proxy, then stop at the requested owner handoff. Keep
all current public application records through that pause.
