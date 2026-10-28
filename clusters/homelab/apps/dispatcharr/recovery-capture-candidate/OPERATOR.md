# Protected Dispatcharr capture candidate

This directory remains excluded from the active Dispatcharr Kustomization. The
`Dispatcharr Protected Capture Candidate` workflow is a fixed operation for a
future reviewed capture window. Do not dispatch it until a separate protected
change has scaled the `dispatcharr` Deployment to zero, left its PostgreSQL
StatefulSet ready, and installed the backup PVC and generated capture ConfigMap.
The workflow checks those conditions before starting a Job.

The workflow uses the existing `homelab-ci` Octelium Kubernetes route. That
route forwards the shared upstream kubeconfig, and its access policy currently
allows broad Kubernetes verbs. The workflow's exact-main guard, protected
`homelab-production` environment, fixed object names, source-spec hashes, and
single-run concurrency limit bound this candidate; they are **not** narrow
Kubernetes RBAC. Review that credential exposure before merging or dispatching
the workflow. Never run it from a pull request.

The runner lists the complete `media` Pod namespace, starts one unfiltered watch
at that list's resourceVersion, and uses two unscheduled barrier Pods to prove
that it observed Pod events before and after the capture Job. It aborts on a
watch disconnect, unexpected Pod event, owner/PVC/PV identity change, Job
failure, or non-ready PostgreSQL Pod. It cleans up only barrier Pods whose UID,
labels, and scheduling gate still match its run. The Job remains for private
inspection; this operation does not restore the app.

A passing run attests only Job completion and observed Pod continuity. The Job
still writes `writers_fenced:false` in `capture.json`; the paired publisher
rejects Dispatcharr. There is no offsite checksummed set or independent restore
receipt. Do not count this run as the recovery material required for a
retirement decision.
