# AFFiNE PostgreSQL

`affine-postgres` is the dedicated PostgreSQL 16 plus pgvector instance for
AFFiNE in the `collaboration` namespace.

Secrets come from AWS SSM:

- `/homelab/affine/postgres-admin-password`
- `/homelab/affine/postgres-app-password`

The init script creates the `affine` role, the `affine` database, and the
`vector` extension expected by AFFiNE's self-host compose bundle.

Verify after Argo CD sync:

```sh
kubectl -n collaboration get externalsecret affine-postgres-auth affine-postgres-client
kubectl -n collaboration get statefulset,pod,pvc,svc -l app.kubernetes.io/name=affine-postgres
kubectl -n collaboration exec statefulset/affine-postgres -- psql -U postgres -d affine -c '\dx'
```
