# Harbor access through Tailscale

The public mirror workflow joins the tailnet and uses Harbor's private HTTPS
hostname directly. `harbor-publish.sh <mirror-scope> --tailscale` does not require
a kubeconfig, Kubernetes calls, host-file changes or port forwarding. TLS
verification, the registry 401 challenge, separate publisher/pull robots, digest
verification and complete pulls remain required.

The workflow is dispatch-only, restricted to exact reviewed `main` and the
`homelab-production` environment. Its credential check fails when the
environment's `TAILSCALE_AUTH_KEY` is absent. The administrator-owned
[Tailscale access module](https://github.com/Stuhlmuller/homelab/blob/3b2256219bcc0cb70596a94fc17e66491e284a9f/IaC/terragrunt-catalog/modules/tailscale-access/README.md)
owns the provider key and its lifetime. Keep raw credentials in protected
credential storage and out of command arguments, logs and git.

## Identity and lifetime

The `apply` identity carries `tag:homelab-ci-apply`. Its policy grants TCP 443 to
`tag:homelab-ingress` and `tag:k8s-operator`, plus UDP/TCP 53 to the ingress-tagged
DNS resolver. Its Kubernetes binding is cluster-admin, so this credential carries
more access than Harbor alone even though the mirror does not call Kubernetes.

The provider auth key is reusable, ephemeral and preauthorized, with a 90-day
maximum lifetime. Each job uses its own private daemon state directory, accepts
tailnet DNS and declines subnet routes. The mirror verifies the official Linux
amd64 1.102.3 archive against its reviewed checksum and passes the auth key to
the native client over stdin. It verifies the authenticated production tag
before AWS access. Cleanup logs out, stops the daemon, runs native network
cleanup and deletes private job state. The job uses the existing AWS role and
Harbor robot.

## Acceptance and recovery

Protected mirror steps check actual enrollment and cleanup, strict TLS, complete
destination pulls, and platform/digest equality. Executable release checks own
readiness. A source change alone does not prove live enrollment or publication.

Revert through protected PRs to stop future workflow use. Deleting the GitHub
secret prevents future jobs from using it; auth-key revocation and removal of
already enrolled devices remain separate credential-management operations.
Preserve encrypted provider state. Restore connectivity through the declared
network path without broadening access as an automatic fallback.

## Existing verification/access limits

The saved image-updater packet records a Kubernetes read to
`10.1.0.199:6443` rejected with network-sandbox operation-not-permitted. The saved
record does not establish an immutable firewall policy or preserve an approval
review rejection; do not reinterpret it as either. No retry through another
endpoint, proxy, SSH or Talos route is authorized by this source change.

No QNAP backup share was mounted on the operator Mac at inspection. Saved
October 25 initial-backup and isolated-restore receipts are historical;
October 26-27 nightly backups failed. Current source offers no independent
Mastodon backup-receipt workflow. Fresh verification comes from executable
backup/restore checks and their Job status, rather than a document-derived
operator attestation. Do not mount a new share or route the
denied Kubernetes read through another service to manufacture acceptance.
