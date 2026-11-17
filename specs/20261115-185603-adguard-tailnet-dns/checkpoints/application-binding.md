# T041 Application binding correction

The preceding separate admin convergence found no admin/runtime defects. During
subsequent read-only cutover integration research, the actual generated AdGuard
registration exposed a T015 compatibility gap: the shared stack uses spec.sources
and sync.revisions, not the singular fixture. A separate convergence pass appended
T041 (HIGH partial FR001/013/019) without changing spec/plan or application code.

Updated the fixture to the actual generated single-element sources shape and
showed it failing before correction. Fixed the checker to require that shape,
its one exact revision, homelab-workloads project and automation/in-cluster
destination, rejecting nonempty legacy source alongside it. Added negative cases
for extra sources/revisions, wrong project, namespace, cluster and legacy source.
Confirmed actual generated registration projection at
/workspace/adguard-progress/adguard-registration.json matches the expected source,
project and destination. Existing verify-gitops.py independently confirms Argo's
sources/revisions selection convention. No live Application assertion.

All8 checker tests pass; git diff --check passes. Logs
/workspace/adguard-progress/adguard-application-red.log and
adguard-application-final.log. T041 complete. No runtime behavior changed, so the
previous pinned runtime6-test result remains applicable. Next separate scoped
convergence forT041, then resumeUS2 cutover/client andUS4 recovery work. No live
AdGuard/signing/DNS change, no Notion. Hooks empty.

Cutover research already read: tailscale-access module README and main.tf;
operator unit at IaC/terragrunt-catalog/units/operator/tailscale-access/terragrunt.hcl.
The separate administrator OAuth is file-backed; existing encrypted saved-plan
path uses terragrunt show/apply within operator/tailscale-access. Normal CI does
not get administrator scope. No cutover helper source has been written yet.
