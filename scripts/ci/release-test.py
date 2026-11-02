#!/usr/bin/env python3
"""Check release isolation and exercise publication against a disposable Git remote."""

import json
import os
from pathlib import Path
import shutil
import subprocess
import sys
import tempfile
import unittest

ROOT = Path(__file__).resolve().parents[2]
RUNTIME = "--runtime" in sys.argv
if RUNTIME:
    sys.argv.remove("--runtime")


class ReleaseTests(unittest.TestCase):
    def test_locked_packages_and_token_boundary(self):
        manifest = json.loads((ROOT / "package.json").read_text())
        lock = json.loads((ROOT / "package-lock.json").read_text())
        self.assertEqual(lock["packages"][""]["devDependencies"], manifest["devDependencies"])
        for name, package in lock["packages"].items():
            if name and not package.get("inBundle"):
                self.assertTrue(package["resolved"].startswith("https://registry.npmjs.org/"), name)
                self.assertTrue(package["integrity"].startswith("sha512-"), name)
        workflow = json.loads(subprocess.check_output(
            ["yq", "-o=json", ".", str(ROOT / ".github/workflows/release.yml")], text=True,
        ))
        publisher = workflow["jobs"]["release"]
        preview = workflow["jobs"]["release-dry-run"]
        self.assertEqual(publisher["concurrency"], {
            "group": "semantic-release-main", "cancel-in-progress": False,
        })
        self.assertTrue(preview["concurrency"]["cancel-in-progress"])
        self.assertNotEqual(preview["concurrency"]["group"], publisher["concurrency"]["group"])
        self.assertEqual(publisher["steps"][0]["with"]["ref"], "refs/heads/main")
        for job in (preview, publisher):
            self.assertLessEqual(job["timeout-minutes"], 15)
            install = next(s for s in job["steps"] if s["name"] == "Install locked release toolchain")
            self.assertIn("npm ci --ignore-scripts", install["run"])
            self.assertNotIn("env", install)
            self.assertFalse(job["steps"][0]["with"]["persist-credentials"])
        self.assertNotIn("secrets.", json.dumps(preview))
        self.assertEqual(publisher["permissions"], {"contents": "write"})
        self.assertEqual(publisher["steps"][-1]["env"], {"GITHUB_TOKEN": "${{ secrets.GITHUB_TOKEN }}"})

    @unittest.skipUnless(RUNTIME, "install locked dependencies and pass --runtime")
    def test_preview_coalesced_commits_and_repeat_publication(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            checkout, remote = root / "checkout", root / "remote.git"
            env = {k: v for k, v in os.environ.items()
                   if not k.startswith(("GITHUB_", "GIT_CONFIG_")) and k not in ("CI", "GH_TOKEN")}
            env.update(GIT_CONFIG_GLOBAL=os.devnull, GIT_CONFIG_NOSYSTEM="1")

            def run(*args, cwd=checkout):
                result = subprocess.run(args, cwd=cwd, env=env, text=True,
                                        stdout=subprocess.PIPE, stderr=subprocess.STDOUT, check=False)
                self.assertEqual(result.returncode, 0, result.stdout)
                return result.stdout

            run("git", "init", "--bare", "--initial-branch=main", str(remote), cwd=root)
            run("git", "clone", str(remote), str(checkout), cwd=root)
            run("git", "config", "user.name", "Release fixture")
            run("git", "config", "user.email", "fixture@example.invalid")
            shutil.copy(ROOT / ".releaserc.yaml", checkout)
            (checkout / "node_modules").symlink_to(ROOT / "node_modules", target_is_directory=True)
            run("git", "add", ".releaserc.yaml")
            run("git", "commit", "-m", "feat: initial fixture")
            run("git", "tag", "v1.0.0")
            run("git", "push", "--tags", "origin", "main")
            for message in ("fix: first pending push", "feat: newest pending push"):
                run("git", "commit", "--allow-empty", "-m", message)
            run("git", "push", "origin", "main")
            command = (str(ROOT / "node_modules/.bin/semantic-release"), "--no-ci",
                       "--repository-url", remote.as_uri())
            self.assertIn("1.1.0", run(*command, "--dry-run"))
            self.assertNotIn("v1.1.0", run("git", "tag", "--list"))
            run(*command)
            tip = run("git", "rev-parse", "HEAD").strip()
            self.assertEqual(run("git", "rev-parse", "v1.1.0").strip(), tip)
            self.assertIn(tip, run("git", "ls-remote", "--tags", "origin", "v1.1.0"))
            tags = run("git", "ls-remote", "--tags", "origin")
            run(*command)
            self.assertEqual(run("git", "ls-remote", "--tags", "origin"), tags)


if __name__ == "__main__":
    unittest.main()
