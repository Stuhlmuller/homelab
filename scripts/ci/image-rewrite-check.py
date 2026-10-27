"""Validate the reviewed Octelium image rewrite catalog and admission decisions."""
import base64
import importlib.util
import json
from pathlib import Path
import subprocess

ROOT = Path(__file__).resolve().parents[2]
POLICY = ROOT / "clusters/homelab/platform/image-policy"
spec = importlib.util.spec_from_file_location("image_rewrite", POLICY / "image-rewrite.py")
module = importlib.util.module_from_spec(spec)
spec.loader.exec_module(module)

catalog = json.loads((ROOT / "scripts/config/harbor-images.json").read_text())
selected = json.loads((POLICY / "images.json").read_text())
assert selected["images"] and selected == catalog
mapping = module.destinations(selected)
for item in selected["images"]:
    source = item["source"]
    if ":" in source.split("@", 1)[0].rsplit("/", 1)[-1]:
        assert mapping[module.normalize(source)] == mapping[module.normalize(source.split("@", 1)[0])]

def check(images, *, subresource="", allowed=True):
    review = {"request": {"uid": "check", "subResource": subresource,
                          "object": {"spec": {key: [{"name": key, "image": value}]
                                               for key, value in images.items()}}}}
    result = module.mutate(review, mapping)["response"]
    assert result["uid"] == "check" and result["allowed"] is allowed
    if allowed and result.get("patch"):
        return json.loads(base64.b64decode(result["patch"]))
    return []

source = next(item["source"] for item in selected["images"]
              if ":" in item["source"].split("@", 1)[0].rsplit("/", 1)[-1])
short = source.split("@", 1)[0]
target = mapping[module.normalize(source)]
assert check({"containers": short, "initContainers": source, "ephemeralContainers": short}) == [
    {"op": "replace", "path": f"/spec/{key}/0/image", "value": target}
    for key in ("initContainers", "containers", "ephemeralContainers")]
assert check({"containers": short, "ephemeralContainers": short}, subresource="ephemeralcontainers") == [
    {"op": "replace", "path": "/spec/ephemeralContainers/0/image", "value": target}]
assert check({"containers": target}) == []
check({"containers": "harbor.stinkyboi.com/homelab/custom@sha256:" + "a" * 64}, allowed=False)
check({"containers": "unreviewed.example/app:1"}, allowed=False)
check({"initContainers": short + "@sha256:" + "0" * 64}, allowed=False)
litellm = next(item["source"] for item in selected["images"]
               if item["source"].startswith("ghcr.io/berriai/litellm-database@"))
assert check({"containers": "ghcr.io/berriai/litellm-database:main-v1.80.8-stable@"
                             + litellm.split("@", 1)[1]})[0]["value"] == mapping[module.normalize(litellm)]
check({"containers": "ghcr.io/berriai/litellm-database:main-v1.80.8-stable"}, allowed=False)
rendered = subprocess.check_output(["kubectl", "kustomize", str(POLICY)], text=True)
resources = json.loads(subprocess.check_output(
    ["yq", "ea", "-o=json", "-I=0", "[.]", "-"], input=rendered, text=True))
webhook = next(doc for doc in resources if doc.get("kind") == "MutatingWebhookConfiguration")["webhooks"][0]
assert webhook["failurePolicy"] == "Fail" and webhook["timeoutSeconds"] <= 5
assert webhook["namespaceSelector"]["matchExpressions"][0]["values"] == ["octelium", "monitoring", "ai"]
assert webhook["rules"][0]["resources"] == ["pods"] and webhook["rules"][0]["operations"] == ["CREATE"]
assert webhook["rules"][1]["resources"] == ["pods/ephemeralcontainers"] and webhook["rules"][1]["operations"] == ["UPDATE"]
deployment = next(doc for doc in resources if doc.get("kind") == "Deployment"
                  and doc["metadata"]["name"] == "image-rewrite")
assert deployment["spec"]["replicas"] >= 2
assert deployment["spec"]["template"]["spec"]["topologySpreadConstraints"]
print(f"Image rewrite checks passed: {len(selected['images'])} reviewed sources")
