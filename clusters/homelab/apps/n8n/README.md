# n8n Desired State

n8n runs as a self-hosted automation service behind the tailnet-only Istio
gateway at `https://n8n.stinkyboi.com`.

The app persists `/home/node/.n8n` on the default NFS StorageClass so workflows,
SQLite data, credentials metadata, and instance settings survive pod restarts.
The `N8N_ENCRYPTION_KEY` value comes from AWS SSM Parameter Store through
External Secrets and must remain stable for the life of the instance so saved
credentials can be decrypted after restarts or restores.

## Runtime Secret Contract

- `/homelab/n8n/encryption-key`: stable n8n instance encryption key. Replace the
  Terragrunt-created placeholder with a strong random value before storing real
  credentials in n8n.

## Access Contract

- Host: `https://n8n.stinkyboi.com`
- Ingress: `istio-system/tailnet-gateway`
- Public Funnel: disabled
