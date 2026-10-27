#!/usr/bin/env python3
"""Check dormant reader policy selectors; live enforcement remains unproved.

The optional --upstream-root checks a clean, pinned stock chart checkout. No
protected PR job supplies that checkout yet, so the chart check is a named
future gate and must not be cited as current source coverage.
"""

import argparse
import copy
import importlib.util
import json
from pathlib import Path
import subprocess
import sys
import unittest


ROOT = Path(__file__).resolve().parents[2]
APP = ROOT / "clusters/homelab/apps/openclaw-enterprise"
FOUNDATION = ROOT / "clusters/homelab/apps/openclaw-enterprise-foundation"
OPTIONS = argparse.ArgumentParser(add_help=False)
OPTIONS.add_argument("--upstream-root", type=Path)
ARGS, REMAINING = OPTIONS.parse_known_args()
sys.argv[1:] = REMAINING
UPSTREAM = ARGS.upstream_root


def load(name, relative):
    spec = importlib.util.spec_from_file_location(name, ROOT / relative)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


INVENTORY = load("oce_policy_inventory", "scripts/network-policy-inventory.py")
READER = load("oce_reader_pod", "scripts/ci/openclaw-enterprise-reader-pod.py")
SHA = "a" * 40
IMAGE = ("harbor.stinkyboi.com/homelab/homelab-oce-restore:homelab-" +
         SHA + "@sha256:" + "b" * 64)


def docs(text):
    output = subprocess.run(["yq", "ea", "-o=json", "-I=0", "[.]", "-"],
                            input=text, text=True, check=True, capture_output=True,
                            timeout=30).stdout
    return [item for item in json.loads(output) if isinstance(item, dict)]


def render(path):
    output = subprocess.run(["kubectl", "kustomize", str(path)], check=True,
                            capture_output=True, text=True, timeout=60).stdout
    return docs(output)


def policies(items):
    return [item for item in items if item.get("kind") == "NetworkPolicy"]


def assert_isolated(items, reader_pods):
    """Reject any additive allow selecting either reader in rendered source."""
    expected = {"operator": "occ-operator-reader-isolation",
                "tenant": "occ-tenant-reader-isolation"}
    for kind, pod in reader_pods.items():
        namespace = pod["metadata"]["namespace"]
        labels = pod["metadata"]["labels"]
        selected = {"Ingress": set(), "Egress": set()}
        for item in policies(items):
            metadata, spec = item.get("metadata"), item.get("spec")
            if not isinstance(metadata, dict) or not isinstance(spec, dict):
                raise AssertionError("Reader NetworkPolicy is malformed")
            if (metadata.get("namespace") or "openclaw-system") != namespace:
                continue
            if not INVENTORY.selector_matches(spec.get("podSelector"), labels):
                continue
            for direction in INVENTORY.policy_types(spec):
                if spec.get(direction.lower()):
                    raise AssertionError(
                        f"{namespace}/{metadata.get('name')} allows reader {direction}")
                selected[direction].add(metadata.get("name"))
        for direction in ("Ingress", "Egress"):
            if expected[kind] not in selected[direction]:
                raise AssertionError(f"{namespace} reader {direction} deny is absent")


class ReaderPolicySource(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.reader_pods = READER.render(SHA, "c" * 64, IMAGE,
                                        "gateway-state-123456abcdef")
        cls.local = render(FOUNDATION) + render(APP)
        if UPSTREAM is not None:
            revision = json.loads((ROOT / "builds/openclaw-enterprise/source.json")
                                  .read_text())["revision"]
            actual = subprocess.run(["git", "-C", str(UPSTREAM), "rev-parse", "HEAD"],
                                    check=True, capture_output=True, text=True,
                                    timeout=30).stdout.strip()
            if actual != revision:
                raise AssertionError("Reader chart checkout differs from pinned source")
            dirty = subprocess.run(["git", "-C", str(UPSTREAM), "status", "--porcelain"],
                                   check=True, capture_output=True, text=True,
                                   timeout=30).stdout
            if dirty:
                raise AssertionError("Reader chart checkout is dirty")
            chart = UPSTREAM / "deploy/helm/openclaw-enterprise"
            output = subprocess.run([
                "helm", "template", "oce", str(chart), "--namespace",
                "openclaw-system", "--values", str(APP / "values.yaml")],
                check=True, capture_output=True, text=True, timeout=60).stdout
            cls.chart = docs(output)
        else:
            cls.chart = None

    def test_rendered_foundation_and_local_hooks_have_only_reader_denies(self):
        assert_isolated(self.local, self.reader_pods)

    def test_additive_matching_allow_is_rejected(self):
        for kind, pod in self.reader_pods.items():
            with self.subTest(kind=kind):
                extra = {"kind": "NetworkPolicy",
                         "metadata": {"name": "foreign-allow",
                                      "namespace": pod["metadata"]["namespace"]},
                         "spec": {"podSelector": {}, "policyTypes": ["Egress"],
                                  "egress": [{"to": [{"ipBlock": {"cidr": "0.0.0.0/0"}}]}]}}
                with self.assertRaises(AssertionError):
                    assert_isolated([*self.local, extra], self.reader_pods)
                if kind == "operator":
                    extra["metadata"]["namespace"] = None
                    with self.assertRaises(AssertionError):
                        assert_isolated([*self.local, extra], self.reader_pods)

    def test_changed_reader_selector_or_missing_deny_is_rejected(self):
        altered = copy.deepcopy(self.local)
        altered = [item for item in altered if item.get("metadata", {}).get("name") !=
                   "occ-tenant-reader-isolation"]
        with self.assertRaises(AssertionError):
            assert_isolated(altered, self.reader_pods)

    @unittest.skipUnless(UPSTREAM is not None,
                         "pinned stock chart overlap requires --upstream-root; no protected gate yet")
    def test_pinned_stock_chart_has_no_reader_allow(self):
        assert_isolated([*self.local, *self.chart], self.reader_pods)


if __name__ == "__main__":
    unittest.main()
