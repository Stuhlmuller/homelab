# AFFiNE Redis

`affine-redis` provides AFFiNE's internal cache and job queue backend. It is
intentionally not persistent; AFFiNE's durable state lives in
`affine-postgres` and the AFFiNE storage PVC.

Verify after Argo CD sync:

```sh
kubectl -n collaboration get deploy,pod,svc -l app.kubernetes.io/name=affine-redis
kubectl -n collaboration exec deploy/affine-redis -- redis-cli ping
```
