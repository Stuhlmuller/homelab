#!/usr/bin/env python3
"""Render dormant namespace-local recovery readers; never create Pods.

The future protected coordinator must authenticate claim UIDs and Pod UIDs,
prove a continuous writer and network fence, and use private exec for capture.
The reader command must never stream recovery bytes into Pod logs.
"""

import re


SHA = re.compile(r"[0-9a-f]{40}\Z")
HEX64 = re.compile(r"[0-9a-f]{64}\Z")
GATEWAY = re.compile(r"gateway-state-[0-9a-f]{12}\Z")
IMAGE = re.compile(
    r"harbor\.stinkyboi\.com/homelab/homelab-oce-restore:homelab-"
    r"([0-9a-f]{40})@sha256:[0-9a-f]{64}\Z")


class Blocked(RuntimeError):
    pass


def render(source_sha, backup_id, image, gateway_claim):
    """Return only the two Pod objects for a future guarded coordinator."""
    image_match = IMAGE.fullmatch(image) if isinstance(image, str) else None
    if (not isinstance(source_sha, str) or not SHA.fullmatch(source_sha) or
            not isinstance(backup_id, str) or not HEX64.fullmatch(backup_id) or
            not isinstance(gateway_claim, str) or not GATEWAY.fullmatch(gateway_claim) or
            image_match is None or image_match.group(1) != source_sha):
        raise Blocked("Enterprise reader Pod identity or image is invalid")

    def pod(kind, namespace, claims):
        suffix = backup_id[:40]
        return {
            "apiVersion": "v1", "kind": "Pod",
            "metadata": {
                "name": f"occ-reader-{kind}-{suffix}",
                "namespace": namespace,
                "labels": {"app.kubernetes.io/name": "occ-recovery-reader",
                           "app.kubernetes.io/component": kind},
                "annotations": {"homelab.dev/source-sha": source_sha,
                                "homelab.dev/backup-id": backup_id},
            },
            "spec": {
                "automountServiceAccountToken": False,
                "hostNetwork": False, "hostPID": False, "hostIPC": False,
                "enableServiceLinks": False,
                "restartPolicy": "Never",
                "activeDeadlineSeconds": 7200,
                "securityContext": {"runAsUser": 1000, "runAsNonRoot": True,
                                    "seccompProfile": {"type": "RuntimeDefault"}},
                "volumes": [
                    {"name": key, "persistentVolumeClaim": {
                        "claimName": name, "readOnly": True}}
                    for key, name in claims.items()
                ],
                "containers": [{
                    "name": "reader", "image": image,
                    "imagePullPolicy": "IfNotPresent",
                    "command": ["/bin/sleep", "7200"],
                    "volumeMounts": [
                        {"name": key, "mountPath": "/source/" + key,
                         "readOnly": True} for key in claims
                    ],
                    "securityContext": {"allowPrivilegeEscalation": False,
                                        "readOnlyRootFilesystem": True,
                                        "capabilities": {"drop": ["ALL"]}},
                    "resources": {"requests": {"cpu": "50m", "memory": "256Mi"},
                                  "limits": {"cpu": "500m", "memory": "512Mi"}},
                }],
            },
        }

    return {
        "operator": pod("operator", "openclaw-system", {
            "journal": "occ-operator-journal",
            "bootstrap": "occ-bootstrap-admin-password",
        }),
        "tenant": pod("tenant", "openclaw-agents", {"gateway": gateway_claim}),
    }
