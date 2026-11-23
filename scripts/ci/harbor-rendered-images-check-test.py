#!/usr/bin/env python3
"""Exercise Argo chart inventory and rendered image accounting."""

import importlib.util
import json
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch
from subprocess import CompletedProcess


spec = importlib.util.spec_from_file_location("rendered_images", Path(__file__).with_name("harbor-rendered-images-check.py"))
check = importlib.util.module_from_spec(spec)
spec.loader.exec_module(check)

class RenderedImagesTest(unittest.TestCase):
    def test_current_source_coverage(self):
        charts = list(check.sources())
        inventory = json.loads((check.ROOT / check.CHART_INVENTORY).read_text())
        check.verify_coverage(charts, inventory)
        expected = {
            "kagent": ("kagent", "kagent"),
            "kagent-crds": ("kagent", "kagent-crds"),
            "git:deploy/helm/openclaw-enterprise": ("openclaw-system", "oce"),
            "git:deploy/chart/local-path-provisioner": ("cordium-storage", "cordium-local-path-provisioner"),
        }
        found = {}
        for candidate in charts:
            entry, namespace, application, source = candidate
            chart = entry["chart"]
            if chart not in expected:
                continue
            self.assertNotIn(chart, found)
            found[chart] = namespace, source["helm"].get("releaseName", application)
            with self.subTest(chart=chart):
                remaining = [other for other in charts if other != candidate]
                with self.assertRaisesRegex(ValueError, "coverage differs"):
                    check.verify_coverage(remaining, inventory)
                with self.assertRaisesRegex(ValueError, "duplicate"):
                    check.verify_coverage(charts + [candidate], inventory)
                for key in ("repoURL", "targetRevision", "chart", "source"):
                    wrong = {**entry, key: entry[key] + "-unexpected"}
                    with self.assertRaisesRegex(ValueError, "coverage differs"):
                        check.verify_coverage(remaining + [(wrong, namespace, application, source)], inventory)
        self.assertEqual(found, expected)

    def test_git_helm_package_requires_exact_repository_path_and_revision(self):
        entry = {"source": "fixture", "repoURL": "https://github.com/fixture/chart.git",
                 "chart": "git:deploy/chart", "targetRevision": "a" * 40}
        package = {"repository": entry["repoURL"], "path": "deploy/chart",
                   "revision": entry["targetRevision"], "chart": "fixture", "version": "1.0.0"}
        self.assertEqual(check.package_for(entry, [package], "harbor.invalid/mirror"), package)
        for key in ("repository", "path", "revision"):
            with self.subTest(key=key), self.assertRaisesRegex(ValueError, "no unique verified package"):
                check.package_for(entry, [{**package, key: package[key] + "-wrong"}], "harbor.invalid/mirror")

    def test_empty_render_requires_helm_success_and_passes_argo_settings(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            source = {"_values_revisions": {"values": "main"},
                      "helm": {"releaseName": "chosen", "valueFiles": ["$values/values.yaml"],
                               "values": "fixture: true", "parameters": [
                                   {"name": "count", "value": "3"},
                                   {"name": "tag", "value": "1", "forceString": True},
                               ]}}
            with patch.object(check.subprocess, "run", return_value=CompletedProcess([], 0, "", "")) as helm:
                self.assertEqual(check.render(source, Path("chart.tgz"), "target", "fallback", root, {}, root), [])
                args, options = helm.call_args
                self.assertEqual(args[0], ["helm", "template", "chosen", "chart.tgz", "--namespace", "target",
                                           "-f", str(root / "values.yaml"), "-f", "-", "--include-crds", "--set", "count=3",
                                           "--set-string", "tag=1"])
                self.assertEqual(options["input"], "fixture: true")
            with patch.object(check.subprocess, "run", return_value=CompletedProcess([], 1, "", "failed")):
                with self.assertRaisesRegex(RuntimeError, "render failed"):
                    check.render(source, Path("chart.tgz"), "target", "fallback", root, {}, root)

    def test_pinned_values_come_from_the_declared_commit(self):
        reference = {"ref": "values", "repoURL": "${local.shared.repo_url}", "targetRevision": "a" * 40}
        defaults = {"repo_url": check.HOMELAB_REPOSITORY + ".git"}
        revisions = check.values_revisions([reference], defaults)
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            source = {"_values_revisions": revisions, "helm": {"valueFiles": ["$values/path/values.yaml"]}}
            with patch.object(check.subprocess, "run", return_value=CompletedProcess([], 0, "", "")) as helm:
                with patch.object(check.subprocess, "check_output", return_value=b"fixture: pinned\n") as git:
                    check.render(source, Path("chart.tgz"), "target", "fallback", root, {}, root)
                path = root / "pinned-values-0.yaml"
                self.assertIn(str(path), helm.call_args.args[0])
                self.assertEqual(path.read_bytes(), b"fixture: pinned\n")
                git.assert_called_once_with(["git", "show", "a" * 40 + ":path/values.yaml"], cwd=root, timeout=15)
        invalid = (
            [{**reference, "repoURL": "https://github.com/foreign/source.git"}],
            [{**reference, "targetRevision": "unreviewed-branch"}],
            [reference, reference],
        )
        for sources in invalid:
            with self.subTest(sources=sources), self.assertRaises(ValueError):
                check.values_revisions(sources, defaults)

    def test_rendered_kustomize_image_is_checked(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            app = root / "clusters/homelab/apps/fixture"
            app.mkdir(parents=True)
            (app / "kustomization.yaml").write_text("apiVersion: kustomize.config.k8s.io/v1beta1\n"
                                                     "kind: Kustomization\nresources: [pod.yaml]\n")
            (app / "pod.yaml").write_text("apiVersion: v1\nkind: Pod\nmetadata:\n  name: fixture\n"
                                           "spec:\n  containers:\n    - name: app\n      image: docker.io/library/busybox:1.37\n")
            images = list(check.kustomize_images(root))
            assert images == [(Path("clusters/homelab/apps/fixture/kustomization.yaml"),
                               "docker.io/library/busybox:1.37")], images
            assert not check.pinned(images[0][1])
            assert check.pinned("harbor.stinkyboi.com/mirror/docker.io/library/busybox@sha256:" + "a" * 64)

    def test_manifest_loader_accepts_helm_relabel_separator_and_empty_configmap(self):
        document = check.yaml.load("kind: ConfigMap\ndata:\nseparator: =\n",
                                   Loader=check.ManifestLoader)
        self.assertEqual(document["separator"], "=")
        self.assertEqual(list(check.image_slots(document)), [])

    def test_generated_image_slots_are_bound_to_actual_sources(self):
        data = {"helperPod.yaml": """kind: Pod
spec:
  initContainers:
    - name: provision
      image: example.invalid/helper:1
"""}
        expected = {("data", "helperPod.yaml", "spec", "initContainers", "provision", "image"):
                    "example.invalid/helper:1"}
        for name in ("IMAGE", "GO_IMAGE", "SKILLS_INIT_IMAGE"):
            data[f"{name}_REGISTRY"] = "example.invalid"
            data[f"{name}_REPOSITORY"] = name.lower()
            data[f"{name}_TAG"] = "1"
            expected[("data", name)] = f"example.invalid/{name.lower()}:1"
        self.assertEqual(dict(check.image_slots({"kind": "ConfigMap", "data": data})), expected)
        pod = {"kind": "Job", "spec": {"template": {"spec": {"initContainers": [
            {"name": "injected", "image": "example.invalid/unapproved:1"}
        ]}}}}
        self.assertEqual(list(check.images(pod)), ["example.invalid/unapproved:1"])

    def test_upstream_exceptions_bind_workload_container_and_digest(self):
        digest = "a" * 64
        manifest = {"kind": "DaemonSet", "metadata": {"name": "ztunnel", "namespace": "istio-system"}}
        slot = ("spec", "template", "spec", "containers", "ztunnel", "image")
        reference = f"docker.io/istio/ztunnel@sha256:{digest}"
        approved = check.image_record("istio/stack.hcl", "ztunnel", "", manifest, slot, reference)
        self.assertEqual(check.image_policy_errors([approved], [approved]), [])
        for index, invalid in (
            (0, "unrelated/stack.hcl"),
            (2, "default"),
            (4, "other-daemon"),
            (5, slot[:-2] + ("other-container", "image")),
            (6, reference[:-1] + "b"),
        ):
            changed = approved[:index] + (invalid,) + approved[index + 1:]
            with self.subTest(index=index):
                self.assertTrue(check.image_policy_errors([changed], [approved])[0].startswith("Unreviewed"))
        self.assertTrue(check.image_policy_errors([], [approved])[0].startswith("Unused"))
        with self.assertRaisesRegex(ValueError, "duplicate"):
            check.image_policy_errors([approved], [approved, approved])

    def test_harbor_digest_must_be_exact(self):
        image = "harbor.stinkyboi.com/mirror/docker.io/library/busybox@sha256:"
        self.assertTrue(check.pinned(image + "a" * 64))
        self.assertFalse(check.pinned(image + "a" * 63))
        self.assertFalse(check.pinned(image + "a" * 64 + "-invalid"))
        self.assertFalse(check.pinned(image.replace("harbor.stinkyboi.com/", "harbor.stinkyboi.com.other/") + "a" * 64))


if __name__ == "__main__":
    unittest.main()
