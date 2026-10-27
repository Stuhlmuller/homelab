# Dormant Enterprise restore runtime

`Dockerfile` layers the official age v1.3.1 Linux amd64 release, checked by its
SHA-256, onto the public digest-pinned PostgreSQL 18 source in the reviewed
Harbor catalog. It adds Python, jq, mountpoint, and the streaming tar
validator/extractor. The protected `openclaw-enterprise-images.yml` workflow
builds it from a clean exact-main checkout before credentials. A complete
private Grype scan checks the exact local image ID, Linux amd64, Debian 12,
scanner and database freshness, unfiltered findings, and available fixes.
The same unpublished image embeds the namespace-local claim reader. Its
clean-source build runs the reader as UID 1000 with network disabled and a
read-only root, and compares the embedded bytes with reviewed source. A
source-only Pod renderer requires the exact source-tagged Harbor digest; it is
excluded from GitOps until a protected publication receipt, claim access,
continuous writer fence and enforced egress are proven.
The publisher accepts only that scanned image ID, pushes
`homelab/homelab-oce-restore:homelab-<main-sha>`, verifies the remote digest
and a full authenticated pull, and verifies its Harbor signature. The second
job validates and uploads the immutable restore reference as a 30-day
receipt artifact tied to the workflow run. No image is published by this
source change. Record a successful protected run and digest, then separately
review the `restore-drill.yaml` digest pin before using that excluded Job.
The packager also checks age v1.3.1; its future backup Job needs a published
runtime and an injected public recipient at `/run/backup-recipient/age.pub`.
Before writing ciphertext off-node, it checks the staged archive against the
restore limits: 32 GiB of file bytes, 100,000 entries, 64 path components,
4,096 bytes per path, 255 bytes per component, and 16 MiB of path names in
total. Private command details stay in local scratch and are removed on exit;
Pod logs contain only fixed stages and results.

The Job also requires a private `occ-backup-publication-receipt` Secret with
`archive` and `sha256` files, plus a separate private
`occ-backup-restore-identity` Secret with an `identity` file. The receipt must
come from a protected publication path that attests the exact encrypted
archive; a caller-supplied hash is not independent backup evidence. No such
producer or restore key is declared yet. Size local scratch for the ciphertext,
extracted recovery set, and restored PostgreSQL data. The candidate currently
caps extracted files at 32 GiB and reserves 96 GiB of ephemeral storage with
a 128 GiB limit; these are provisional fail-closed bounds, not a capacity
receipt. Prove measured capacity and an independent restore before scheduling
or activating it.
