#!/usr/bin/env python3
"""Read-only release preflight; failures belong to the protected PR pipeline."""
import argparse
from datetime import datetime, timedelta, timezone
import json
import subprocess
import sys


def runtime_changed(paths):
    return any((path.startswith("clusters/homelab/apps/mastodon/")
                or path.startswith("IaC/") and "/mastodon/" in path)
               and not path.endswith(".md") for path in paths)


def completed_at(job, now):
    status = job.get("status", {})
    if not any(c.get("type") == "Complete" and c.get("status") == "True"
               for c in status.get("conditions", [])):
        return None
    if not isinstance(status.get("completionTime"), str):
        return None
    try:
        completed = datetime.fromisoformat(status["completionTime"].replace("Z", "+00:00"))
        if completed.tzinfo is not None and now - timedelta(hours=24) <= completed <= now:
            return completed
    except (KeyError, TypeError, ValueError):
        pass
    return None


def failures(application, cronjob, jobs, now):
    errors = []
    status = application.get("status", {})
    if status.get("sync", {}).get("status") != "Synced" or status.get("health", {}).get("status") != "Healthy":
        errors.append("Argo CD baseline is not Synced/Healthy")
    if cronjob.get("spec", {}).get("suspend", False):
        errors.append("scheduled database backup is suspended")
    backups = [job for job in jobs if any(
        owner.get("kind") == "CronJob" and owner.get("name") == "mastodon-backup"
        and owner.get("uid") == cronjob.get("metadata", {}).get("uid")
        and owner.get("controller") is True
        for owner in job.get("metadata", {}).get("ownerReferences", []))]
    backups.sort(key=lambda job: job.get("metadata", {}).get("creationTimestamp", ""))
    backup_time = completed_at(backups[-1], now) if backups else None
    if backup_time is None:
        errors.append("latest scheduled database backup has not succeeded within 24 hours")
    restored = False
    for job in jobs:
        if job.get("metadata", {}).get("labels", {}).get("app.kubernetes.io/name") != "mastodon-restore-verification":
            continue
        completed = completed_at(job, now)
        try:
            started = datetime.fromisoformat(job["status"]["startTime"].replace("Z", "+00:00"))
            pod = job["spec"]["template"]["spec"]
            claims = [v["persistentVolumeClaim"] for v in pod["volumes"] if "persistentVolumeClaim" in v]
            containers = pod.get("containers", []) + pod.get("initContainers", [])
            secret_environment = any(
                any("secretRef" in source for source in container.get("envFrom", []))
                or any("secretKeyRef" in variable.get("valueFrom", {}) for variable in container.get("env", []))
                for container in containers)
            isolated = (pod.get("automountServiceAccountToken") is False
                        and claims == [{"claimName": "mastodon-backup", "readOnly": True}]
                        and all(set(volume) <= {"name", "persistentVolumeClaim", "configMap", "emptyDir"}
                                for volume in pod["volumes"])
                        and not any(pod.get(field) for field in ("hostNetwork", "hostPID", "hostIPC"))
                        and not secret_environment)
            if (completed is not None and backup_time is not None
                    and backup_time <= started <= completed and isolated):
                restored = True
        except (AttributeError, KeyError, TypeError, ValueError):
            continue
    if not restored:
        errors.append("no fresh successful isolated database restore follows the latest backup")
    return errors


def read_json(*args):
    result = subprocess.run(["kubectl", "--request-timeout=15s", *args, "-o", "json"],
                            capture_output=True, text=True, timeout=25, check=True)
    return json.loads(result.stdout)


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--base-ref", required=True)
    args = parser.parse_args()
    try:
        paths = subprocess.run(["git", "diff", "--name-only", "-z", f"{args.base_ref}...HEAD"],
                               capture_output=True, text=True, timeout=15, check=True).stdout.split("\0")
        if not runtime_changed(paths):
            print("Mastodon runtime unchanged; database release check not applicable.")
            return 0
        application = read_json("-n", "argocd", "get", "application", "mastodon")
        cronjob = read_json("-n", "mastodon", "get", "cronjob", "mastodon-backup")
        jobs = read_json("-n", "mastodon", "get", "jobs")["items"]
        errors = failures(application, cronjob, jobs, datetime.now(timezone.utc))
        for error in errors:
            print(f"::error::Mastodon release check: {error}.", file=sys.stderr)
        if not errors:
            print("Mastodon baseline, scheduled backup and fresh isolated database restore passed.")
        return int(bool(errors))
    except (OSError, subprocess.SubprocessError, ValueError, KeyError, TypeError):
        print("::error::Mastodon release evidence unavailable; private diagnostics withheld.", file=sys.stderr)
        return 1


if __name__ == "__main__":
    sys.exit(main())
