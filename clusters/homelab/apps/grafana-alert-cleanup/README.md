# Grafana Alert Cleanup

The one-shot Grafana alert cleanup is complete. Keep this empty Kustomize
source and its Argo CD Application registered temporarily so automated pruning
can remove the retired Job, ServiceAccount, and NetworkPolicy without orphaning
cluster resources.

After Argo CD reports this empty Application as synced and the retired resources
are confirmed absent through read-only inspection, a later repository change may
remove the Application and this tombstone directory.
