# Immich

Immich v3.4.2 stores photos and videos on the retained QNAP-backed
`immich-library` claim. Its dedicated VectorChord PostgreSQL runs on
`acer` with retained local storage. Valkey holds the job queue in memory.
After a Valkey restart, requeue interrupted jobs from the Immich admin UI.
Machine learning and its dependent search and face features are disabled
to fit the available memory. Photo uploads, browsing, and sharing within
the private network use the normal Immich server.

## Access and first setup

Use [Immich](https://immich.stinkyboi.com) on the homelab tailnet. The
same URL works in the mobile app. Traefik's private route excludes
first-admin registration. A cluster operator creates the first admin
from a workstation with the homelab Kubernetes context.

```sh
kubectl -n immich port-forward svc/immich 2283:2283
```

Open [the local Immich setup](http://127.0.0.1:2283) and choose the owner
email and password. Close the port-forward, sign in over the tailnet,
and upload and download a disposable image to verify the storage path.

## Storage and recovery

- The library claim requests 250 GiB. The QNAP provisioner uses a shared
  export, so the capacity request is advisory. Check actual NAS free space
  before importing a large library.
- The 20 GiB PostgreSQL claim is node-local and advisory. A Talos wipe or
  disk failure on `acer` requires a database restore. Argo CD preserves both
  claims and their namespaces or storage resources on removal.
- External Secrets projects separate generated PostgreSQL credentials.
  Only PostgreSQL and the backup job mount the administrator password.
  Immich uses a non-superuser database owner. PostgreSQL initializes
  VectorChord and earthdistance before Immich starts. Review extension
  upgrades and database password rotation as database migrations.
- The backup CronJob writes daily PostgreSQL custom-format archives to
  `/data/postgres-dumps` and keeps approximately two weeks. It validates
  the archive table of contents before publishing each file. The database
  archive contains private metadata and must be protected like the photos.
  Keep an independent copy of the library and a matching database archive
  to recover from NAS loss. Before relying on this recovery path, restore
  both into an isolated test instance and verify representative assets.

For recovery, start a separate empty PostgreSQL instance with the same
major version and extensions. Create the application role as the init SQL
does, restore a selected archive as the database administrator with
`pg_restore --exit-on-error --single-transaction --dbname=immich`, and
mount the matching copy of the media volume. Start Immich only after the
restore completes. Check the restored account, albums, and original files
before switching traffic. Do not overwrite the only retained copy.

## Delivery and verification

The [Terragrunt unit](../../../../IaC/homelab/us-west-2/apps/immich/stack.hcl)
registers the Argo CD Application. Harbor publishes the three exact image pins
before registration. The targeted apply requires the AppProject destination,
External Secrets store namespace access, ingress, DNS, and storage to be ready.

After apply, verify Argo CD using the observed exact main commit and check
both claims, the PostgreSQL rollout, and HTTPS from the tailnet.

```sh
python3 scripts/verify-gitops.py --application immich --expected-sha <commit> \
  --deployment immich/immich --deployment immich/immich-valkey
kubectl -n immich rollout status statefulset/immich-postgres
kubectl -n immich get pvc,externalsecret
curl -fsS https://immich.stinkyboi.com/api/server/ping
```

A healthy HTTP response confirms connectivity. First sign-in and a
round-trip of a disposable image confirm the user path. Revert the reviewed
application or route to stop serving it, preserving the data claims. A Git
revert cannot undo PostgreSQL migrations or restore deleted media.
