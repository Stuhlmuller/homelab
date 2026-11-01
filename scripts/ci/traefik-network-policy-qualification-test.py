#!/usr/bin/env python3
"""Offline failure tests for private Traefik NetworkPolicy acceptance."""

import importlib.util
import json
import socket
import subprocess
import sys
import tempfile
import threading
import types
import unittest
from pathlib import Path
from unittest.mock import patch


ROOT = Path(__file__).resolve().parents[2]
SPEC = importlib.util.spec_from_file_location(
    "traefik_qualification", ROOT / "scripts/traefik-network-policy-qualification.py")
CHECK = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(CHECK)


def policy(name, namespace, selector, types, ingress=None, egress=None):
    return {"apiVersion": "networking.k8s.io/v1", "kind": "NetworkPolicy",
            "metadata": {"name": name, "namespace": namespace,
                         "uid": f"{namespace}-{name}-uid", "generation": 1,
                         "resourceVersion": "10"},
            "spec": {"podSelector": selector, "policyTypes": types,
                     "ingress": ingress or [], "egress": egress or []}}


class TraefikQualificationTests(unittest.TestCase):
    def setUp(self):
        peer = {"namespaceSelector": {"matchLabels": {"kubernetes.io/metadata.name": "traefik"}},
                "podSelector": {"matchLabels": {"app.kubernetes.io/name": "traefik"}}}
        self.signer = policy("harbor-image-signing", "harbor",
                             {"matchLabels": {"app.kubernetes.io/name": "harbor-image-signing"}},
                             ["Ingress", "Egress"], egress=[
                                 {"to": [peer], "ports": [{"protocol": "TCP", "port": 8443}]}])
        self.destination = policy("traefik", "traefik",
                                  {"matchLabels": {"app.kubernetes.io/name": "traefik"}},
                                  ["Ingress"], ingress=[
                                      {"from": [{"namespaceSelector": {"matchLabels": {
                                          "kubernetes.io/metadata.name": "harbor"}},
                                          "podSelector": {"matchLabels": {
                                              "app.kubernetes.io/name": "harbor-image-signing"}}}],
                                       "ports": [{"protocol": "TCP", "port": 8443}]}])
        self.probes = {
            "allow": {"metadata": {"labels": {"app.kubernetes.io/name": "harbor-image-signing"}}},
            "deny": {"metadata": {"labels": {"app.kubernetes.io/name": "traefik-policy-deny"}}},
        }
        self.traefik = {"metadata": {"labels": {"app.kubernetes.io/name": "traefik"}}}
        self.harbor_namespace = {"metadata": {"labels": {"kubernetes.io/metadata.name": "harbor"}}}

    def test_reviewed_placement_requires_distinct_acer_sources(self):
        target = {"node": "zimaboard-1"}
        sources = {"allow": {"node": "acer"}, "deny": {"node": "acer"}}
        self.assertIsNone(CHECK.require_reviewed_placement(target, sources))
        for changed_target, changed_sources, expected in (
                ({"node": "zimaboard-0"}, sources, "Traefik placement changed"),
                (target, {**sources, "deny": {"node": "zimaboard-0"}},
                 "source probe placement changed"),
                (target, {**sources, "allow": {"node": "zimaboard-1"}},
                 "source probe shares Traefik node")):
            with self.subTest(target=changed_target, sources=changed_sources), \
                    self.assertRaisesRegex(ValueError, expected):
                CHECK.require_reviewed_placement(changed_target, changed_sources)

    def test_reviewed_placement_matches_gitops_source(self):
        values = json.loads(subprocess.check_output(
            ["yq", "-o=json", ".", str(ROOT / "clusters/homelab/apps/traefik/values.yaml")],
            text=True))
        self.assertEqual(values["controllers"]["traefik"]["pod"]["nodeSelector"]
                         ["kubernetes.io/hostname"], CHECK.TRAEFIK_NODE)

    def inspect(self, harbor_policies=None, traefik_policies=None):
        harbor_policies = [self.signer] if harbor_policies is None else harbor_policies
        traefik_policies = [self.destination] if traefik_policies is None else traefik_policies

        def kube(*args):
            if args[:3] == ("-n", "harbor", "get"):
                return {"metadata": {}, "items": harbor_policies}
            if args[:3] == ("-n", "traefik", "get"):
                return {"metadata": {}, "items": traefik_policies}
            raise AssertionError(args)

        with patch.object(CHECK, "kubernetes_json", side_effect=kube), \
                patch.object(CHECK, "command", return_value=json.dumps(self.destination)):
            return CHECK.inspect_policies(self.probes, self.traefik, self.harbor_namespace)

    def test_matching_signer_and_unrestricted_denied_egress(self):
        self.assertIn("traefik", self.inspect())

    def test_denied_source_egress_policy_blocks_acceptance(self):
        source_block = policy("deny-source-egress", "harbor",
                              {"matchLabels": {"app.kubernetes.io/name": "traefik-policy-deny"}},
                              ["Egress"])
        with self.assertRaisesRegex(ValueError, "denied source has an Egress"):
            self.inspect([self.signer, source_block])

    def test_additive_destination_policy_blocks_acceptance(self):
        broad = policy("extra", "traefik", {}, ["Ingress"], ingress=[{}])
        with self.assertRaisesRegex(ValueError, "ingress policy selection"):
            self.inspect(traefik_policies=[self.destination, broad])

    def test_ambient_source_blocks_acceptance(self):
        self.harbor_namespace["metadata"]["labels"]["istio.io/dataplane-mode"] = "ambient"
        with self.assertRaisesRegex(ValueError, "became ambient"):
            self.inspect()

    def test_replaced_policy_changes_probe_snapshot(self):
        first = self.inspect()
        self.destination["metadata"]["uid"] = "replacement"
        self.assertNotEqual(first, self.inspect())

    def test_stale_manifest_revision_blocks_even_when_values_are_current(self):
        source_sha = "a" * 40
        stale_sha = "b" * 40
        application = {"metadata": {"name": "harbor", "uid": "application-uid"},
                       "spec": {"sources": [
                           {"repoURL": "https://helm.goharbor.io", "chart": "harbor",
                            "targetRevision": "1.19.2"},
                           {"repoURL": CHECK.REPO_URL, "path": ".", "ref": "values",
                            "targetRevision": "main"},
                           {"repoURL": CHECK.REPO_URL, "path": "clusters/homelab/apps/harbor",
                            "targetRevision": "main"}]},
                       "status": {"sync": {"status": "Synced",
                                           "revisions": ["1.19.2", source_sha, stale_sha]},
                                  "health": {"status": "Healthy"}}}
        with self.assertRaisesRegex(ValueError, "GitOps source"):
            CHECK.reviewed_application(application, "harbor", source_sha)
        application["status"]["sync"]["revisions"][2] = source_sha
        self.assertEqual(CHECK.reviewed_application(application, "harbor", source_sha)["uid"],
                         "application-uid")

    def test_out_of_sync_gitops_source_blocks_before_probing(self):
        stale = {"metadata": {"name": "harbor", "uid": "u"},
                 "status": {"sync": {"status": "OutOfSync", "revisions": ["a" * 40]},
                            "health": {"status": "Healthy"}}}
        with patch.object(CHECK, "kubernetes_json", return_value=stale), \
                self.assertRaisesRegex(ValueError, "GitOps source is not current"):
            CHECK.inspect("a" * 40)

    def test_denied_tcp_connection_is_never_a_pass(self):
        with socket.socket() as listener:
            listener.bind(("127.0.0.1", 0))
            listener.listen(1)
            port = listener.getsockname()[1]
            thread = threading.Thread(target=lambda: listener.accept()[0].close(), daemon=True)
            thread.start()
            probe = CHECK.PROBE_CODE.replace("8443", str(port))
            result = subprocess.run([sys.executable, "-c", probe, "127.0.0.1", "deny"],
                                    capture_output=True, text=True, timeout=5)
            thread.join(timeout=2)
        self.assertEqual(result.returncode, 8)
        self.assertEqual(result.stdout.strip(), "REACHABLE")

    def test_denied_source_requires_working_network_control(self):
        with socket.socket() as listener:
            listener.bind(("127.0.0.1", 0))
            listener.listen(1)
            port = listener.getsockname()[1]
            thread = threading.Thread(target=lambda: listener.accept()[0].close(), daemon=True)
            thread.start()
            code = CHECK.PROBE_CODE.replace("15008", str(port))
            healthy = subprocess.run([sys.executable, "-c", code, "127.0.0.1", "control"],
                                     capture_output=True, text=True, timeout=5)
            thread.join(timeout=2)
        broken = subprocess.run([sys.executable, "-c", code, "127.0.0.1", "control"],
                                capture_output=True, text=True, timeout=5)
        self.assertEqual((healthy.returncode, healthy.stdout.strip()), (0, "CONTROL"))
        self.assertEqual(broken.returncode, 7)

    def test_allowed_probe_accepts_split_http_status_line_only_when_complete(self):
        class Connection:
            def __init__(self, chunks):
                self.chunks = iter(chunks)

            def __enter__(self):
                return self

            def __exit__(self, *_):
                return False

            def settimeout(self, *_):
                pass

            def sendall(self, *_):
                pass

            def recv(self, *_):
                return next(self.chunks, b"")

        def run(chunks):
            connection = Connection(chunks)
            socket_module = types.SimpleNamespace(create_connection=lambda *_args, **_kwargs:
                                                  connection)
            ssl_module = types.SimpleNamespace(create_default_context=lambda:
                                               types.SimpleNamespace(wrap_socket=lambda *_args, **_kwargs:
                                                                     connection))
            with patch.dict(sys.modules, {"socket": socket_module, "ssl": ssl_module}), \
                    patch.object(sys, "argv", ["probe", "10.0.0.1", "allow"]), \
                    patch("builtins.print"):
                exec(CHECK.PROBE_CODE, {"__name__": "__main__"})

        run([b"HTTP/1.1 40", b"1 Unauthorized\r\n"])
        with self.assertRaises(SystemExit) as failure:
            run([b"HTTP/1.1 401 Unauthorized"])
        self.assertEqual(failure.exception.code, 9)

    def test_denied_http_response_or_allowed_tls_error_cannot_pass_runner(self):
        for mode, output, code in (("deny", "REACHABLE\n", 0),
                                   ("deny", "HTTP/1.1 401 Unauthorized\n", 0),
                                   ("allow", "", 7), ("control", "", 7)):
            with self.subTest(mode=mode, output=output), \
                    patch.object(CHECK.subprocess, "run", return_value=subprocess.CompletedProcess(
                        args=[], returncode=code, stdout=output, stderr="")):
                with self.assertRaisesRegex(ValueError, "PodIP probe failed"):
                    CHECK.probe(mode, "10.244.1.2")

    def test_qualification_rechecks_identity_and_brackets_denial(self):
        snapshot = {"traefik": {"ip": "10.244.1.2", "uid": "target"}}
        calls = []
        with patch.object(CHECK, "protected_source", return_value="a" * 40), \
                patch.object(CHECK, "inspect", side_effect=[snapshot, snapshot]), \
                patch.object(CHECK, "probe", side_effect=lambda mode, ip: calls.append((mode, ip))):
            self.assertTrue(CHECK.qualify()["verified"])
        self.assertEqual(calls, [(mode, "10.244.1.2") for mode in
                                 ("allow", "control", "deny", "control", "allow")])
        with patch.object(CHECK, "protected_source", return_value="a" * 40), \
                patch.object(CHECK, "inspect", side_effect=[snapshot, {"traefik": {"ip": "10.244.1.3"}}]), \
                patch.object(CHECK, "probe"):
            with self.assertRaisesRegex(ValueError, "changed during qualification"):
                CHECK.qualify()

    def test_dormant_probe_manifest_renders_as_two_pods(self):
        fixture = ROOT / "clusters/homelab/apps/harbor/traefik-network-policy-probes.yaml"
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory)
            (path / "fixtures.yaml").write_bytes(fixture.read_bytes())
            (path / "kustomization.yaml").write_text(
                "apiVersion: kustomize.config.k8s.io/v1beta1\n"
                "kind: Kustomization\nresources:\n  - fixtures.yaml\n")
            rendered = subprocess.run(["kubectl", "kustomize", str(path)],
                                      capture_output=True, text=True, check=True, timeout=15).stdout
        self.assertEqual(rendered.count("kind: Pod\n"), 2)
        self.assertIn("name: traefik-policy-allow", rendered)
        self.assertIn("name: traefik-policy-deny", rendered)
        self.assertEqual(rendered.count(f"kubernetes.io/hostname: {CHECK.PROBE_NODE}"), 2)
        self.assertNotIn(f"kubernetes.io/hostname: {CHECK.TRAEFIK_NODE}", rendered)

if __name__ == "__main__":
    unittest.main()
