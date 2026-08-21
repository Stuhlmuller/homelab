# Grafana Alert Cleanup

The one-shot Grafana alert cleanup is complete. Keep the inert retirement
ConfigMap and its Argo CD Application registered temporarily so automated
pruning can remove the retired Job, ServiceAccount, and NetworkPolicy without
triggering Argo CD's automatic-sync safety block for an empty source.

After Argo CD reports this Application as synced and the retired resources
are confirmed absent through read-only inspection, a later repository change may
remove the Application and this tombstone directory.
