#!/usr/bin/env python3
"""Check NOFX's image-relative writes against the rendered pod's storage mounts.

Accept a JSON array of rendered resources on stdin or at the supplied path.
Upstream docker/Dockerfile.backend starts ./nofx in /app; backtest/storage.go
writes ./backtests and logger/logger.go writes ./data independently of DB_PATH.
Recheck these paths when upgrading the backend image.
"""

import copy
import json
import posixpath
import sys
from pathlib import Path


def backend(resources):
    deployments = [item for item in resources if item.get("kind") == "Deployment"
                   and item.get("metadata", {}).get("name") == "nofx-backend"
                   and item["metadata"].get("namespace") == "nofx"]
    if len(deployments) != 1:
        raise ValueError("expected one nofx/nofx-backend Deployment")
    pod = deployments[0]["spec"]["template"]["spec"]
    containers = [item for item in pod["containers"] if item["name"] == "backend"]
    if len(containers) != 1:
        raise ValueError("expected one backend container")
    return pod, containers[0]


def storage_error(path, pod, container, retained_relative=None):
    """The most specific mount owns a path, including nested read-only mounts."""
    path = posixpath.normpath(path)
    mounts = [mount for mount in container.get("volumeMounts", [])
              if path == mount["mountPath"]
              or path.startswith(mount["mountPath"].rstrip("/") + "/")]
    if not mounts:
        return f"{path} resolves to the read-only image filesystem"
    mount = max(mounts, key=lambda item: len(item["mountPath"]))
    volume = next(item for item in pod["volumes"] if item["name"] == mount["name"])
    claim = volume.get("persistentVolumeClaim", {})
    if mount.get("readOnly", False) or claim.get("readOnly", False):
        return f"{path} resolves to a read-only volume"
    if claim.get("claimName") != "nofx-data":
        return f"{path} must remain on the nofx-data PVC"
    if mount.get("subPath") or mount.get("subPathExpr"):
        return f"{path} must retain the existing PVC root, without subPath remapping"
    if retained_relative and posixpath.relpath(path, mount["mountPath"]) != retained_relative:
        return f"{path} must retain {retained_relative} at the existing PVC root"
    return None


def validate(resources):
    pod, container = backend(resources)
    errors = []
    if container.get("securityContext", {}).get("readOnlyRootFilesystem") is not True:
        errors.append("backend must keep readOnlyRootFilesystem: true")
    if container.get("command") != ["/app/nofx"]:
        errors.append("backend must launch the image binary with absolute command /app/nofx")
    workdir = container.get("workingDir", "/app")
    if not posixpath.isabs(workdir):
        errors.append("backend workingDir must be absolute")
    else:
        for relative in ("backtests", "data"):
            error = storage_error(posixpath.join(workdir, relative), pod, container)
            if error:
                errors.append(error)
    database = [item.get("value") for item in container.get("env", [])
                if item["name"] == "DB_PATH"]
    if database != ["/app/data/data.db"]:
        errors.append("DB_PATH must preserve the existing absolute /app/data/data.db")
    else:
        error = storage_error(database[0], pod, container, retained_relative="data.db")
        if error:
            errors.append(error)
    claims = [item for item in resources if item.get("kind") == "PersistentVolumeClaim"
              and item.get("metadata", {}).get("name") == "nofx-data"
              and item["metadata"].get("namespace") == "nofx"]
    if len(claims) != 1:
        errors.append("rendered resources must retain the nofx/nofx-data PVC")
    return errors


def negative_checks(resources):
    """Mutate the real rendered contract, especially mount shadowing and identity."""
    cases = ("image-workdir", "sibling-path", "relative-command", "relative-database",
             "writable-root", "readonly-claim", "remapped-database", "shadowed-backtests")
    for case in cases:
        changed = copy.deepcopy(resources)
        pod, container = backend(changed)
        if case == "image-workdir":
            container.pop("workingDir", None)
        elif case == "sibling-path":
            container["workingDir"] = "/app/data-sibling"
        elif case == "relative-command":
            container["command"] = ["./nofx"]
        elif case == "relative-database":
            for item in container["env"]:
                if item["name"] == "DB_PATH":
                    item["value"] = "data/data.db"
        elif case == "writable-root":
            container["securityContext"]["readOnlyRootFilesystem"] = False
        elif case == "readonly-claim":
            for volume in pod["volumes"]:
                if volume.get("persistentVolumeClaim", {}).get("claimName") == "nofx-data":
                    volume["persistentVolumeClaim"]["readOnly"] = True
        elif case == "remapped-database":
            for mount in container["volumeMounts"]:
                if mount["mountPath"] == "/app/data":
                    mount["mountPath"] = "/app"
        elif case == "shadowed-backtests":
            pod["volumes"].append({"name": "shadow", "emptyDir": {}})
            container["volumeMounts"].append({
                "name": "shadow", "mountPath": container["workingDir"] + "/backtests"})
        if not validate(changed):
            raise ValueError(f"runtime regression was accepted: {case}")
    return len(cases)


def main():
    source = sys.argv[1] if len(sys.argv) > 1 else "-"
    resources = json.loads(sys.stdin.read() if source == "-" else Path(source).read_text())
    errors = validate(resources)
    if errors:
        raise ValueError("; ".join(errors))
    count = negative_checks(resources)
    print(f"NOFX runtime storage: writable persisted paths, database identity, read-only root; "
          f"{count} regressions rejected")


if __name__ == "__main__":
    try:
        main()
    except (ValueError, KeyError, StopIteration) as error:
        sys.exit(f"NOFX runtime storage: {error}")
