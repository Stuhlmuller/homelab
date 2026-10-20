#!/usr/bin/env python3
"""Fixed full-sync contract; fake CLIs prevent a local cluster mutation."""

import json
import hashlib
import os
from pathlib import Path
import re
import subprocess
import tempfile
import unittest


ROOT = Path(__file__).resolve().parents[2]
SCRIPT = ROOT / "scripts/ci/openclaw-enterprise-full-sync.sh"
SHA = "a" * 40
UPSTREAM = "33bb74590a749f37934da4502fca6035cd234a55"
REPO = "https://github.com/Stuhlmuller/homelab.git"


class FullSync(unittest.TestCase):
    def test_workflow_pins_reviewed_script(self):
        workflow = (ROOT / ".github/workflows/openclaw-enterprise-operations.yml").read_text()
        hashes = re.findall(
            r"sha256sum --check --status <<<'([0-9a-f]{64})  scripts/ci/openclaw-enterprise-full-sync\.sh'",
            workflow,
        )
        self.assertEqual(hashes, [hashlib.sha256(SCRIPT.read_bytes()).hexdigest()])

    def run_stage(self, *, phase="lifecycle-validation", ref="refs/heads/main",
                  upstream=UPSTREAM, enterprise_enabled=False, foundation_path=None,
                  enterprise_path=None):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            (root / "scripts/config").mkdir(parents=True)
            config = json.loads((ROOT / "scripts/config/openclaw-enterprise.json").read_text())
            config["installationPhase"] = phase
            (root / "scripts/config/openclaw-enterprise.json").write_text(json.dumps(config))
            (root / "bin").mkdir()
            calls = root / "calls"
            fixture = root / "fixture.py"
            fixture.write_text('''#!/usr/bin/env python3
import json, os, sys
from pathlib import Path
name = Path(sys.argv[0]).name
args = sys.argv[1:]
with open(os.environ["CALLS"], "a") as output:
    output.write(json.dumps([name, *args]) + "\\n")
if name in ("git", "gh"):
    print(os.environ["EXPECTED_SHA"])
elif name == "kubectl":
    app = args[args.index("application") + 1]
    history = [json.loads(line) for line in Path(os.environ["CALLS"]).read_text().splitlines()]
    synced = any(call[:4] == ["argocd", "app", "sync", app] for call in history)
    status = ({"operationState": {"phase": "Succeeded"},
               "sync": {"revisions": ([os.environ["EXPECTED_SHA"]] if app.endswith("foundation") else
                                     [os.environ["UPSTREAM"], os.environ["EXPECTED_SHA"],
                                      os.environ["EXPECTED_SHA"]])},
               "health": {"status": "Healthy"}} if synced else {})
    if app == "openclaw-enterprise-foundation":
        print(json.dumps({"metadata": {"name": app}, "status": status, "spec": {
            "project": "openclaw-enterprise", "destination": {"namespace": "openclaw-system"},
            "sources": [{"repoURL": os.environ["REPO"],
                         "path": os.environ["FOUNDATION_PATH"], "targetRevision": "main"}],
            "syncPolicy": {"automated": {"enabled": False, "prune": False, "selfHeal": False}}}}))
    else:
        print(json.dumps({"metadata": {"name": app}, "status": status, "spec": {
            "project": "openclaw-enterprise", "destination": {"namespace": "openclaw-system"},
            "sources": [
                {"repoURL": "https://github.com/openclaw/openclaw-enterprise.git",
                 "path": "deploy/helm/openclaw-enterprise", "targetRevision": os.environ["UPSTREAM"],
                 "helm": {"releaseName": "oce", "valueFiles": ["$values/clusters/homelab/apps/openclaw-enterprise/values.yaml"]}},
                {"repoURL": os.environ["REPO"], "path": ".", "targetRevision": "main",
                 "ref": "values", "directory": {"include": ".argocd-values-ref-placeholder.yaml"}},
                {"repoURL": os.environ["REPO"], "path": os.environ["ENTERPRISE_PATH"],
                 "targetRevision": "main"}],
            "syncPolicy": {"automated": {"enabled": os.environ["ENTERPRISE_ENABLED"] == "true",
                                           "prune": False, "selfHeal": False}}}}))
''')
            fixture.chmod(0o755)
            for name in ("git", "gh", "kubectl", "argocd"):
                (root / "bin" / name).symlink_to(fixture)
            result = subprocess.run(
                ["bash", str(SCRIPT)], cwd=root, capture_output=True, text=True,
                env={**os.environ, "PATH": str(root / "bin") + os.pathsep + os.environ["PATH"],
                     "GITHUB_ACTIONS": "true", "GITHUB_REF": ref, "GITHUB_SHA": SHA,
                     "EXPECTED_SHA": SHA, "GH_REPO": "Stuhlmuller/homelab", "CALLS": str(calls),
                     "REPO": REPO, "UPSTREAM": upstream,
                     "FOUNDATION_PATH": foundation_path or "clusters/homelab/apps/openclaw-enterprise-foundation",
                     "ENTERPRISE_PATH": enterprise_path or "clusters/homelab/apps/openclaw-enterprise",
                     "ENTERPRISE_ENABLED": str(enterprise_enabled).lower()}, check=False,
            )
            return result, [json.loads(line) for line in calls.read_text().splitlines()] if calls.exists() else []

    def test_exact_source_full_sync_and_dependency_order(self):
        result, calls = self.run_stage()
        self.assertEqual(result.returncode, 0, result.stderr)
        commands = [call for call in calls if call[0] == "argocd"]
        self.assertEqual([(call[1:3]) for call in commands], [
            ["app", "wait"], ["app", "sync"], ["app", "wait"],
            ["app", "sync"], ["app", "wait"],
        ])
        self.assertIn("--revisions", commands[1])
        self.assertIn("--source-positions", commands[1])
        self.assertIn(SHA, commands[1])
        self.assertEqual(commands[3].count("--revisions"), 3)
        self.assertEqual(commands[3].count(SHA), 2)
        self.assertEqual(commands[3].count(UPSTREAM), 1)
        self.assertFalse(any(flag in call for call in commands for flag in
                             ("--force", "--prune", "--resource", "--apply-out-of-sync-only", "--async")))

    def test_incomplete_or_drifted_inputs_block_before_sync(self):
        for options in ({"phase": "unselected"}, {"ref": "refs/heads/feature"},
                        {"upstream": "b" * 40}, {"enterprise_enabled": True},
                        {"foundation_path": "clusters/homelab/apps/openclaw"},
                        {"enterprise_path": "clusters/homelab/apps/openclaw"}):
            with self.subTest(options=options):
                result, calls = self.run_stage(**options)
                self.assertNotEqual(result.returncode, 0)
                self.assertFalse(any(call[0] == "argocd" for call in calls))


if __name__ == "__main__":
    unittest.main()
