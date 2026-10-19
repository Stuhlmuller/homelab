#!/usr/bin/env python3
"""Check the dormant stock chart candidate and its local Helm hooks."""

import copy
import hashlib
import json
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
APP = ROOT / "clusters/homelab/apps/openclaw-enterprise"
FOUNDATION = ROOT / "clusters/homelab/apps/openclaw-enterprise-foundation"
CONFIG = ROOT / "scripts/config/openclaw-enterprise.json"
UPSTREAM = None
if len(sys.argv) == 3 and sys.argv[1] == "--upstream-root":
    UPSTREAM = Path(sys.argv[2])
    sys.argv[1:] = []


def docs(text):
    return [item for item in json.loads(subprocess.run(
        ["yq", "ea", "-o=json", "-I=0", "[.]", "-"], input=text,
        text=True, check=True, capture_output=True).stdout) if isinstance(item, dict)]


def doc(text):
    return docs(text)[0]


def rendered(path):
    return docs(subprocess.check_output(["kubectl", "kustomize", str(path)], text=True))


def identity(item):
    metadata = item["metadata"]
    cluster_scoped = item["kind"] in {"ClusterRole", "ClusterRoleBinding", "GatewayClass", "Namespace"}
    return item["kind"], metadata.get("name"), "" if cluster_scoped else metadata.get("namespace", "openclaw-system")


class ChartHooksContract(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.app = rendered(APP)
        cls.foundation = rendered(FOUNDATION)
        cls.local = {identity(item): item for item in cls.app}
        cls.values = doc((APP / "values.yaml").read_text())
        cls.installation = (APP / "installation.yaml").read_bytes()
        cls.digest = hashlib.sha256(cls.installation).hexdigest()
        cls.config = json.loads(CONFIG.read_text())
        if UPSTREAM:
            chart = UPSTREAM / "deploy/helm/openclaw-enterprise"
            cls.chart = docs(subprocess.check_output([
                "helm", "template", "oce", str(chart), "--namespace", "openclaw-system",
                "--values", str(APP / "values.yaml")], text=True))
        else:
            cls.chart = []

    def test_reviewed_candidate_and_inactive_embedded_profile(self):
        expected = "occ-installation-startup-" + self.digest[:32]
        self.assertFalse(any(item["kind"] == "Secret" for item in self.foundation))
        self.assertEqual(self.digest,
                         "980de11bbc688a33741a19c9093f613e74e464d2aae897571ac61d0056593c71")
        self.assertEqual(self.values["installation"]["secretName"], expected)
        self.assertEqual(self.values["controlPlane"]["installationChecksum"], self.digest)
        self.assertFalse(self.config["activationEnabled"])
        self.assertEqual(self.config["installationPhase"], "unselected")
        self.assertEqual(self.config["agent"]["type"], "embedded")
        self.assertEqual(doc(self.installation.decode())["drivers"]["plugin"]["id"], "occ-plugin")
        self.assertEqual(self.values["bootstrap"]["adminEmail"], "operator@oce.example.invalid")
        self.assertEqual(self.values["controlPlane"]["nodeSelector"], {"oce-role": "control"})
        self.assertEqual(self.values["database"]["cidrs"], ["10.96.0.51/32"])
        self.assertEqual(self.values["cluster"]["cidrs"], ["10.96.0.1/32", "10.1.0.199/32"])
        self.assertEqual(self.values["api"]["trustedProxy"]["preset"], "generic")
        self.assertNotIn("0.0.0.0/0", self.values["api"]["trustedProxy"]["cidrs"])

    def test_hooks_have_exact_order_and_narrow_scale_permissions(self):
        expected = {
            ("ConfigMap", "oce-lifecycle-scripts"): "-40",
            ("ServiceAccount", "oce-preflight"): "-40",
            ("ServiceAccount", "oce-quiesce"): "-40",
            ("Role", "oce-preflight"): "-40",
            ("Role", "oce-quiesce"): "-40",
            ("RoleBinding", "oce-preflight"): "-40",
            ("RoleBinding", "oce-quiesce"): "-40",
            ("NetworkPolicy", "oce-lifecycle-hooks"): "-40",
            ("Job", "oce-preflight"): "-18",
            ("Job", "oce-quiesce"): "-15",
        }
        hooks = {(item["kind"], item["metadata"]["name"]): item for item in self.app
                 if "helm.sh/hook" in item["metadata"].get("annotations", {})}
        self.assertEqual(set(hooks), set(expected))
        for key, item in hooks.items():
            annotations = item["metadata"]["annotations"]
            self.assertEqual(annotations["helm.sh/hook"], "pre-install,pre-upgrade")
            self.assertEqual(annotations["helm.sh/hook-weight"], expected[key])
            self.assertEqual(annotations["helm.sh/hook-delete-policy"], "before-hook-creation")
            self.assertFalse(any(name.startswith("argocd.argoproj.io/hook") for name in annotations))
        role = hooks["Role", "oce-quiesce"]
        self.assertEqual(role["rules"], [
            {"apiGroups": ["apps"], "resources": ["deployments"],
             "resourceNames": ["openclaw-enterprise-api", "openclaw-enterprise-worker"], "verbs": ["get"]},
            {"apiGroups": ["apps"], "resources": ["deployments/scale"],
             "resourceNames": ["openclaw-enterprise-api", "openclaw-enterprise-worker"],
             "verbs": ["get", "update"]},
            {"apiGroups": [""], "resources": ["pods"], "verbs": ["get", "list"]},
        ])
        source = (APP / "check-installation.mjs").read_bytes()
        self.assertEqual(hashlib.sha256(source).hexdigest(),
                         "d6919627a375f708d4d7e8142aff8bbc783c0a0565254c4372b83b7a306ffd13")
        scripts = hooks["ConfigMap", "oce-lifecycle-scripts"]["data"]
        for name in ("check-installation.mjs", "preflight.mjs", "quiesce.py"):
            self.assertEqual(scripts[name], (APP / name).read_text())
        self.assertEqual(hooks["Job", "oce-preflight"]["spec"]["backoffLimit"], 0)
        self.assertEqual(hooks["Job", "oce-quiesce"]["spec"]["backoffLimit"], 0)

    @unittest.skipUnless(UPSTREAM, "supply --upstream-root for pinned stock chart comparison")
    def test_stock_chart_single_image_only_override(self):
        if (UPSTREAM / ".git").exists():
            self.assertEqual(subprocess.check_output(["git", "rev-parse", "HEAD"],
                             cwd=UPSTREAM, text=True).strip(),
                             self.config["source"]["revision"])
        chart = {identity(item): item for item in self.chart}
        duplicates = set(chart) & set(self.local)
        key = ("EnvoyProxy", "oce-private-gateway", "openclaw-system")
        self.assertEqual(duplicates, {key})
        expected = copy.deepcopy(chart[key])
        expected["spec"]["provider"]["kubernetes"]["envoyDeployment"]["container"] = {
            "image": "harbor.stinkyboi.com/mirror/docker.io/envoyproxy/envoy:"
                     "7369b033550a14997e5d698677b7b51f0210a80754f5d084c5caa1a78268267b"
                     "@sha256:7369b033550a14997e5d698677b7b51f0210a80754f5d084c5caa1a78268267b"
        }
        self.assertEqual(self.local[key], expected)
        for name, weight in [("oce-bootstrap-isolation", "-30"),
                             ("oce-initialization", "-10")]:
            item = next(item for item in self.chart if item["metadata"]["name"] == name)
            self.assertEqual(item["metadata"]["annotations"]["helm.sh/hook-weight"], weight)
        for component in ("api", "worker"):
            deployment = chart[("Deployment", f"openclaw-enterprise-{component}", "openclaw-system")]
            self.assertEqual(deployment["spec"]["replicas"], 1)
            self.assertEqual(deployment["spec"]["template"]["metadata"]["annotations"]["openclaw.dev/installation-checksum"], self.digest)
            volumes = deployment["spec"]["template"]["spec"]["volumes"]
            self.assertTrue(any(volume.get("secret", {}).get("secretName") == self.values["installation"]["secretName"]
                                for volume in volumes))

    @unittest.skipUnless(UPSTREAM, "supply --upstream-root for pinned stock chart comparison")
    def test_stock_chart_uses_exact_secret_keys_and_retained_file_mounts(self):
        chart = {(item["kind"], item["metadata"]["name"]): item for item in self.chart}

        def secret_env(container):
            return {entry["name"]: entry["valueFrom"]["secretKeyRef"]
                    for entry in container.get("env", [])
                    if "secretKeyRef" in entry.get("valueFrom", {})}

        for component in ("api", "worker"):
            pod = chart["Deployment", f"openclaw-enterprise-{component}"]["spec"]["template"]["spec"]
            container = pod["containers"][0]
            expected = {"OCC_DATABASE_URL": {"name": "occ-database", "key": "application-url"}}
            if component == "api":
                expected["OCC_AUTH_SECRET"] = {"name": "occ-auth", "key": "secret"}
            self.assertEqual(secret_env(container), expected)
            volumes = {volume["name"]: volume for volume in pod["volumes"]}
            self.assertEqual(volumes["installation-startup"]["secret"], {
                "secretName": self.values["installation"]["secretName"],
                "items": [{"key": "installation.yaml", "path": "installation.yaml"}]})
            self.assertEqual(volumes["database-ca"]["secret"], {
                "secretName": "occ-postgres-root", "items": [{"key": "tls.crt", "path": "tls.crt"}]})
            self.assertEqual(volumes["gateway-api-key"]["secret"], {
                "secretName": "occ-private-gateway-key", "items": [{"key": "occ", "path": "key"}]})
            mounts = {mount["name"]: mount for mount in container["volumeMounts"]}
            for name in ("installation-startup", "database-ca", "gateway-api-key"):
                self.assertTrue(mounts[name]["readOnly"])

        pod = chart["Job", "oce-initialization"]["spec"]["template"]["spec"]
        migration = next(item for item in pod["initContainers"] if item["name"] == "migration")
        bootstrap = next(item for item in pod["containers"] if item["name"] == "bootstrap")
        self.assertEqual(secret_env(migration), {
            "OCC_MIGRATION_DATABASE_URL": {"name": "occ-database", "key": "migration-url"}})
        self.assertEqual(secret_env(bootstrap), {
            "OCC_DATABASE_URL": {"name": "occ-database", "key": "application-url"},
            "OCC_AUTH_SECRET": {"name": "occ-auth", "key": "secret"}})
        volumes = {volume["name"]: volume for volume in pod["volumes"]}
        self.assertEqual(volumes["bootstrap-password-output"]["persistentVolumeClaim"], {
            "claimName": self.values["bootstrap"]["password"]["claimName"]})
        self.assertNotIn("occ-model-api-key", json.dumps(self.chart))

    @unittest.skipUnless(UPSTREAM, "supply --upstream-root for stock profile regeneration")
    def test_candidate_is_pinned_openclaw_profile_with_reviewed_gateway_name(self):
        with tempfile.TemporaryDirectory() as output:
            subprocess.run(["node", "scripts/render-installation-profile.mjs",
                            "--profile", "openclaw", "--input", str(APP / "profile-input.json"),
                            "--out-dir", output], cwd=UPSTREAM, check=True, capture_output=True, text=True)
            generated = Path(output)
            candidate = (generated / "installation.yaml").read_text().replace(
                "gatewayName: oce-agent-gateways", "gatewayName: oce-private-gateway")
            self.assertEqual(candidate.encode(), self.installation)
            original = hashlib.sha256((generated / "installation.yaml").read_bytes()).hexdigest()
            expected = (generated / "values.yaml").read_text().replace(
                "installation:\n  name: homelab\n",
                "installation:\n  name: homelab\n"
                f"  secretName: occ-installation-startup-{self.digest[:32]}\n"
                "  key: installation.yaml\n")
            expected = expected.replace(f'installationChecksum: "{original}"',
                                        f'installationChecksum: "{self.digest}"')
            expected = expected.replace("  gatewayClassName: envoy-gateway\n",
                                        "  gatewayClassName: envoy-gateway\n"
                                        "  gatewayName: oce-private-gateway\n")
            self.assertEqual(expected, (APP / "values.yaml").read_text())


if __name__ == "__main__":
    unittest.main()
