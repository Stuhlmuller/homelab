"""Render Argo chart sources and reject non-Harbor effective workload images."""
import importlib.util
import json
import os
from pathlib import Path
import subprocess
import tempfile

import hcl2
import yaml

ROOT = Path(__file__).resolve().parents[2]
POLICY = ROOT / "clusters/homelab/platform/image-policy"
spec = importlib.util.spec_from_file_location("image_rewrite", POLICY / "image-rewrite.py")
rewrite = importlib.util.module_from_spec(spec)
spec.loader.exec_module(rewrite)
CATALOG = rewrite.destinations(json.loads((POLICY / "images.json").read_text()))
REWRITE_NAMESPACES = {"octelium", "monitoring", "ai"}


def sources():
    for path in sorted((ROOT / "IaC/homelab/us-west-2/apps").glob("*/stack.hcl")):
        data = hcl2.loads(path.read_text())
        for block in data.get("inputs", []):
            destination = block.get("spec", {}).get("destination", {}).get("namespace")
            for source in block.get("spec", {}).get("sources", []):
                if "chart" in source and isinstance(source.get("repoURL"), str) and not source["repoURL"].startswith("${"):
                    yield path.relative_to(ROOT), destination, source
    for path in sorted((ROOT / "clusters").rglob("*.yaml")):
        for doc in yaml.safe_load_all(path.read_text()):
            if isinstance(doc, dict) and doc.get("kind") == "Application":
                source = doc.get("spec", {}).get("source", {})
                if "chart" in source:
                    yield path.relative_to(ROOT), doc["spec"]["destination"]["namespace"], source


def render(source, workdir, env):
    chart, repo, version = source["chart"], source["repoURL"], source["targetRevision"]
    helm = source.get("helm", {})
    release = helm.get("releaseName", chart)
    command = ["helm", "template", release]
    if repo.startswith("https://"):
        command.extend([chart, "--repo", repo])
    else:
        command.append("oci://" + repo + "/" + chart)
    command.extend(["--version", version])
    for value in helm.get("valueFiles", []):
        if value.startswith("$values/"):
            command.extend(["-f", str(ROOT / value.removeprefix("$values/"))])
    values = helm.get("values")
    if values is not None:
        command.extend(["-f", "-"])
    if "valuesObject" in helm:
        value_file = workdir / "values.yaml"
        value_file.write_text(yaml.safe_dump(helm["valuesObject"]))
        command.extend(["-f", str(value_file)])
    if helm.get("skipSchemaValidation"):
        command.append("--skip-schema-validation")
    if helm.get("skipTests"):
        command.append("--skip-tests")
    for parameter in helm.get("parameters", []):
        command.extend(["--set-string", parameter["name"] + "=" + parameter["value"]])
    result = subprocess.run(command, input=values, text=True, capture_output=True, env=env, timeout=120)
    if result.returncode:
        raise RuntimeError(f"{chart} render failed: {result.stderr[-1000:]}")
    return list(yaml.safe_load_all(result.stdout))


def images(value):
    if isinstance(value, dict):
        for key, child in value.items():
            if key == "image" and isinstance(child, str):
                yield child
            else:
                yield from images(child)
    elif isinstance(value, list):
        for child in value:
            yield from images(child)


def generated_images(value):
    if isinstance(value, dict):
        if isinstance(value.get("image_name"), str) and isinstance(value.get("image_version"), str):
            yield value["image_name"] + ":" + value["image_version"]
        if value.get("name") == "PROXY_IMAGE" and isinstance(value.get("value"), str):
            yield value["value"]
        for key, child in value.items():
            if key == "args" and isinstance(child, list):
                for argument in child:
                    if isinstance(argument, str) and argument.startswith("--prometheus-config-reloader="):
                        yield argument.split("=", 1)[1]
            yield from generated_images(child)
    elif isinstance(value, list):
        for child in value:
            yield from generated_images(child)


def check():
    failures = []
    count = 0
    with tempfile.TemporaryDirectory(prefix="harbor-chart-render-") as directory:
        workdir = Path(directory)
        docker = workdir / "docker"
        docker.mkdir()
        (docker / "config.json").write_text('{"auths":{}}\n')
        registry = workdir / "registry.json"
        registry.write_text('{"auths":{}}\n')
        env = os.environ.copy()
        env.update(DOCKER_CONFIG=str(docker), HELM_REGISTRY_CONFIG=str(registry),
                   HELM_CACHE_HOME=str(workdir / "cache"), HELM_CONFIG_HOME=str(workdir / "config"))
        for location, namespace, source in sources():
            count += 1
            if source["chart"] == "istiod":
                parameters = {item["name"]: item["value"] for item in source.get("helm", {}).get("parameters", [])}
                for name in ("pilot.image", "global.proxy.image", "global.proxy_init.image"):
                    image = parameters.get(name, "")
                    if not image.startswith("harbor.stinkyboi.com/") or "@sha256:" not in image:
                        failures.append(f"{location}: istiod: missing pinned {name}")
            for doc in render(source, workdir, env):
                if not isinstance(doc, dict):
                    continue
                for image in (*images(doc), *generated_images(doc)):
                    if image == "auto" and source["chart"] == "gateway":
                        continue  # Istio injection uses the pinned global.proxy.image from istiod.
                    if image.startswith("harbor.stinkyboi.com/") and "@sha256:" in image:
                        continue
                    annotations = doc.get("metadata", {}).get("annotations", {})
                    hook = annotations.get("helm.sh/hook", "")
                    if (doc.get("kind") == "Pod" and "test" in hook and namespace in REWRITE_NAMESPACES
                            and image == "busybox" and rewrite.normalize(image) in CATALOG):
                        continue  # The scoped admission webhook rewrites this hardcoded test Pod image.
                    failures.append(f"{location}: {source['chart']}: {doc.get('kind')}: {image}")
    if failures:
        raise AssertionError("Non-Harbor rendered images:\n" + "\n".join(failures))
    print(f"Harbor chart render passed: {count} Argo chart sources")


if __name__ == "__main__":
    check()
