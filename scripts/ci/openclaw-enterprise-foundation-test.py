#!/usr/bin/env python3
"""Check the dormant Enterprise namespace and secret boundary."""

import json
import subprocess
import unittest
from pathlib import Path


ROOT = Path(__file__).resolve().parents[2]
FOUNDATION = ROOT / "clusters/homelab/apps/openclaw-enterprise-foundation"
STORE = ROOT / "clusters/homelab/apps/external-secrets/cluster-secret-store.yaml"


def documents(yaml_text):
    return json.loads(subprocess.run(
        ["yq", "ea", "-o=json", "-I=0", "[.]", "-"], input=yaml_text,
        text=True, check=True, capture_output=True).stdout)


class FoundationContract(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        rendered = subprocess.check_output(
            ["kubectl", "kustomize", str(FOUNDATION)], text=True)
        cls.resources = {(item["kind"], item["metadata"]["name"]): item
                         for item in documents(rendered)}

    def test_existing_namespace_is_adoptable_but_not_policy_owned(self):
        agent = self.resources["Namespace", "openclaw-agents"]["metadata"]
        self.assertEqual(agent["annotations"]["openclaw.dev/namespace-lifecycle"], "external")
        for name in ("openclaw-system", "openclaw-agents"):
            labels = self.resources["Namespace", name]["metadata"]["labels"]
            for mode in ("enforce", "audit", "warn"):
                self.assertEqual(labels[f"pod-security.kubernetes.io/{mode}"], "restricted")
            self.assertNotIn("istio.io/dataplane-mode", labels)
        policies = [item for (kind, _), item in self.resources.items()
                    if kind == "NetworkPolicy"]
        self.assertEqual(len(policies), 1)
        self.assertEqual(policies[0]["metadata"]["namespace"], "openclaw-system")
        self.assertEqual(policies[0]["spec"], {"podSelector": {}, "policyTypes": ["Ingress"]})

    def test_tenant_roles_follow_fixed_oce_release(self):
        expected = {
            "openclaw-enterprise-worker": ("worker", "worker"),
            "openclaw-enterprise-api-secrets": ("api", "api"),
            "openclaw-enterprise-api-configuration": ("api", "configuration"),
        }
        roles = {name: item for (kind, name), item in self.resources.items()
                 if kind == "RoleBinding"}
        self.assertEqual(set(roles), set(expected))
        for name, (account, suffix) in expected.items():
            role = roles[name]
            self.assertEqual(role["metadata"]["namespace"], "openclaw-agents")
            self.assertEqual(role["roleRef"], {
                "apiGroup": "rbac.authorization.k8s.io", "kind": "ClusterRole",
                "name": f"oce-openclaw-tenant-{suffix}"})
            self.assertEqual(role["subjects"], [{
                "kind": "ServiceAccount", "name": f"openclaw-enterprise-{account}",
                "namespace": "openclaw-system"}])

    def test_secret_projections_are_exact_and_rotation_is_declared(self):
        expected = {
            "occ-postgres-admin": ("openclaw-system", "password", "postgres-admin-password"),
            "occ-postgres-migrator": ("openclaw-system", "password", "postgres-migrator-password"),
            "occ-postgres-app": ("openclaw-system", "password", "postgres-app-password"),
            "occ-auth": ("openclaw-system", "secret", "session-auth-secret"),
            "occ-private-gateway-key": ("openclaw-system", "occ", "gateway-api-key"),
            "occ-model-api-key": ("openclaw-agents", "api-key", "model-api-key"),
        }
        secrets = {name: item for (kind, name), item in self.resources.items()
                   if kind == "ExternalSecret"}
        self.assertEqual(set(secrets), set(expected))
        for name, (namespace, key, parameter) in expected.items():
            secret = secrets[name]
            self.assertEqual(secret["metadata"]["namespace"], namespace)
            self.assertEqual(secret["metadata"]["annotations"], {
                "homelab.stuhlmuller.dev/generated-secret-revision": "v1"})
            spec = secret["spec"]
            self.assertEqual(spec["refreshPolicy"], "OnChange")
            self.assertEqual(spec["secretStoreRef"], {
                "kind": "ClusterSecretStore", "name": "aws-ssm"})
            self.assertEqual(spec["target"], {
                "name": name, "creationPolicy": "Owner", "deletionPolicy": "Retain"})
            self.assertEqual(spec["data"], [{
                "secretKey": key,
                "remoteRef": {"key": f"/homelab/openclaw-enterprise/{parameter}"}}])
        store = documents(STORE.read_text())[0]
        allowed = store["spec"]["conditions"][0]["namespaces"]
        self.assertTrue({"openclaw-system", "openclaw-agents"} <= set(allowed))
        config = json.loads((ROOT / "scripts/config/openclaw-enterprise.json").read_text())
        self.assertFalse(config["activationEnabled"])


if __name__ == "__main__":
    unittest.main()
