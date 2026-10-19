#!/usr/bin/env python3
"""Run Cordium CI against fake commands to verify direct TLS and cleanup behavior."""
import json
import os
from pathlib import Path
import subprocess
import sys
import tempfile
import time
import unittest

ROOT = Path(__file__).resolve().parents[2]


class Transport(unittest.TestCase):
    def exercise(self, mode="checks", *, ready=True, remote_status=0, logout_status=0):
        with tempfile.TemporaryDirectory() as temporary:
            directory = Path(temporary)
            binary = directory / "bin"
            binary.mkdir()
            runner = directory / "runner"
            runner.mkdir()
            log = directory / "calls.jsonl"
            dispatcher = binary / "fake"
            dispatcher.write_text(f"#!{sys.executable}\n" + '''
import json, os, pathlib, sys
name, args = pathlib.Path(sys.argv[0]).name, sys.argv[1:]
with open(os.environ["CALL_LOG"], "a") as output:
    output.write(json.dumps([name, *args]) + "\\n")
if name == "uname":
    print("Linux")
elif name == "curl":
    assert "--http2" in args and "--insecure" not in args and "-k" not in args
    assert args[-1] == "https://octelium-api.stinkyboi.com/octelium.api.main.user.v1.MainService/GetStatus"
    pathlib.Path(args[args.index("-D") + 1]).write_text("grpc-status: 16\\n")
    print("200 2" if os.environ["READY"] == "true" else "502 1.1", end="")
elif name == "python3":
    assert args[0] == "-I"
    if "scripts/cordium-check.py" in args:
        sys.exit(int(os.environ["REMOTE_STATUS"]))
elif name == "timeout":
    os.execvp(args[1], args[1:])
elif name == "octelium" and "logout" in args:
    sys.exit(int(os.environ["LOGOUT_STATUS"]))
elif name not in ("sleep", "octelium"):
    raise RuntimeError("Unexpected transport command: " + name)
''')
            dispatcher.chmod(0o700)
            for name in ("uname", "curl", "python3", "timeout", "octelium", "sleep", "cloudflared", "sudo"):
                (binary / name).symlink_to(dispatcher)
            result = subprocess.run(["bash", "scripts/ci/cordium-ci.sh", str(int(time.time()) + 3600), mode],
                                    cwd=ROOT, capture_output=True, text=True, timeout=10,
                                    env={**os.environ, "PATH": str(binary) + os.pathsep + os.environ["PATH"],
                                         "GITHUB_ACTIONS": "true", "GITHUB_SHA": "a" * 40,
                                         "RUNNER_TEMP": str(runner), "CALL_LOG": str(log),
                                         "READY": str(ready).lower(), "REMOTE_STATUS": str(remote_status),
                                         "LOGOUT_STATUS": str(logout_status)})
            calls = [json.loads(line) for line in log.read_text().splitlines()]
            self.assertEqual(list(runner.iterdir()), [], "Private transport scratch data was not removed")
            self.assertFalse(any(call[0] in ("cloudflared", "sudo") for call in calls))
            return result, calls

    def test_native_grpc_probe_precedes_login_and_logout_follows_execution(self):
        result, calls = self.exercise()
        self.assertEqual(result.returncode, 0, result.stderr)
        login = next(i for i, call in enumerate(calls) if call[0] == "octelium" and "login" in call)
        self.assertLess(next(i for i, call in enumerate(calls) if call[0] == "curl"), login)
        self.assertTrue(any(call[0] == "python3" and "scripts/cordium-check.py" in call for call in calls))
        self.assertEqual(calls[-1][0], "octelium")
        self.assertIn("logout", calls[-1])

    def test_transport_failure_prevents_login_and_workspace(self):
        result, calls = self.exercise(ready=False)
        self.assertNotEqual(result.returncode, 0)
        self.assertIn("Native TLS transport is not ready", result.stderr)
        self.assertFalse(any(call[0] == "octelium" or "scripts/cordium-check.py" in call for call in calls))

    def test_remote_failure_is_preserved_and_logout_failure_is_fatal(self):
        self.assertEqual(self.exercise(remote_status=42)[0].returncode, 42)
        self.assertNotEqual(self.exercise(logout_status=1)[0].returncode, 0)

    def test_denial_modes_never_invoke_workspace_runner(self):
        for mode in ("deny-ref", "deny-workflow", "forbidden-method"):
            result, calls = self.exercise(mode)
            self.assertEqual(result.returncode, 0, result.stderr)
            self.assertFalse(any("scripts/cordium-check.py" in call for call in calls))
            self.assertTrue(any("--homedir" in call and "scripts/cordium-ci-acceptance.py" in call for call in calls))


if __name__ == "__main__":
    unittest.main()
