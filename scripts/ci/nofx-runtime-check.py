#!/usr/bin/env python3
"""Check NOFX's persisted write paths and private image credential contract.

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


REGISTRY_AUTH_NAME = "nofx-registry-auth"
HARBOR_AUTH_NAME = "harbor-pull"
REGISTRY_AUTH_NAMES = {REGISTRY_AUTH_NAME, HARBOR_AUTH_NAME}
REGISTRY_TEMPLATE = (
    '{"auths":{"ghcr.io":{"auth":"'
    '{{ printf "rstuhlmuller:%s" .token | b64enc }}'
    '"}}}'
)
HARBOR_TEMPLATE = (
    '{"auths":{"harbor.stinkyboi.com":{"username":"robot$homelab+pull",'
    '"password":{{ .password | toJson }},"auth":"'
    '{{ printf "robot$homelab+pull:%s" .password | b64enc }}'
    '"}}}'
)


def deployment(resources, component="backend"):
    deployments = [item for item in resources if item.get("kind") == "Deployment"
                   and item.get("metadata", {}).get("name") == f"nofx-{component}"
                   and item["metadata"].get("namespace") == "nofx"]
    if len(deployments) != 1:
        raise ValueError(f"expected one nofx/nofx-{component} Deployment")
    pod = deployments[0]["spec"]["template"]["spec"]
    containers = [item for item in pod["containers"] if item["name"] == component]
    if len(containers) != 1:
        raise ValueError(f"expected one {component} container")
    return pod, containers[0]


def registry_errors(resources):
    errors = []
    secrets = [item for item in resources if item.get("kind") == "ExternalSecret"
               and item.get("metadata", {}).get("name") == REGISTRY_AUTH_NAME
               and item["metadata"].get("namespace") == "nofx"]
    if len(secrets) != 1:
        errors.append("expected one nofx/nofx-registry-auth ExternalSecret")
    else:
        spec = secrets[0]["spec"]
        if spec.get("secretStoreRef") != {"kind": "ClusterSecretStore", "name": "aws-ssm"}:
            errors.append("registry auth must use the aws-ssm ClusterSecretStore")
        if spec.get("refreshPolicy") != "Periodic" or spec.get("refreshInterval") != "5m":
            errors.append("registry auth must refresh rotated credentials every five minutes")
        if spec.get("data") != [{"secretKey": "token", "remoteRef": {
                "key": "/homelab/nofx/ghcr-read-token", "conversionStrategy": "Default",
                "decodingStrategy": "None", "metadataPolicy": "None"}}] or spec.get("dataFrom"):
            errors.append("registry auth must read only the dedicated GHCR token parameter")
        target = spec.get("target", {})
        if (target.get("name") != REGISTRY_AUTH_NAME or target.get("creationPolicy") != "Owner"
                or target.get("deletionPolicy") != "Retain"):
            errors.append("registry auth must own and retain its dedicated target Secret")
        template = target.get("template", {})
        if (template.get("engineVersion") != "v2" or template.get("mergePolicy") != "Replace"
                or template.get("type") != "kubernetes.io/dockerconfigjson"
                or template.get("data") != {".dockerconfigjson": REGISTRY_TEMPLATE}
                or template.get("templateFrom")):
            errors.append("registry auth must render only the fixed GHCR base64 credential template")
    harbor_secrets = [item for item in resources if item.get("kind") == "ExternalSecret"
                     and item.get("metadata", {}).get("name") == HARBOR_AUTH_NAME
                     and item["metadata"].get("namespace") == "nofx"]
    if len(harbor_secrets) != 1:
        errors.append("expected one nofx/harbor-pull ExternalSecret")
    else:
        harbor = harbor_secrets[0]
        spec = harbor["spec"]
        if spec.get("secretStoreRef") != {"kind": "ClusterSecretStore", "name": "aws-ssm"}:
            errors.append("Harbor pull auth must use the aws-ssm ClusterSecretStore")
        revision = harbor["metadata"].get("annotations", {}).get(
            "homelab.stuhlmuller.dev/generated-secret-revision")
        if spec.get("refreshPolicy") != "OnChange" or not revision:
            errors.append("Harbor pull auth must retain its generated-secret revision refresh contract")
        if spec.get("data") != [{"secretKey": "password", "remoteRef": {
                "key": "/homelab/nofx/harbor-pull-password", "conversionStrategy": "Default",
                "decodingStrategy": "None", "metadataPolicy": "None"}}] or spec.get("dataFrom"):
            errors.append("Harbor pull auth must read only the dedicated NOFX pull password")
        target = spec.get("target", {})
        if (target.get("name") != HARBOR_AUTH_NAME or target.get("creationPolicy") != "Owner"
                or target.get("deletionPolicy") != "Retain"):
            errors.append("Harbor pull auth must own and retain its dedicated target Secret")
        template = target.get("template", {})
        if (template.get("engineVersion") != "v2" or template.get("mergePolicy", "Replace") != "Replace"
                or template.get("type") != "kubernetes.io/dockerconfigjson"
                or template.get("data") != {".dockerconfigjson": HARBOR_TEMPLATE}
                or template.get("templateFrom")):
            errors.append("Harbor pull auth must render only the fixed read-only robot credential template")
    if any(item.get("kind") == "Secret" and item.get("metadata", {}).get("name") in REGISTRY_AUTH_NAMES
           and item["metadata"].get("namespace") == "nofx" for item in resources):
        errors.append("registry auth must not be committed as a Secret")
    for component in ("backend", "frontend"):
        pod, container = deployment(resources, component)
        image_repository = container.get("image", "").split(":", 1)[0].split("@", 1)[0]
        private_repositories = {
            f"ghcr.io/stuhlmuller/homelab-nofx-{component}": REGISTRY_AUTH_NAME,
            f"harbor.stinkyboi.com/homelab/homelab-nofx-{component}": HARBOR_AUTH_NAME,
        }
        pull_secret = private_repositories.get(image_repository)
        if image_repository.startswith("harbor.stinkyboi.com/") and pull_secret != HARBOR_AUTH_NAME:
            errors.append(f"{component} must use its exact maintained Harbor repository")
        if pull_secret and pod.get("imagePullSecrets") != [{"name": pull_secret}]:
            errors.append(f"{component} must pull private images using {pull_secret}")
        if not pull_secret and pod.get("imagePullSecrets"):
            errors.append(f"{component} must defer registry credentials until the private image rollout")
        for volume in pod.get("volumes", []):
            refs = [volume.get("secret", {}).get("secretName")]
            refs += [source.get("secret", {}).get("name")
                     for source in volume.get("projected", {}).get("sources", [])]
            if REGISTRY_AUTH_NAMES.intersection(refs):
                errors.append(f"{component} must not mount the registry credential")
        containers = pod.get("containers", []) + pod.get("initContainers", [])
        containers += pod.get("ephemeralContainers", [])
        for container in containers:
            refs = [entry.get("secretRef", {}).get("name")
                    for entry in container.get("envFrom", [])]
            refs += [entry.get("valueFrom", {}).get("secretKeyRef", {}).get("name")
                     for entry in container.get("env", [])]
            if REGISTRY_AUTH_NAMES.intersection(refs):
                errors.append(f"{component} must not expose the registry credential as environment")
    return errors


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
    pod, container = deployment(resources)
    errors = registry_errors(resources)
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
             "writable-root", "readonly-claim", "remapped-database", "shadowed-backtests",
             "backend-pull-secret", "frontend-pull-secret", "registry-parameter",
             "registry-json-injection", "registry-raw-key", "registry-refresh",
             "registry-env", "registry-mount", "registry-committed-secret",
             "harbor-backend-pull-secret", "harbor-frontend-pull-secret",
             "harbor-wrong-pull-secret", "harbor-wrong-repository", "harbor-parameter",
             "harbor-json-injection", "harbor-raw-key", "harbor-missing-secret",
             "harbor-refresh", "harbor-env", "harbor-init-env", "harbor-ephemeral-env",
             "harbor-mount", "harbor-projected-mount", "harbor-committed-secret")
    for case in cases:
        changed = copy.deepcopy(resources)
        pod, container = deployment(changed)
        registry = next(item for item in changed if item.get("kind") == "ExternalSecret"
                        and item.get("metadata", {}).get("name") == REGISTRY_AUTH_NAME)
        harbor = next(item for item in changed if item.get("kind") == "ExternalSecret"
                      and item.get("metadata", {}).get("name") == HARBOR_AUTH_NAME)
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
        elif case in ("backend-pull-secret", "frontend-pull-secret"):
            component = case.split("-")[0]
            pull_pod, pull_container = deployment(changed, component)
            pull_container["image"] = f"ghcr.io/stuhlmuller/homelab-nofx-{component}:guard-case"
            pull_pod.pop("imagePullSecrets", None)
        elif case == "registry-parameter":
            registry["spec"]["data"][0]["remoteRef"]["key"] = "/homelab/nofx/jwt-secret"
        elif case == "registry-json-injection":
            registry["spec"]["target"]["template"]["data"][".dockerconfigjson"] = (
                REGISTRY_TEMPLATE.replace('printf "rstuhlmuller:%s" .token | b64enc', '.token'))
        elif case == "registry-raw-key":
            registry["spec"]["target"]["template"]["mergePolicy"] = "Merge"
        elif case == "registry-refresh":
            registry["spec"]["refreshPolicy"] = "OnChange"
        elif case == "registry-env":
            container["envFrom"].append({"secretRef": {"name": REGISTRY_AUTH_NAME}})
        elif case == "registry-mount":
            pod["volumes"].append({"name": "registry", "projected": {
                "sources": [{"secret": {"name": REGISTRY_AUTH_NAME}}]}})
        elif case in ("registry-committed-secret", "harbor-committed-secret"):
            name = HARBOR_AUTH_NAME if case.startswith("harbor-") else REGISTRY_AUTH_NAME
            changed.append({"kind": "Secret", "metadata": {"name": name, "namespace": "nofx"}})
        elif case in ("harbor-backend-pull-secret", "harbor-frontend-pull-secret", "harbor-wrong-pull-secret"):
            component = "frontend" if case == "harbor-frontend-pull-secret" else "backend"
            pull_pod, pull_container = deployment(changed, component)
            pull_container["image"] = f"harbor.stinkyboi.com/homelab/homelab-nofx-{component}:guard-case"
            if case == "harbor-wrong-pull-secret":
                pull_pod["imagePullSecrets"] = [{"name": REGISTRY_AUTH_NAME}]
            else:
                pull_pod.pop("imagePullSecrets", None)
        elif case == "harbor-wrong-repository":
            container["image"] = "harbor.stinkyboi.com/unreviewed/homelab-nofx-backend:guard-case"
            pod.pop("imagePullSecrets", None)
        elif case == "harbor-parameter":
            harbor["spec"]["data"][0]["remoteRef"]["key"] = "/homelab/harbor/ci-push-password"
        elif case == "harbor-json-injection":
            harbor["spec"]["target"]["template"]["data"][".dockerconfigjson"] = (
                HARBOR_TEMPLATE.replace('.password | toJson', '.password'))
        elif case == "harbor-raw-key":
            harbor["spec"]["target"]["template"]["mergePolicy"] = "Merge"
        elif case == "harbor-missing-secret":
            changed.remove(harbor)
        elif case == "harbor-refresh":
            harbor["metadata"]["annotations"].pop("homelab.stuhlmuller.dev/generated-secret-revision", None)
        elif case == "harbor-env":
            container["envFrom"].append({"secretRef": {"name": HARBOR_AUTH_NAME}})
        elif case in ("harbor-init-env", "harbor-ephemeral-env"):
            field = "initContainers" if case == "harbor-init-env" else "ephemeralContainers"
            pod.setdefault(field, []).append({"name": "registry-leak", "env": [{
                "name": "REGISTRY_PASSWORD", "valueFrom": {
                    "secretKeyRef": {"name": HARBOR_AUTH_NAME, "key": ".dockerconfigjson"}}}]})
        elif case == "harbor-mount":
            pod["volumes"].append({"name": "registry", "secret": {"secretName": HARBOR_AUTH_NAME}})
        elif case == "harbor-projected-mount":
            pod["volumes"].append({"name": "registry", "projected": {
                "sources": [{"secret": {"name": HARBOR_AUTH_NAME}}]}})
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
    print(f"NOFX runtime: persisted paths, database identity, read-only root, private image auth; "
          f"{count} regressions rejected")


if __name__ == "__main__":
    try:
        main()
    except (ValueError, KeyError, StopIteration) as error:
        sys.exit(f"NOFX runtime: {error}")
