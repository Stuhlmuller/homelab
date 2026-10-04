<!-- markdownlint-disable MD013 -->

# HOME-60 repository integration disposition

2026-10-04. **Preparation delivered; operational HOLD unchanged.** The isolated
integration uses #1166 `0948b5e15e1e4e91f5e40d11cbbc1bbd25d5cdae`, reuses #1162
`1d1caad4305c256201c521442dc98507b0f29b52` (tree
`2d008b857e92da5fc111a18c595580d21f81eab9`), and incorporates current main
`99deec007bf82f197960f87e9c31bbc51f0c7157`, including Wazuh. Existing proposal
branches are preserved. This is consolidation for review, not a parallel rollout.

The [replacement SRE proposal](talos-security-upgrade-2026-10.md) supersedes the
original HOME-55 attachment's sequence, rollback allowance and broader collection
request. Original attachments and review evidence remain preserved in HOME-55.
No duplicate adversarial review was commissioned.

| Finding | Integrated correction | Still required |
| --- | --- | --- |
| Controller defect during OS hops | Conditional 1.34.12 checkpoint precedes OS hops; 1.35.9 follows accepted OS/mesh | Separate bridge decision, exact benefit and expiry |
| Healthy-API rollback allowance | Removed from replacement proposal; source-stack recovery for every transition | Actual source identities, fenced boot/watch rehearsal, matching tools |
| Linked recovery provenance | Same-set capture/retrieval/integrity/restore, config/software binding and application consistency | Current independent receipts, numeric RPO/RTO/outage |
| Agent isolation | Explicit Acer Multica placement and external operator requirement | Effective mitigation and independent operator evidence |
| Mesh/network ordering | Distinct HOME-56/3 stages; worker canary cannot prove Acer or global CNI safety | Platform's stage disposition and mixed-version/fresh CNI evidence |
| Isolation defaults | Preserve effective settings; no implicit regenerated-config behavior change | Strict private four-node renders and mount/config review |
| Collection boundary | HOME-60 receipt-only request supersedes original broader request | HOME-61 custodian, existing contexts, exact revision/window and separate approval |

## Artifact reconciliation

- Reused #1162's 1.34.12 patches, immutable image evidence and focused RBAC tests.
  Added equivalent inactive 1.35.9 control-plane/worker patches and all five
  packet image indexes to Harbor's catalog. No old catalog entries removed,
  including all five 1.34.11 images, all five 1.34.12 images and Wazuh additions.
- Tags in candidate patches follow the existing ordered Talos upgrade contract;
  immutable indexes live in the catalog/evidence. Recheck tag/index equality
  before separately approved publication. No runtime image was published.
- Added non-executable client preparation profiles for all five Talos versions,
  matching the packet's advertised checksums and Recovery's source etcd defaults.
  Existing 1.11.3 scheduler pin and 3.6.5 restore guard stay intact. Missing
  3.6.14/3.7.1 tool hashes and RPC/boot compatibility are explicit blockers,
  not accepted migrations. Client binaries were not downloaded/executed here.
- All 23 chart source records remain; none gains a render/provenance pass.
  Wazuh adds literal RBAC/storage/Harbor/Talos validation scope. The original
  #1162 literal grant inventory remains historical rather than silently relabelled.
- Per-node installer identities remain unknown. No generic installer, empty
  schematic, extension choice or private configuration was invented.

## Validation and limits

On this integration: eight focused tests pass, covering both Kubernetes patch
versions plus synthetic RBAC cases; Harbor image regression passes; bootstrap
check passes. Catalog retention, component/evidence equality, five client checksum
matches, 23-source chart inventory equality and whitespace checks pass.
Full catalog check cannot start YAML extraction because `yq` is absent.
Full static runner passes bootstrap/focused tests then stops at missing
Terragrunt (exit 127). Nix is absent. Full CI, strict private renders, complete
charts/generated grants, installer validation and recovery migration remain open.
Prior public content-hash and synthetic Talos results are attributed evidence,
not rerun claims. No cluster-health or recovery-readiness claim is made.

Commits created by this integration are unsigned; signing remains an independent
gate. Review this exact published head again after any signed replacement.
Platform owns the pending mesh/CNI/installer-input disposition. Recovery and
Decision Desk own missing recovery/request evidence. Security retains the
integrated packet and Decision Review routing. The concrete operational request
cannot proceed until every independent gate is closed; October 6, 18:00 UTC
expiry retains HOLD. No merge to main, live probe, deployment, credential change
or real-data operation occurred.
