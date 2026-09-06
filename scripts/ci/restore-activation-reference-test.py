#!/usr/bin/env python3
"""Offline release-reference checks with real Kustomize/Terragrunt rendering; no API access."""
from copy import deepcopy
import importlib.util
import io
import json
import os
from pathlib import Path
import shutil
import subprocess
import sys
import tempfile
import unittest
from unittest.mock import MagicMock, patch


def load(name, path):
    spec = importlib.util.spec_from_file_location(name, path)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


M = load("reference", Path(__file__).with_name("restore-activation-reference.py"))
SOURCE_TESTS = load("source_tests", Path(__file__).with_name("restore-talos-synthetic-test.py"))
ROOT = M.ROOT
TEMPLATE = Path("IaC/.catalog/units/live/argocd-octelium-restore/terragrunt.hcl.template")
PIN = {"image": "registry.example/restore@sha256:" + "a" * 64}
HEAD = "b" * 40


def run(tool, *arguments, **kwargs):
    executable = shutil.which(tool)
    if executable is None:
        raise RuntimeError(f"Missing {tool}; run these tests in the repository-locked development shell")
    return subprocess.run([executable, *arguments], capture_output=True, text=True, timeout=60, **kwargs)


def checked(tool, *arguments, **kwargs):
    result = run(tool, *arguments, **kwargs)
    if result.returncode:
        raise AssertionError(f"{tool} failed: {result.stderr[-2000:]}")
    return result.stdout


def objects(directory):
    rendered = checked("kustomize", "build", str(directory))
    return json.loads(checked("yq", "ea", "-o=json", "[.]", "-", input=rendered))


class Tests(unittest.TestCase):
    def temporary(self):
        directory = tempfile.TemporaryDirectory(prefix="restore-reference-test-")
        self.addCleanup(directory.cleanup)
        return Path(directory.name)

    def copied_candidate(self):
        target = self.temporary() / "candidate"
        shutil.copytree(ROOT / M.CANDIDATE, target)
        return target

    def apply_reference(self, target):
        source = M.application(PIN)["spec"]["sources"][0]
        checked("kustomize", "edit", "set", "image", *source["kustomize"]["images"], cwd=target)
        # Argo appends inline patches to the source Kustomization before build.
        value = json.loads(checked("yq", "-o=json", ".", str(target / "kustomization.yaml")))
        value["patches"] = value.get("patches", []) + source["kustomize"]["patches"]
        (target / "kustomization.yaml").write_text(json.dumps(value))

    def catalog_fixture(self, *, instantiate=False, pin=False):
        root = self.temporary()
        (root / "flake.nix").write_text("{}\n")
        (root / "IaC").mkdir()
        # Real shared includes, but render never initializes their providers/backends.
        for path in ("IaC/root.hcl", "IaC/kubernetes-provider.hcl"):
            shutil.copyfile(ROOT / path, root / path)
        dependency = root / "IaC/live/argocd-apps/octelium-storage"
        dependency.mkdir(parents=True)
        (dependency / "terragrunt.hcl").write_text("inputs = {}\n")
        template = root / TEMPLATE
        template.parent.mkdir(parents=True)
        shutil.copyfile(ROOT / TEMPLATE, template)
        script = root / "scripts/ci/restore-activation-reference.py"
        script.parent.mkdir(parents=True)
        shutil.copyfile(Path(M.__file__), script)
        if pin:
            target = root / M.PIN.relative_to(ROOT)
            target.parent.mkdir(parents=True)
            target.write_text(json.dumps(PIN))
            # Only the verified source/pin result is a seam in this CLI wiring test.
            # The constructor bytes, template, include resolution and Terragrunt
            # subprocess are real. Strict source binding is exercised below with
            # real Git trees/blobs, avoiding unsigned fixture commits.
            (script.parent / "restore-talos-synthetic.py").write_text(
                "import json\nfrom pathlib import Path\n"
                "def run(*args):\n"
                "    assert args == ('git', 'rev-parse', 'HEAD')\n"
                f"    return {HEAD!r} + '\\n'\n"
                "def contract(head):\n"
                f"    assert head == {HEAD!r}\n"
                "    root = Path(__file__).resolve().parents[2]\n"
                "    return json.loads((root / 'images/postgres-restore-egress/published-image.json').read_bytes()), None\n")
        unit = root / "IaC/live/argocd-apps/octelium-postgres-restore-drill"
        if instantiate:
            unit.mkdir()
            shutil.copyfile(template, unit / "terragrunt.hcl")
        return root, unit, script

    def test_absent_and_symlink_pin_precede_imports_and_commands(self):
        root = self.temporary()
        target = root / "pin.json"
        for symlink in (False, True):
            with self.subTest(symlink=symlink):
                if symlink:
                    real = root / "real.json"
                    real.write_text(json.dumps(PIN))
                    target.symlink_to(real)
                with patch.object(M, "PIN", target), patch.object(M.importlib.util, "spec_from_file_location") as imported:
                    with self.assertRaisesRegex(RuntimeError, "pin is absent"):
                        M.verified_pin()
                    imported.assert_not_called()

    def test_verified_pin_uses_exact_head_and_propagates_strict_rejection(self):
        target = self.temporary() / "pin.json"
        target.write_text(json.dumps(PIN))
        source = MagicMock()
        source.run.return_value = HEAD + "\n"
        source.contract.return_value = (PIN, object())
        with patch.object(M, "PIN", target), patch.object(M.importlib.util, "spec_from_file_location"), \
                patch.object(M.importlib.util, "module_from_spec", return_value=source):
            self.assertEqual(M.verified_pin(), PIN)
            source.run.assert_called_once_with("git", "rev-parse", "HEAD")
            source.contract.assert_called_once_with(HEAD)
            source.contract.side_effect = RuntimeError("Published source inventory differs")
            with self.assertRaisesRegex(RuntimeError, "source inventory"):
                M.verified_pin()

    def test_no_cli_overrides_or_partial_output_on_rejection(self):
        for arguments in (["reference", "--image", PIN["image"]], ["reference", "--unsuspend"]):
            with self.subTest(arguments=arguments), patch.object(sys, "argv", arguments), \
                    patch.object(M, "verified_pin") as verifier, patch.object(sys, "stdout", new_callable=io.StringIO) as output:
                with self.assertRaisesRegex(RuntimeError, "no arguments"):
                    M.main()
                verifier.assert_not_called()
                self.assertEqual(output.getvalue(), "")
        with patch.object(sys, "argv", ["reference"]), \
                patch.object(M, "verified_pin", side_effect=RuntimeError("dirty source")), \
                patch.object(sys, "stdout", new_callable=io.StringIO) as output:
            with self.assertRaisesRegex(RuntimeError, "dirty source"):
                M.main()
            self.assertEqual(output.getvalue(), "")

    def test_reference_is_dedicated_main_and_environment_independent(self):
        expected = M.application(PIN)
        with patch.dict(os.environ, {"RESTORE_IMAGE": "unreviewed:latest", "RESTORE_SUSPEND": "false"}):
            self.assertEqual(M.application(PIN), expected)
        self.assertEqual(expected["metadata"]["name"], "octelium-postgres-restore-drill")
        self.assertEqual(expected["spec"]["project"], "homelab")
        self.assertEqual(expected["spec"]["destination"]["namespace"], "octelium-storage")
        source, = expected["spec"]["sources"]
        self.assertEqual((source["repoURL"], source["targetRevision"], source["path"]),
                         ("https://github.com/Stuhlmuller/homelab.git", "main", M.CANDIDATE))
        self.assertEqual(source["kustomize"]["images"], ["postgres=" + PIN["image"]])
        self.assertNotIn("source", expected["spec"])
        self.assertIs(type(expected["spec"]["syncPolicy"]["retry"]["limit"]), int)
        self.assertIs(type(expected["spec"]["syncPolicy"]["retry"]["backoff"]["factor"]), int)

    def test_real_kustomize_changes_only_image_and_launcher_and_keeps_suspended(self):
        original = objects(ROOT / M.CANDIDATE)
        target = self.copied_candidate()
        self.apply_reference(target)
        actual = objects(target)
        expected = deepcopy(original)
        job = next(obj for obj in expected if obj["kind"] == "CronJob")
        container, = job["spec"]["jobTemplate"]["spec"]["template"]["spec"]["containers"]
        self.assertEqual(container["image"].split(":")[0], "postgres")
        container["image"] = PIN["image"]
        container["command"] = [M.LAUNCHER, "/bin/sh", "/scripts/restore-drill.sh", "/backup/logical-backups", "/work"]
        self.assertEqual(actual, expected)
        self.assertIs(job["spec"]["suspend"], True)
        self.assertEqual(len(actual), 3)
        self.assertEqual({obj["kind"] for obj in actual}, {"ConfigMap", "CronJob", "NetworkPolicy"})
        self.assertEqual(objects(ROOT / M.CANDIDATE), original)
        self.assertFalse(any(obj["metadata"]["name"].startswith(M.NAME)
                             for obj in objects((ROOT / M.CANDIDATE).parent)))

    def test_real_patch_rejects_changed_container_or_unsuspended_base(self):
        for path, value in ((".spec.suspend", "false"),
                            (".spec.jobTemplate.spec.template.spec.containers[0].name", '"other"')):
            with self.subTest(path=path):
                target = self.copied_candidate()
                file = target / "restore-drill-cronjob.yaml"
                changed = checked("yq", f'(select(.kind == "CronJob") | {path}) = {value}', str(file))
                file.write_text(changed)
                self.apply_reference(target)
                result = run("kustomize", "build", str(target))
                self.assertNotEqual(result.returncode, 0)
                self.assertIn("test failed", result.stderr)

    def test_new_constructor_and_test_are_bound_by_real_git_inventory(self):
        helper = SOURCE_TESTS.Tests()
        self.addCleanup(helper.doCleanups)
        root = helper.source_repository()
        paths = ["scripts/ci/restore-activation-reference.py", "scripts/ci/restore-activation-reference-test.py"]
        files = {path: ("100644", (ROOT / path).read_bytes()) for path in paths}
        original = helper.source_tree(root, files)
        helper.source_working_files(root, files)
        helper.source_contract(root, original, original)
        for path in paths:
            with self.subTest(path=path):
                changed = {**files, path: ("100644", files[path][1] + b"# changed dependency\n")}
                current = helper.source_tree(root, changed)
                helper.source_working_files(root, changed)
                with self.assertRaisesRegex(RuntimeError, "source inventory"):
                    helper.source_contract(root, original, current)

    def test_dormant_template_keeps_normal_hcl_validation_pin_independent(self):
        root, _, _ = self.catalog_fixture()
        checked("terragrunt", "hcl", "validate", "--no-color", cwd=root)
        # Check this dormant fixture, not the repository's future release state:
        # registration must not require changing these publication-bound tests.
        self.assertFalse((root / TEMPLATE).with_suffix("").exists())

    def test_later_release_iac_keeps_publication_source_unchanged(self):
        helper = SOURCE_TESTS.Tests()
        self.addCleanup(helper.doCleanups)
        root = helper.source_repository()
        files = {path: ("100644", (ROOT / path).read_bytes()) for path in (
            "scripts/ci/restore-activation-reference.py", "scripts/ci/restore-activation-reference-test.py")}
        original = helper.source_tree(root, files)
        released = {**files,
                    "IaC/.catalog/units/live/argocd-octelium-restore/terragrunt.hcl": (
                        "100644", (ROOT / TEMPLATE).read_bytes()),
                    "IaC/terragrunt.stack.hcl": ("100644", b'# synthetic reviewed release registration\n')}
        current = helper.source_tree(root, released)
        helper.source_working_files(root, released)
        # Real Git inventory permits release-only additions; no bound test or
        # candidate edit is needed to preserve the published source contract.
        helper.source_contract(root, original, current)

    def test_instantiated_template_rejects_absent_pin_without_source_commands(self):
        _, unit, script = self.catalog_fixture(instantiate=True)
        result = run("terragrunt", "render", "--json", "--write=false", "--no-color", cwd=unit)
        self.assertNotEqual(result.returncode, 0)
        self.assertIn("pin is absent", result.stderr)
        self.assertNotIn("restore-talos-synthetic.py", result.stderr)
        # Direct execution with no PATH proves the missing-pin check needs no Git
        # or external command, even when invoked outside the script's repository.
        direct = subprocess.run([sys.executable, str(script)], cwd=unit, env={"PATH": ""},
                                capture_output=True, text=True, timeout=30)
        self.assertNotEqual(direct.returncode, 0)
        self.assertIn("pin is absent", direct.stderr)
        self.assertEqual(direct.stdout, "")

    def test_real_terragrunt_render_resolves_generated_unit_and_constructor(self):
        root, unit, _ = self.catalog_fixture(instantiate=True, pin=True)
        checked("terragrunt", "hcl", "fmt", "--check", cwd=unit)
        rendered = json.loads(checked("terragrunt", "render", "--json", "--write=false", "--no-color", cwd=unit))
        self.assertEqual(rendered["inputs"]["manifest"], M.application(PIN))
        self.assertEqual(rendered["terraform"]["source"], "../../../modules/argocd-application-kubernetes")
        self.assertIn("../octelium-storage", rendered["dependencies"]["paths"])
        self.assertFalse((unit / "kubernetes-provider.tf").exists())
        self.assertFalse((unit / "terragrunt.rendered.json").exists())
        self.assertNotEqual(root, ROOT)


if __name__ == "__main__":
    unittest.main()
