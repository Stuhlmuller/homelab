#!/usr/bin/env python3
"""Copy the completed bootstrap service key from its isolated PVC into a private runner file.

The only source is the exact, ready, same-namespace reader Pod declared in Git.
Neither Kubernetes stderr nor key bytes are printed by this command.
"""

import argparse
import importlib.util
import json
import os
from pathlib import Path
import re
import stat
import subprocess
import sys


ROOT = Path(__file__).resolve().parents[1]
NAMESPACE = "openclaw-system"
READER = "oce-bootstrap-reader"
CLAIM = "occ-bootstrap-admin-password"
IMAGE = ("harbor.stinkyboi.com/mirror/docker.io/library/python:"
         "218761489de417a6eb0808e264cbdd7043ec6659fe5a61898815e9848536541d"
         "@sha256:218761489de417a6eb0808e264cbdd7043ec6659fe5a61898815e9848536541d")
KEY = "/var/lib/openclaw/bootstrap/initial-admin-service-key.json"
UID = re.compile(r"[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}\Z")

# Runs in the read-only, tokenless reader Pod. All checks precede stdout.
READ_KEY = rf"""import os, stat, sys
path = {KEY!r}
first = os.lstat(path)
if not stat.S_ISREG(first.st_mode) or first.st_uid != 1000 or stat.S_IMODE(first.st_mode) != 0o600 or not 0 < first.st_size <= 8192:
    sys.exit(2)
fd = os.open(path, os.O_RDONLY | os.O_NOFOLLOW)
try:
    second = os.fstat(fd)
    if (second.st_dev, second.st_ino, second.st_size, second.st_mode, second.st_uid) != (first.st_dev, first.st_ino, first.st_size, first.st_mode, first.st_uid):
        sys.exit(3)
    data = os.read(fd, 8193)
    if len(data) != second.st_size:
        sys.exit(4)
    sys.stdout.buffer.write(data)
finally:
    os.close(fd)
"""


def _startup():
    spec = importlib.util.spec_from_file_location(
        "openclaw_enterprise_startup", ROOT / "scripts/openclaw-enterprise-startup.py")
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


class Blocked(Exception):
    """A fixed bootstrap ownership or transport gate failed."""


def kube(*args, output=None):
    command = ["kubectl", "--request-timeout=15s", "-n", NAMESPACE, *args]
    try:
        result = subprocess.run(command, stdout=output or subprocess.PIPE,
                                stderr=subprocess.DEVNULL, check=False, timeout=45)
    except (OSError, subprocess.TimeoutExpired) as error:
        raise Blocked("private Kubernetes read failed") from error
    if result.returncode:
        raise Blocked("private Kubernetes read failed")
    return result.stdout if output is None else None


def kube_json(*args):
    try:
        return json.loads(kube(*args, "-o=json"))
    except (ValueError, TypeError) as error:
        raise Blocked("Kubernetes returned invalid object") from error


def _ready_reader(pod):
    metadata = pod.get("metadata", {})
    spec = pod.get("spec", {})
    status = pod.get("status", {})
    labels = metadata.get("labels", {})
    uid = metadata.get("uid")
    if (pod.get("kind") != "Pod" or metadata.get("name") != READER or
            metadata.get("namespace") != NAMESPACE or not isinstance(uid, str) or
            not UID.fullmatch(uid) or metadata.get("deletionTimestamp") or
            metadata.get("ownerReferences") or
            labels.get("app.kubernetes.io/name") != "openclaw-enterprise-bootstrap-reader" or
            labels.get("app.kubernetes.io/instance") != "oce" or
            labels.get("app.kubernetes.io/part-of") != "openclaw-enterprise" or
            spec.get("nodeSelector") != {"oce-role": "control"} or
            not spec.get("nodeName") or spec.get("automountServiceAccountToken") is not False or
            spec.get("enableServiceLinks") is not False or
            spec.get("hostNetwork") is True or spec.get("hostPID") is True or
            spec.get("hostIPC") is True or spec.get("initContainers") not in (None, []) or
            spec.get("ephemeralContainers") not in (None, []) or
            spec.get("shareProcessNamespace") is True or
            spec.get("restartPolicy") != "Always" or
            len(spec.get("containers", [])) != 1 or len(spec.get("volumes", [])) != 1 or
            status.get("phase") != "Running"):
        raise Blocked("bootstrap reader is absent or changed")
    container = spec["containers"][0]
    volume = spec["volumes"][0]
    security = container.get("securityContext", {})
    pod_security = spec.get("securityContext", {})
    if (container.get("name") != "reader" or container.get("image") != IMAGE or
            container.get("command") != ["python3", "-I", "-c", "import time; time.sleep(1000000000)"] or
            container.get("volumeMounts") != [{"name": "bootstrap", "mountPath": "/var/lib/openclaw/bootstrap", "readOnly": True}] or
            container.get("env") not in (None, []) or container.get("envFrom") not in (None, []) or
            container.get("lifecycle") not in (None, {}) or
            container.get("startupProbe") not in (None, {}) or
            container.get("livenessProbe", {}).get("exec") != {
                "command": ["python3", "-I", "-c", "import os; os.kill(1, 0)"]} or
            container.get("readinessProbe", {}).get("exec") != {
                "command": ["sh", "-c", "test -f /var/lib/openclaw/bootstrap/initial-admin-service-key.json"]} or
            container.get("terminationMessagePath", "/dev/termination-log") != "/dev/termination-log" or
            container.get("terminationMessagePolicy", "File") != "File" or
            security != {"allowPrivilegeEscalation": False,
                         "readOnlyRootFilesystem": True,
                         "capabilities": {"drop": ["ALL"]}} or
            pod_security != {"runAsNonRoot": True, "runAsUser": 1000,
                             "runAsGroup": 1000, "seccompProfile": {"type": "RuntimeDefault"}} or
            volume.get("name") != "bootstrap" or
            volume.get("persistentVolumeClaim") != {"claimName": CLAIM, "readOnly": True}):
        raise Blocked("bootstrap reader source is changed")
    containers = status.get("containerStatuses", [])
    if (len(containers) != 1 or containers[0].get("name") != "reader" or
            containers[0].get("ready") is not True or
            "running" not in containers[0].get("state", {}) or
            not any(item.get("type") == "Ready" and item.get("status") == "True"
                    for item in status.get("conditions", []))):
        raise Blocked("bootstrap reader is not Ready")
    return uid


def _bootstrap_finished(job):
    metadata = job.get("metadata", {})
    labels = metadata.get("labels", {})
    status = job.get("status", {})
    if (job.get("kind") != "Job" or metadata.get("name") != "oce-initialization" or
            metadata.get("namespace") != NAMESPACE or
            labels.get("app.kubernetes.io/instance") != "oce" or
            labels.get("app.kubernetes.io/component") != "initialization" or
            status.get("succeeded") != 1 or status.get("active", 0) != 0 or
            status.get("failed", 0) != 0 or
            not any(item.get("type") == "Complete" and item.get("status") == "True"
                    for item in status.get("conditions", []))):
        raise Blocked("reviewed initialization is not complete")


def _isolated(policy):
    spec = policy.get("spec", {})
    if (policy.get("kind") != "NetworkPolicy" or
            policy.get("metadata", {}).get("name") != "oce-bootstrap-reader-isolation" or
            policy.get("metadata", {}).get("namespace") != NAMESPACE or
            spec.get("podSelector") != {"matchLabels": {
                "app.kubernetes.io/name": "openclaw-enterprise-bootstrap-reader",
                "app.kubernetes.io/instance": "oce"}} or
            set(spec.get("policyTypes", [])) != {"Ingress", "Egress"} or
            spec.get("ingress") not in (None, []) or spec.get("egress") not in (None, [])):
        raise Blocked("bootstrap reader isolation is absent or changed")


def materialize(expected_sha, output):
    _startup().reviewed_main(expected_sha)
    _bootstrap_finished(kube_json("get", "job", "oce-initialization"))
    _isolated(kube_json("get", "networkpolicy", "oce-bootstrap-reader-isolation"))
    first = _ready_reader(kube_json("get", "pod", READER))
    path = Path(output)
    if not path.is_absolute() or path.exists() or path.is_symlink():
        raise Blocked("private credential destination is invalid")
    parent = path.parent
    mode = parent.stat().st_mode
    if not stat.S_ISDIR(mode) or stat.S_IMODE(mode) != 0o700:
        raise Blocked("private credential directory is invalid")
    fd = os.open(path, os.O_WRONLY | os.O_CREAT | os.O_EXCL | os.O_NOFOLLOW, 0o600)
    try:
        with os.fdopen(fd, "wb") as private:
            kube("exec", READER, "-c", "reader", "--", "python3", "-I", "-c", READ_KEY,
                 output=private)
            private.flush()
            os.fsync(private.fileno())
        if path.stat().st_size <= 0 or path.stat().st_size > 8192:
            raise Blocked("private credential size is invalid")
        if _ready_reader(kube_json("get", "pod", READER)) != first:
            raise Blocked("bootstrap reader changed during credential copy")
        _isolated(kube_json("get", "networkpolicy", "oce-bootstrap-reader-isolation"))
        _startup().reviewed_main(expected_sha)
    except BaseException:
        path.unlink(missing_ok=True)
        raise
    return first


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--expected-sha", required=True)
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args(argv)
    try:
        materialize(args.expected_sha, args.output)
    except (Blocked, OSError, ValueError) as error:
        print(f"OpenClaw Enterprise bootstrap credential blocked: {error}", file=sys.stderr)
        return 1
    print("Reviewed bootstrap reader Ready; private credential materialized")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
