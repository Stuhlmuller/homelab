# Dormant Enterprise restore runtime

`Dockerfile` layers the official age v1.3.1 Linux amd64 release, checked by its
SHA-256, onto the PostgreSQL 18 image already pinned for the isolated restore
candidate. It also adds the streaming tar validator/extractor. The image is
source only. A protected publisher must build and scan
it, record the resulting Harbor digest, and replace the base image reference
in `restore-drill.yaml` before that excluded Job can run.
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
