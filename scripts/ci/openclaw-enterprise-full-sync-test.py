#!/usr/bin/env python3
"""Fixed full-sync contract; fake CLIs prevent a local cluster mutation."""

import json
import os
from pathlib import Path
import subprocess
import tempfile
import unittest


ROOT = Path(__file__).resolve().parents[2]
SCRIPT = ROOT / "scripts/ci/openclaw-enterprise-full-sync.sh"
SHA = "a" * 40
UPSTREAM = "33bb74590a749f37934da4502fca6035cd234a55"
REPO = "https://github.com/Stuhlmuller/homelab.git"


class FullSync(unittest.TestCase):
    def test_workflow_runs_only_full_sync_without_a_journal(self):
        workflow = (ROOT / ".github/workflows/openclaw-enterprise-operations.yml").read_text()
        stage = (ROOT / "scripts/ci/openclaw-enterprise-stage.sh").read_text()
        self.assertIn('options: [none, bind-installation, full-sync, reconcile, stop,', workflow)
        self.assertIn('nix develop --command bash scripts/ci/openclaw-enterprise-stage.sh "$RUN_STAGE"', workflow)
        self.assertIn('if [[ "$stage" == full-sync ]]; then', stage)
        self.assertIn('bash scripts/ci/openclaw-enterprise-full-sync.sh', stage)
        self.assertIn('durable private journal runner is not declared', stage)

    def run_stage(self, *, phase="lifecycle-validation", ref="refs/heads/main",
                  upstream=UPSTREAM, enterprise_enabled=False, foundation_path=None,
                  enterprise_path=None, enterprise_sync_exit=0,
                  foundation_sync_options=None, enterprise_sync_options=None,
                  foundation_retry_limit=0, enterprise_retry_limit=0,
                  drift_after_enterprise_sync=False):
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
if name == "gh" and os.environ["DRIFT_AFTER_ENTERPRISE_SYNC"] == "true":
    history = [json.loads(line) for line in Path(os.environ["CALLS"]).read_text().splitlines()]
    if any(call[:4] == ["argocd", "app", "sync", "openclaw-enterprise"]
           for call in history):
        print("b" * 40)
        raise SystemExit(0)
if name in ("git", "gh"):
    print(os.environ["EXPECTED_SHA"])
elif name == "argocd" and args[:3] == ["app", "sync", "openclaw-enterprise"]:
    sys.exit(int(os.environ["ENTERPRISE_SYNC_EXIT"]))
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
            "syncPolicy": {"automated": {"allowEmpty": False, "enabled": False,
                                         "prune": False, "selfHeal": False},
                           "syncOptions": json.loads(os.environ["FOUNDATION_SYNC_OPTIONS"]),
                           "retry": {"limit": int(os.environ["FOUNDATION_RETRY_LIMIT"]),
                                     "backoff": {"duration": "30s", "factor": 2,
                                                 "maxDuration": "2m"}}}}}))
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
            "syncPolicy": {"automated": {"allowEmpty": False,
                                           "enabled": os.environ["ENTERPRISE_ENABLED"] == "true",
                                           "prune": False, "selfHeal": False},
                           "syncOptions": json.loads(os.environ["ENTERPRISE_SYNC_OPTIONS"]),
                           "retry": {"limit": int(os.environ["ENTERPRISE_RETRY_LIMIT"]),
                                     "backoff": {"duration": "30s", "factor": 2,
                                                 "maxDuration": "2m"}}}}}))
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
                     "ENTERPRISE_ENABLED": str(enterprise_enabled).lower(),
                     "ENTERPRISE_SYNC_EXIT": str(enterprise_sync_exit),
                     "DRIFT_AFTER_ENTERPRISE_SYNC": str(drift_after_enterprise_sync).lower(),
                     "FOUNDATION_SYNC_OPTIONS": json.dumps(foundation_sync_options or
                                                              ["CreateNamespace=false", "ServerSideApply=true"]),
                     "ENTERPRISE_SYNC_OPTIONS": json.dumps(enterprise_sync_options or
                                                              ["CreateNamespace=false", "ServerSideApply=true"]),
                     "FOUNDATION_RETRY_LIMIT": str(foundation_retry_limit),
                     "ENTERPRISE_RETRY_LIMIT": str(enterprise_retry_limit)}, check=False,
            )
            return result, [json.loads(line) for line in calls.read_text().splitlines()] if calls.exists() else []

    def test_exact_source_full_sync_and_dependency_order(self):
        result, calls = self.run_stage()
        self.assertEqual(result.returncode, 0, result.stderr)
        commands = [call for call in calls if call[0] == "argocd"]
        self.assertEqual([(call[1:3]) for call in commands], [
            ["app", "wait"], ["app", "wait"], ["app", "sync"], ["app", "wait"],
            ["app", "sync"], ["app", "wait"],
        ])
        self.assertIn("--revisions", commands[2])
        self.assertIn("--source-positions", commands[2])
        self.assertIn(SHA, commands[2])
        self.assertEqual(commands[4].count("--revisions"), 3)
        self.assertEqual(commands[4].count(SHA), 2)
        self.assertEqual(commands[4].count(UPSTREAM), 1)
        self.assertEqual(len([call for call in calls if call[0] == "gh"]), 3)
        self.assertFalse(any(flag in call for call in commands for flag in
                             ("--force", "--prune", "--resource", "--skip-hooks",
                              "--apply-out-of-sync-only", "--async")))

    def test_incomplete_or_drifted_inputs_block_before_sync(self):
        for options in ({"phase": "unselected"}, {"ref": "refs/heads/feature"},
                        {"upstream": "b" * 40}, {"enterprise_enabled": True},
                        {"foundation_path": "clusters/homelab/apps/openclaw"},
                        {"enterprise_path": "clusters/homelab/apps/openclaw"},
                        {"foundation_sync_options": ["ApplyOutOfSyncOnly=true"]},
                        {"enterprise_sync_options": ["ApplyOutOfSyncOnly=true"]},
                        {"foundation_retry_limit": 1}, {"enterprise_retry_limit": 1}):
            with self.subTest(options=options):
                result, calls = self.run_stage(**options)
                self.assertNotEqual(result.returncode, 0)
                self.assertFalse(any(call[0] == "argocd" for call in calls))

    def test_failed_or_cancelled_migration_stops_before_any_resuming_sync(self):
        for exit_code in (1, 130):
            with self.subTest(exit_code=exit_code):
                result, calls = self.run_stage(enterprise_sync_exit=exit_code)
                self.assertEqual(result.returncode, exit_code, result.stderr)
                self.assertEqual([call[1:4] for call in calls if call[0] == "argocd"], [
                    ["app", "wait", "platform-gateway-api-crds"],
                    ["app", "wait", "platform-envoy-gateway"],
                    ["app", "sync", "openclaw-enterprise-foundation"],
                    ["app", "wait", "openclaw-enterprise-foundation"],
                    ["app", "sync", "openclaw-enterprise"],
                ])

    def test_main_advances_during_enterprise_sync_blocks_success(self):
        result, calls = self.run_stage(drift_after_enterprise_sync=True)
        self.assertEqual(result.returncode, 2)
        self.assertTrue(any(call[:4] == ["argocd", "app", "sync", "openclaw-enterprise"]
                            for call in calls))
        self.assertEqual(calls[-1][:2], ["gh", "api"])


if __name__ == "__main__":
    unittest.main()
