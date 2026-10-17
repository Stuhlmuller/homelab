# Argo CD Image Updater

This directory contains the paused Argo CD Image Updater source. `values.yaml`
keeps replicas at zero until the Harbor automation contract and recovery gates
pass. Targets are generated from the Harbor enrollment file.

See `docs/argocd-image-updater.md` for promotion and recovery verification.
