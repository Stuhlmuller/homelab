"""Validate the rendered database prerequisite without accessing credentials."""

import copy
import json
from pathlib import Path
import subprocess

ROOT = Path(__file__).resolve().parents[2]


def check(objects):
    indexed = {(item["kind"], item["metadata"]["name"]): item for item in objects}
    statefulset = indexed["StatefulSet", "litellm-postgres"]
    pod = statefulset["spec"]["template"]["spec"]
    assert not pod["automountServiceAccountToken"]
    assert pod["securityContext"]["runAsNonRoot"]
    assert statefulset["spec"]["replicas"] == 1
    claim = statefulset["spec"]["volumeClaimTemplates"][0]
    assert claim["spec"]["storageClassName"] == "nfs-default"
    assert claim["spec"]["resources"]["requests"]["storage"] == "20Gi"
    container = pod["containers"][0]
    env = {item["name"]: item for item in container["env"]}
    assert "POSTGRES_PASSWORD" not in env
    assert env["POSTGRES_PASSWORD_FILE"]["value"] == "/run/secrets/litellm-postgres/POSTGRES_PASSWORD"
    for probe in ("readinessProbe", "livenessProbe"):
        assert container[probe]["exec"]["command"][-1] == "SELECT 1"
    client = indexed["ExternalSecret", "litellm-postgres-client"]["spec"]
    assert set(client["target"]["template"]["data"]) == {"password"}
    assert [item["remoteRef"]["key"] for item in client["data"]] == [
        "/homelab/litellm/postgres-app-password"]
    auth = indexed["ExternalSecret", "litellm-postgres-auth"]["spec"]
    assert {item["remoteRef"]["key"] for item in auth["data"]} == {
        "/homelab/litellm/postgres-admin-password", "/homelab/litellm/postgres-app-password"}
    policy = indexed["AuthorizationPolicy", "litellm-postgres"]["spec"]
    assert policy["rules"] == [{"from": [{"source": {"principals": [
        "cluster.local/ns/ai/sa/litellm"]}}], "to": [{"operation": {"ports": ["5432"]}}]}]
    init = indexed["ConfigMap", "litellm-postgres-initdb"]["data"]["00-create-litellm-database.sh"]
    assert "CREATE USER litellm WITH PASSWORD :'app_password';" in init
    assert "SUPERUSER" not in init
    assert "CREATE DATABASE litellm OWNER litellm;" in init


if __name__ == "__main__":
    rendered = subprocess.check_output([
        "kubectl", "kustomize", str(ROOT / "clusters/homelab/apps/litellm")], text=True)
    objects = json.loads(subprocess.check_output([
        "yq", "ea", "-o=json", "-I=0", "[.]", "-"], input=rendered, text=True))
    check(objects)
    for target, mutate in (
        ("litellm-postgres-client", lambda obj: obj["spec"]["data"][0]["remoteRef"].update(
            key="/homelab/litellm/postgres-admin-password")),
        ("litellm-postgres", lambda obj: obj["spec"].update(rules=[])),
    ):
        changed = copy.deepcopy(objects)
        kind = "ExternalSecret" if target.endswith("client") else "AuthorizationPolicy"
        mutate(next(obj for obj in changed if obj["kind"] == kind and obj["metadata"]["name"] == target))
        try:
            check(changed)
        except AssertionError:
            continue
        raise AssertionError("Unsafe database contract accepted")
    print("LiteLLM database isolation, persistence, file secrets and negative checks passed")
