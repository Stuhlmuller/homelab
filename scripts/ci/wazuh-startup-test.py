#!/usr/bin/env python3
"""Exercise the real Wazuh startup script with isolated command failures.

No container runtime or live cluster required. Only paths and external binaries
are replaced; the checked-in shell control flow runs unchanged under Bash.
"""

import json
import os
import shutil
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path

REPO = Path(__file__).resolve().parents[2]
APP = REPO / "clusters/homelab/apps/wazuh"


def executable(path, source):
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(f"#!{sys.executable}\n" + source)
    path.chmod(0o755)


class StartupTests(unittest.TestCase):
    def run_startup(self, failure=None):
        with tempfile.TemporaryDirectory(prefix="wazuh-startup-") as temporary:
            root = Path(temporary)
            for directory in (
                "run/wazuh/credentials", "run/wazuh/config", "etc/filebeat",
                "var/ossec/api/configuration", "var/ossec/etc", "bin",
            ):
                (root / directory).mkdir(parents=True)
            inputs = {
                "run/wazuh/credentials/filebeat.yml": "filebeat.modules: []\n",
                "run/wazuh/config/api.yaml": "https: {enabled: true}\n",
                "run/wazuh/credentials/agent-enrollment-password": "test",
                "run/wazuh/credentials/indexer-admin-password": "test",
                "run/wazuh/credentials/api-admin.json": json.dumps({
                    "username": "wazuh-wui", "password": "test"
                }),
                "etc/filebeat/wazuh-template.json": (
                    "invalid JSON" if failure == "template" else '{"settings": {}}'
                ),
            }
            for path, content in inputs.items():
                (root / path).write_text(content)
            executable(root / "bin/install", """
import os, shutil, sys
if os.environ.get('WAZUH_TEST_FAIL') == 'install':
    sys.exit(21)
shutil.copyfile(sys.argv[-2], sys.argv[-1])
""")
            executable(root / "var/ossec/framework/python/bin/python3", f"""
import json, os, pathlib, sys
if sys.argv[1].endswith('create_user.py'):
    if os.environ.get('WAZUH_TEST_FAIL') == 'create-user':
        sys.exit(22)
    value = json.loads(pathlib.Path({str(root / 'var/ossec/api/configuration/admin.json')!r}).read_text())
    assert value['username'] == 'wazuh-wui'
    pathlib.Path({str(root / 'api-configured')!r}).touch()
else:
    os.execv({sys.executable!r}, [{sys.executable!r}] + sys.argv[1:])
""")
            for path, phase in (
                ("var/ossec/bin/wazuh-keystore", "keystore"),
                ("var/ossec/bin/wazuh-analysisd", "analysis"),
                ("var/ossec/bin/wazuh-logcollector", "logcollector"),
                ("usr/share/filebeat/bin/filebeat", "filebeat"),
            ):
                executable(root / path, f"""
import os, sys
if os.environ.get('WAZUH_TEST_FAIL') == {phase!r}:
    sys.exit(23)
if {phase!r} == 'keystore':
    sys.stdin.read()
""")
            executable(root / "var/ossec/bin/wazuh-control", f"""
import pathlib, sys
assert sys.argv[1:] == ['start']
assert pathlib.Path({str(root / 'api-configured')!r}).exists()
pathlib.Path({str(root / 'started')!r}).touch()
""")
            source = (APP / "manager-start.sh").read_text()
            for original in ("/var/ossec", "/run/wazuh", "/etc/filebeat", "/usr/share/filebeat"):
                source = source.replace(original, str(root / original.removeprefix("/")))
            script = root / "manager-start.sh"
            script.write_text(source)
            environment = os.environ.copy()
            environment["PATH"] = str(root / "bin") + os.pathsep + environment["PATH"]
            environment["WAZUH_TEST_FAIL"] = failure or ""
            result = subprocess.run(
                [shutil.which("bash"), str(script)], env=environment,
                capture_output=True, text=True, timeout=15, check=False,
            )
            if failure:
                self.assertNotEqual(result.returncode, 0, f"{failure} did not fail")
                self.assertFalse((root / "started").exists(), f"{failure} started Wazuh")
            else:
                self.assertEqual(result.returncode, 0, result.stderr)
                self.assertTrue((root / "started").exists())
                self.assertFalse((root / "var/ossec/api/configuration/admin.json").exists())
                settings = json.loads((root / "etc/filebeat/wazuh-template.json").read_text())["settings"]
                self.assertEqual(settings["index.number_of_shards"], 1)
                self.assertEqual(settings["index.number_of_replicas"], 0)

    def test_success_starts_only_after_configuring_credentials(self):
        self.run_startup()

    def test_each_failure_keeps_all_wazuh_listeners_down(self):
        for phase in ("install", "create-user", "keystore", "analysis", "logcollector", "filebeat", "template"):
            with self.subTest(phase=phase):
                self.run_startup(phase)

    def test_script_replaces_upstream_unchecked_hook_runner(self):
        manifest = (APP / "manager.yaml").read_text()
        self.assertIn("mountPath: /etc/cont-init.d/2-manager", manifest)
        self.assertNotIn("mountPath: /entrypoint-scripts", manifest)


if __name__ == "__main__":
    unittest.main()
