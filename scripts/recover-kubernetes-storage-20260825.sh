#!/usr/bin/env bash
set -euo pipefail

readonly context="admin@homelab"
readonly server="https://10.1.0.199:6443"
readonly recovery_pod="etcd-corruption-recovery-20260825"
readonly restore_backup_job="media-postgres-etcd-rollback-backup-20260825"
readonly media_secret_keys=$'PROWLARR_POSTGRES_HOST\nPROWLARR_POSTGRES_LOG_DB\nPROWLARR_POSTGRES_MAIN_DB\nPROWLARR_POSTGRES_PASSWORD\nPROWLARR_POSTGRES_PORT\nPROWLARR_POSTGRES_USER\nRADARR_POSTGRES_HOST\nRADARR_POSTGRES_LOG_DB\nRADARR_POSTGRES_MAIN_DB\nRADARR_POSTGRES_PASSWORD\nRADARR_POSTGRES_PORT\nRADARR_POSTGRES_USER\nSONARR_POSTGRES_HOST\nSONARR_POSTGRES_LOG_DB\nSONARR_POSTGRES_MAIN_DB\nSONARR_POSTGRES_PASSWORD\nSONARR_POSTGRES_PORT\nSONARR_POSTGRES_USER'

[[ "$(kubectl config current-context)" == "$context" ]]
[[ "$(kubectl config view --minify -o jsonpath='{.clusters[0].cluster.server}')" == "$server" ]]

media_secret_ready() {
	local actual_keys
	# shellcheck disable=SC2016 # Go-template variables, not shell variables.
	actual_keys="$(kubectl -n media get secret media-postgres-arr-env \
		-o go-template='{{range $key, $_ := .data}}{{printf "%s\n" $key}}{{end}}' \
		2>/dev/null | sort)" || return 1
	[[ "$actual_keys" == "$media_secret_keys" ]]
}

openclaw_ready_off_acer() {
	local deletion pod_name pod_state ready node
	pod_state="$(kubectl -n ai get pod -l app.kubernetes.io/name=openclaw \
		-o jsonpath='{range .items[*]}{.metadata.name}{"|"}{.spec.nodeName}{"|"}{.status.conditions[?(@.type=="Ready")].status}{"|"}{.metadata.deletionTimestamp}{"\n"}{end}' \
		2>/dev/null)" || return 1
	[[ "$pod_state" != *$'\n'* ]] || return 1
	IFS='|' read -r pod_name node ready deletion <<<"$pod_state"
	[[ -n "$pod_name" && "$node" != "acer" && "$ready" == "True" && -z "$deletion" ]]
}

prepare_restore_backup() {
	local active_backup_jobs backup_log postgres_pod postgres_replicas ready_postgres_pods
	active_backup_jobs="$(kubectl -n media get job \
		-l app.kubernetes.io/name=media-postgres-backup \
		-o jsonpath='{range .items[?(@.status.active)]}{.metadata.name}{"\n"}{end}')"
	[[ -z "$active_backup_jobs" ]]
	postgres_replicas="$(kubectl -n media get statefulset media-postgres-local \
		-o jsonpath='{.spec.replicas}')"
	if [[ "$postgres_replicas" == "0" ]]; then
		[[ "$(kubectl -n media get "job/$restore_backup_job" \
			-o jsonpath='{.status.conditions[?(@.type=="Complete")].status}')" == "True" ]]
	else
		[[ "$postgres_replicas" == "1" ]]
		kubectl -n media delete "job/$restore_backup_job" --ignore-not-found --wait=true
		kubectl -n media create job \
			--from=cronjob/media-postgres-backup \
			"$restore_backup_job" \
			--dry-run=client \
			-o json |
			kubectl patch --local -f - \
				--type=json \
				-p='[{"op":"add","path":"/spec/template/spec/tolerations","value":[{"key":"node.kubernetes.io/unschedulable","operator":"Exists","effect":"NoSchedule"}]}]' \
				-o yaml |
			kubectl create -f -
		kubectl -n media wait \
			--for=condition=Complete \
			"job/$restore_backup_job" \
			--timeout=30m
	fi
	backup_log="$(kubectl -n media logs "job/$restore_backup_job")"
	grep -Eq 'completed backup [0-9]{8}T[0-9]{6}Z: /backup/logical-backups/[0-9]{8}T[0-9]{6}Z' <<<"$backup_log"
	postgres_pod="$(kubectl -n media get pod \
		-l app.kubernetes.io/name=media-postgres,app.kubernetes.io/instance=local \
		-o jsonpath='{range .items[*]}{.metadata.name}{"\n"}{end}')"
	[[ "$postgres_pod" != *$'\n'* ]]
	kubectl cordon acer
	if [[ "$postgres_replicas" == "1" ]]; then
		[[ -n "$postgres_pod" ]]
		kubectl -n media scale statefulset/media-postgres-local --replicas=0
	fi
	if [[ -n "$postgres_pod" ]]; then
		kubectl -n media wait --for=delete "pod/$postgres_pod" --timeout=5m
	fi
	ready_postgres_pods="$(kubectl -n media get pod \
		-l app.kubernetes.io/name=media-postgres,app.kubernetes.io/instance=local \
		-o jsonpath='{range .items[*]}{.status.conditions[?(@.type=="Ready")].status}{"\n"}{end}')"
	[[ "$ready_postgres_pods" != *"True"* ]]
	printf '%s\n' "$backup_log"
}

if [[ "${1:-}" == "--prepare-restore" ]]; then
	prepare_restore_backup
	exit 0
fi

crd_state="$(kubectl get crd clustersecretstores.external-secrets.io -o name 2>&1 || true)"
secret_state="$(kubectl -n argocd get secret sh.helm.release.v1.argocd.v6 -o name 2>&1 || true)"
media_secret_state="$(kubectl -n media get secret media-postgres-arr-env -o name 2>&1 || true)"

storage_repaired=false
if [[ "$crd_state" == customresourcedefinition.apiextensions.k8s.io/clustersecretstores.external-secrets.io &&
	"$secret_state" == *"not found"* &&
	"$media_secret_state" == secret/media-postgres-arr-env ]] && media_secret_ready; then
	storage_repaired=true
fi

if [[ "$storage_repaired" == true ]] && openclaw_ready_off_acer; then
	echo "Recovery already complete."
	exit 0
fi

if [[ "$storage_repaired" != true ]]; then
	[[ "$crd_state" == *"invalid character"* || "$crd_state" == *"not found"* || "$crd_state" == customresourcedefinition.apiextensions.k8s.io/clustersecretstores.external-secrets.io ]]
	[[ "$secret_state" == *"output array was not large enough for encryption"* || "$secret_state" == *"not found"* ]]
	[[ "$media_secret_state" == *"output array was not large enough for encryption"* || "$media_secret_state" == *"not found"* || "$media_secret_state" == secret/media-postgres-arr-env ]]
	[[ "$(kubectl -n argocd get secret sh.helm.release.v1.argocd.v14 -o jsonpath='{.metadata.labels.status}')" == "deployed" ]]
fi

if [[ "${1:-}" != "--execute" ]]; then
	echo "Preflight passed. Run $0 --execute to complete the pending recovery steps."
	exit 0
fi

if [[ "$storage_repaired" != true ]]; then
	kubectl -n kube-system delete pod "$recovery_pod" --ignore-not-found --wait=true
	kubectl create -f - <<'POD'
apiVersion: v1
kind: Pod
metadata:
  name: etcd-corruption-recovery-20260825
  namespace: kube-system
spec:
  automountServiceAccountToken: false
  hostNetwork: true
  hostPID: true
  nodeName: acer
  restartPolicy: Never
  tolerations:
    - operator: Exists
  containers:
    - name: etcdctl
      image: registry.k8s.io/etcd:3.6.4-0@sha256:e36c081683425b5b3bc1425bc508b37e7107bb65dfa9367bf5a80125d431fa19
      command:
        - /bin/sh
        - -ec
        - |
          etcd() {
            etcdctl \
              --endpoints=https://127.0.0.1:2379 \
              --cacert="$certs/etcd-client-ca.crt" \
              --cert="$certs/etcd-client.crt" \
              --key="$certs/etcd-client.key" \
              "$@"
          }

          delete_if_present() {
            key="$1"
            found="$(etcd get "$key" --keys-only)"
            if [ -n "$found" ]; then
              [ "$found" = "$key" ]
              [ "$(etcd del "$key")" = "1" ]
            fi
          }

          certs=
          for certificate in /proc/[0-9]*/root/system/secrets/kubernetes/kube-apiserver/etcd-client.crt; do
            if [ -r "$certificate" ]; then
              certs="${certificate%/etcd-client.crt}"
              break
            fi
          done
          [ -n "$certs" ]

          secret_key=/registry/secrets/argocd/sh.helm.release.v1.argocd.v6
          media_secret_key=/registry/secrets/media/media-postgres-arr-env
          crd_key=/registry/apiextensions.k8s.io/customresourcedefinitions/clustersecretstores.external-secrets.io

          etcd endpoint health
          umask 077
          if [ ! -r /backup/etcd-before-corruption-repair-20260825.db ]; then
            [ "$(etcd get "$media_secret_key" --keys-only)" = "$media_secret_key" ]
            etcd snapshot save /backup/etcd-before-corruption-repair-20260825.db
          fi

          delete_if_present "$secret_key"
          delete_if_present "$media_secret_key"
          delete_if_present "$crd_key"
          etcd endpoint health
      resources:
        requests:
          cpu: 25m
          memory: 64Mi
        limits:
          memory: 256Mi
      securityContext:
        privileged: true
        readOnlyRootFilesystem: true
        runAsGroup: 0
        runAsUser: 0
      volumeMounts:
        - name: backup
          mountPath: /backup
  volumes:
    - name: backup
      hostPath:
        path: /var/mnt
        type: Directory
POD

	kubectl -n kube-system wait \
		--for=jsonpath='{.status.phase}'=Succeeded \
		"pod/$recovery_pod" \
		--timeout=5m
	kubectl -n kube-system logs "$recovery_pod"
	kubectl -n kube-system delete pod "$recovery_pod" --wait=true

	for _ in {1..60}; do
		kubectl get --raw=/readyz >/dev/null 2>&1 && break
		sleep 5
	done
	kubectl get --raw=/readyz

	for _ in {1..60}; do
		kubectl get crd clustersecretstores.external-secrets.io >/dev/null 2>&1 && break
		sleep 5
	done
	kubectl get crd clustersecretstores.external-secrets.io -o name

	for _ in {1..60}; do
		media_secret_ready && break
		sleep 5
	done
	media_secret_ready
fi

if ! openclaw_ready_off_acer; then
	acer_was_unschedulable="$(kubectl get node acer -o jsonpath='{.spec.unschedulable}')"
	kubectl cordon acer
	if [[ "$acer_was_unschedulable" != "true" ]]; then
		trap 'kubectl uncordon acer >/dev/null 2>&1 || true' EXIT
	fi
	kubectl -n ai delete pod -l app.kubernetes.io/name=openclaw --wait=true
	kubectl -n ai rollout status deployment/openclaw --timeout=20m
	openclaw_ready_off_acer
	if [[ "$acer_was_unschedulable" != "true" ]]; then
		kubectl uncordon acer
	fi
	trap - EXIT
fi

echo "Kubernetes storage repaired and OpenClaw is ready off acer."
