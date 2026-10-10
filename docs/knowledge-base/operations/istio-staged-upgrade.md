# Istio staged upgrade preparation

HOME-56 is operational NO-GO. The [staged design](../../istio-staged-upgrade.md)
records chart-specific offline validation, both-layer hold requirements,
readiness/partial-stage recovery and exact remaining owners.

`specs/istio-upgrade` is inactive: six chart-specific value maps, QA's verified
chart locks through 1.30.5, and a design-only HOLD with unresolved evidence.
`scripts/ci/istio-upgrade-check.py` never deploys or accepts promotion; tests
exercise malformed values, corrupt/mismatched charts, missing target bytes,
semantic regressions and attempts to unlock the design. Gateway injection,
1.31.1 artifacts, signatures and recovery remain open.

Active stack pins, services, permissions and catalog are unchanged. Platform
Operations retains shared integration/executor ownership; HOME-3 owns
enforcement and HOME-60 owns separate Kubernetes/Talos integration. Update
[[operations/validation-gates]] only when Platform wires the reviewed checker
into shared CI. See [[architecture/gitops-flow]] for registration ownership.

Offline results do not establish live mesh health, independent access,
recovery readiness or authorization to execute.
