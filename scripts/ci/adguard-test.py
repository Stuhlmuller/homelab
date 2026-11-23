#!/usr/bin/env python3
"""Validate AdGuard manifests and render its secret template with synthetic data."""
import copy
import importlib.util
import json
from pathlib import Path
import subprocess
import sys
import tempfile
import unittest

ROOT = Path(__file__).resolve().parents[2]
APP = ROOT / "clusters/homelab/apps/adguard"
DIGEST = "sha256:e2e1b48c832f7705be915873f95de0d5114de573736441d7f2923a8a6293027c"
# Deliberately weak, synthetic 32-character input; never a deployed credential.
FIXTURE_PASSWORD = "fixture1" * 4


def documents():
    rendered = subprocess.check_output(["kubectl", "kustomize", str(APP)], text=True)
    return json.loads(subprocess.check_output(
        ["yq", "ea", "-o=json", "-I=0", "[.]", "-"], input=rendered, text=True))


def render_config(password=FIXTURE_PASSWORD):
    """Helm and ESO use the same Sprig bcrypt/JSON functions; fixture data only."""
    secret = next(d for d in documents() if d["kind"] == "ExternalSecret")
    template = secret["spec"]["target"]["template"]["data"]["config.json"]
    with tempfile.TemporaryDirectory(prefix="adguard-template-") as temp:
        chart = Path(temp)
        (chart / "templates").mkdir()
        (chart / "Chart.yaml").write_text("apiVersion: v2\nname: fixture\nversion: 0.1.0\n")
        (chart / "values.yaml").write_text(json.dumps({"password": password}))
        (chart / "templates/config.yaml").write_text(
            '{{- define "config" -}}' + template + '{{- end -}}\n'
            'apiVersion: v1\nkind: ConfigMap\nmetadata: {name: fixture}\ndata:\n'
            '  config.json: {{ include "config" (dict "password" .Values.password) | quote }}\n')
        result = subprocess.run(["helm", "template", "fixture", str(chart)],
                                capture_output=True, text=True, timeout=30, check=False)
        if result.returncode:
            raise ValueError("Synthetic AdGuard template rejected")
        output = json.loads(subprocess.check_output(
            ["yq", "-o=json", ".", "-"], input=result.stdout, text=True))
        return json.loads(output["data"]["config.json"])


class AdGuardManifestTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.docs = documents()

    def resource(self, kind, name):
        return next(d for d in self.docs if d["kind"] == kind and d["metadata"]["name"] == name)

    def test_single_nonroot_writer_and_bounded_privileges(self):
        deployment = self.resource("Deployment", "adguard")["spec"]
        self.assertEqual(deployment["replicas"], 1)
        self.assertEqual(deployment["strategy"]["type"], "Recreate")
        self.assertEqual(deployment["template"]["metadata"]["labels"]["istio.io/dataplane-mode"], "none")
        pod = deployment["template"]["spec"]
        self.assertFalse(pod["automountServiceAccountToken"])
        for key in ("runAsUser", "runAsGroup", "fsGroup"):
            self.assertEqual(pod["securityContext"][key], 65534)
        self.assertTrue(pod["securityContext"]["runAsNonRoot"])
        self.assertEqual(pod["securityContext"]["seccompProfile"]["type"], "RuntimeDefault")
        self.assertFalse(pod.get("hostNetwork", False))
        for container in pod["containers"] + pod["initContainers"]:
            security = container["securityContext"]
            self.assertFalse(security["allowPrivilegeEscalation"])
            self.assertTrue(security["readOnlyRootFilesystem"])
            self.assertEqual(security["capabilities"]["drop"], ["ALL"])
            self.assertEqual(security["capabilities"].get("add", []),
                             ["NET_BIND_SERVICE"] if container["name"] == "adguard" else [])
            self.assertIn("requests", container["resources"])
            self.assertIn("limits", container["resources"])
            self.assertNotIn("env", container)
            self.assertTrue(all("hostPort" not in p for p in container.get("ports", [])))
        runtime, = pod["containers"]
        self.assertTrue(runtime["image"].startswith("harbor.stinkyboi.com/mirror/"))
        self.assertTrue(runtime["image"].endswith("@" + DIGEST))
        for probe in ("startupProbe", "readinessProbe", "livenessProbe"):
            self.assertIn("tcpSocket", runtime[probe])
            self.assertLessEqual(runtime[probe]["timeoutSeconds"], 3)

    def test_dns_only_tailnet_service_and_private_admin(self):
        dns = self.resource("Service", "adguard-dns")
        self.assertEqual(dns["spec"]["type"], "LoadBalancer")
        self.assertIs(dns["spec"].get("allocateLoadBalancerNodePorts"), False)
        self.assertEqual(dns["spec"]["loadBalancerClass"], "tailscale")
        self.assertEqual(dns["metadata"]["annotations"]["tailscale.com/hostname"], "homelab-adguard")
        self.assertEqual(dns["metadata"]["annotations"]["tailscale.com/tags"], "tag:homelab-ingress")
        self.assertEqual({(p["protocol"], p["port"]) for p in dns["spec"]["ports"]},
                         {("UDP", 53), ("TCP", 53)})
        admin = self.resource("Service", "adguard-admin")
        self.assertEqual(admin["spec"]["type"], "ClusterIP")
        self.assertEqual([p["port"] for p in admin["spec"]["ports"]], [3000])
        self.assertFalse(any(d["kind"] in ("Ingress", "Namespace") for d in self.docs))
        self.assertFalse(any("funnel" in json.dumps(d).lower() for d in self.docs))

    def test_retained_storage_and_revision_driven_secret(self):
        pvc = self.resource("PersistentVolumeClaim", "adguard-work")
        self.assertEqual(pvc["spec"]["storageClassName"], "nfs-default")
        self.assertEqual(pvc["spec"]["resources"]["requests"]["storage"], "1Gi")
        self.assertEqual(pvc["metadata"]["annotations"]["argocd.argoproj.io/sync-options"], "Prune=false,Delete=false")
        secret = self.resource("ExternalSecret", "adguard-config")
        self.assertEqual(secret["spec"]["refreshPolicy"], "OnChange")
        self.assertIn("homelab.stuhlmuller.dev/generated-secret-revision", secret["metadata"]["annotations"])
        self.assertEqual(secret["spec"]["data"], [{"secretKey": "password", "remoteRef": {
            "key": "/homelab/adguard/admin-password", "conversionStrategy": "Default",
            "decodingStrategy": "None", "metadataPolicy": "None"}}])

    def test_initialized_private_configuration(self):
        config = render_config()
        self.assertEqual(config["schema_version"], 34)
        self.assertEqual(len(config["users"]), 1)
        self.assertEqual(config["users"][0]["name"], "admin")
        self.assertRegex(config["users"][0]["password"], r"^\$2[aby]\$\d\d\$[./A-Za-z0-9]{53}$")
        self.assertNotIn(FIXTURE_PASSWORD, json.dumps(config))
        self.assertEqual(config["http"]["address"], "0.0.0.0:3000")
        self.assertFalse(config["http"]["doh"]["insecure_enabled"])
        self.assertFalse(config["tls"]["enabled"])
        self.assertFalse(config["dhcp"]["enabled"])
        self.assertIs(config["dns"]["anonymize_client_ip"], False)
        self.assertTrue(config["querylog"]["enabled"])
        self.assertEqual(config["querylog"]["size_memory"], 1000)
        self.assertFalse(config["querylog"]["file_enabled"])
        self.assertEqual(config["statistics"], {"enabled": True, "interval": "1d"})
        self.assertTrue(all(v is False for v in config["clients"]["runtime_sources"].values()))
        self.assertEqual(config["dns"]["fallback_dns"], [])
        self.assertFalse(config["dns"]["use_private_ptr_resolvers"])
        self.assertEqual(config["dns"]["upstream_dns"], [
            "1.1.1.2", "1.0.0.2", "[/stinkyboi.com/]PRIVATE_DNS_IP"])
        filtering = config["filtering"]
        self.assertTrue(filtering["protection_enabled"] and filtering["filtering_enabled"])
        self.assertEqual(filtering["blocking_mode"], "null_ip")
        self.assertEqual(filtering["blocked_response_ttl"], 10)
        self.assertEqual(filtering["filters_update_interval"], 24)
        self.assertEqual(config["filters"], [{"enabled": True, "url":
            "https://adguardteam.github.io/HostlistsRegistry/assets/filter_1.txt",
            "name": "AdGuard DNS filter", "id": 1}])

    def test_template_rejects_invalid_credentials_without_disclosing_them(self):
        for password in ("", "short", "a" * 73, "é" * 32):
            with self.subTest(length=len(password)), self.assertRaises(ValueError):
                render_config(password)


class AdGuardInitTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        spec = importlib.util.spec_from_file_location("adguard_init", APP / "init-config.py")
        cls.module = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(cls.module)
        cls.config = render_config()

    def resolver(self, *addresses):
        def resolve(host, port, family, kind):
            self.assertEqual(host, "tailnet-dns.tailnet-dns.svc.cluster.local")
            self.assertEqual(port, 53)
            return [(family, kind, 17, "", (ip, port)) for ip in addresses]
        return resolve

    def test_private_address_substitution_and_atomic_mode(self):
        with tempfile.TemporaryDirectory(prefix="adguard-init-") as tmp:
            root = Path(tmp)
            source, target = root / "source.json", root / "AdGuardHome.yaml"
            source.write_text(json.dumps(self.config))
            target.write_text("old")
            self.module.initialize(source, target, self.resolver("10.97.0.7", "10.97.0.7"))
            self.assertEqual(target.stat().st_mode & 0o777, 0o600)
            self.assertEqual(json.loads(target.read_text())["dns"]["upstream_dns"][-1],
                             "[/stinkyboi.com/]10.97.0.7")
            self.assertEqual(sorted(p.name for p in root.iterdir()), ["AdGuardHome.yaml", "source.json"])

    def test_invalid_schema_or_auth_never_replaces_working_config(self):
        variants = [{"schema_version": 35}, {"schema_version": 34.0}, {"users": []}, {"users": [{"name": "admin", "password": "plaintext"}]},
                    {"users": self.config["users"] * 2}, {"users": ["invalid"]}]
        for override in variants:
            with self.subTest(override=list(override)), tempfile.TemporaryDirectory(prefix="adguard-init-") as tmp:
                source, target = Path(tmp) / "source.json", Path(tmp) / "config.yaml"
                source.write_text(json.dumps(dict(self.config, **override)))
                target.write_text("previous valid configuration")
                with self.assertRaises(ValueError):
                    self.module.initialize(source, target, self.resolver("10.97.0.7"))
                self.assertEqual(target.read_text(), "previous valid configuration")

    def test_missing_ambiguous_and_invalid_private_addresses_are_rejected(self):
        for addresses in ((), ("10.97.0.7", "10.97.0.8"), ("127.0.0.1",), ("0.0.0.0",),
                          ("8.8.8.8",), ("169.254.0.1",), ("::1",), ("255.255.255.255",)):
            with self.subTest(addresses=addresses), self.assertRaises(ValueError):
                self.module.prepare_config(self.config, self.resolver(*addresses))

    def test_private_resolution_failure_does_not_write_config(self):
        def unavailable(*_):
            raise OSError("Synthetic resolver unavailable")
        with tempfile.TemporaryDirectory(prefix="adguard-init-") as tmp:
            source, target = Path(tmp) / "source.json", Path(tmp) / "config.yaml"
            source.write_text(json.dumps(self.config))
            with self.assertRaises(OSError):
                self.module.initialize(source, target, unavailable)
            self.assertFalse(target.exists())

    def test_unexpected_upstream_and_invalid_bcrypt_cost_fail_closed(self):
        config = copy.deepcopy(self.config)
        config["dns"]["upstream_dns"][-1] = "1.1.1.1"
        with self.assertRaises(ValueError):
            self.module.prepare_config(config, self.resolver("10.97.0.7"))
        config = copy.deepcopy(self.config)
        config["users"][0]["password"] = "$2a$99$" + "a" * 53
        with self.assertRaises(ValueError):
            self.module.prepare_config(config, self.resolver("10.97.0.7"))

    def test_cli_does_not_disclose_malformed_secret(self):
        with tempfile.TemporaryDirectory(prefix="adguard-init-") as tmp:
            source = Path(tmp) / "source.json"
            marker = "synthetic-secret-must-not-appear"
            source.write_text(marker)
            result = subprocess.run([sys.executable, str(APP / "init-config.py"), "--source", str(source)],
                                    capture_output=True, text=True, check=False)
            self.assertNotEqual(result.returncode, 0)
            self.assertNotIn(marker, result.stdout + result.stderr)
            self.assertNotIn("Traceback", result.stderr)


if __name__ == "__main__":
    unittest.main()
