#!/usr/bin/env python3
"""Exercise the privileged provenance workflow's event gate without API writes."""

import json
import os
import subprocess
import tempfile
import unittest
from pathlib import Path


ROOT = Path(__file__).resolve().parents[2]
WORKFLOW = ROOT / ".github/workflows/harbor-native-chainguard-receipt-provenance.yml"
HEAD = "a" * 40
STALE = "b" * 40
REPOSITORY = "Stuhlmuller/homelab"


class WorkflowRunEventTest(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        run = subprocess.check_output(
            ["yq", "-r", ".jobs.verify.steps[1].run", str(WORKFLOW)], text=True
        )
        start = 'if [[ "$GITHUB_EVENT_NAME" == workflow_run ]]; then'
        end = 'printf \'%s\\n\' "$event_head" >"$heads_file"'
        assert run.count(start) == run.count(end) == 1
        cls.gate = start + run.split(start, 1)[1].split(end, 1)[0] + end + "\nfi\n"

    def check_event(self, *, repository=REPOSITORY, workflow="Terragrunt Plan",
                    event="pull_request", head=HEAD, open_head=HEAD):
        payload = {"action": "completed", "repository": {"full_name": repository},
                   "workflow_run": {"name": workflow, "event": event, "head_sha": head}}
        with tempfile.TemporaryDirectory() as temp:
            folder = Path(temp)
            (folder / "event.json").write_text(json.dumps(payload))
            (folder / "all-heads").write_text(open_head + "\n")
            (folder / "heads").write_text("")
            env = {**os.environ, "GITHUB_EVENT_NAME": "workflow_run",
                   "GITHUB_EVENT_PATH": str(folder / "event.json"),
                   "GITHUB_REPOSITORY": REPOSITORY}
            script = 'set -euo pipefail\nall_heads_file="$1"\nheads_file="$2"\n' + self.gate
            result = subprocess.run(
                ["bash", "-c", script, "--", str(folder / "all-heads"), str(folder / "heads")],
                env=env, capture_output=True, text=True, check=False,
            )
            return result.returncode, (folder / "heads").read_text()

    def test_current_open_pr_head_is_selected(self):
        self.assertEqual(self.check_event(), (0, HEAD + "\n"))

    def test_spoofed_event_metadata_is_rejected(self):
        for change in ({"repository": "other/repository"}, {"workflow": "Other Workflow"},
                       {"event": "push"}, {"head": "invalid"}):
            with self.subTest(change=change):
                status, selected = self.check_event(**change)
                self.assertNotEqual(status, 0)
                self.assertEqual(selected, "")

    def test_stale_pr_head_is_not_selected(self):
        self.assertEqual(self.check_event(open_head=STALE), (0, ""))


if __name__ == "__main__":
    unittest.main()
