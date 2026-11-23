"""Exercise runtime scope against committed changes, including deletions."""

import os
from pathlib import Path
import subprocess
import tempfile
import unittest


SCOPE = Path(__file__).resolve().with_name("validate-runtime-scope.sh")


class RuntimeScopeTest(unittest.TestCase):
    def test_scope_reports_only_affected_runtime_checks(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)

            def git(*args):
                return subprocess.check_output(["git", *args], cwd=root, text=True).strip()

            def write(path):
                entry = root / path
                entry.parent.mkdir(parents=True, exist_ok=True)
                entry.write_text("test\n")
                return entry

            def commit():
                git("add", "-A")
                git("-c", "user.name=Fixture", "-c", "user.email=fixture@example.invalid",
                    "-c", "commit.gpgsign=false", "commit", "-qm", "fixture")
                return git("rev-parse", "HEAD")

            def scope(base_sha):
                output = root / "output"
                output.unlink(missing_ok=True)
                result = subprocess.run(
                    ["bash", str(SCOPE), base_sha], cwd=root, capture_output=True,
                    env={**os.environ, "GITHUB_OUTPUT": str(output)}, check=False,
                )
                if result.returncode:
                    self.assertFalse(output.exists())
                    return None
                return dict(line.split("=") for line in output.read_text().splitlines())

            git("init", "-q")
            write(".gitignore").write_text("/output\n")
            image = write("clusters/homelab/platform/image-policy/policy.yaml")
            base = commit()
            write("docs/guide\nwith-newline.md")
            docs = commit()
            self.assertEqual(scope(base), {
                "image-policy": "false", "network-policy": "false", "harbor-core": "false",
            })

            image.rename(root / "docs/former-policy.yaml")
            write("scripts/ci/fixtures/network-policy-enforcer.yaml")
            runtime = commit()
            self.assertEqual(scope(docs), {
                "image-policy": "true", "network-policy": "true", "harbor-core": "false",
            })

            write("builds/harbor-core/Dockerfile")
            harbor = commit()
            self.assertEqual(scope(runtime), {
                "image-policy": "false", "network-policy": "false", "harbor-core": "true",
            })

            write("flake.lock")
            commit()
            self.assertEqual(scope(harbor), {
                "image-policy": "true", "network-policy": "true", "harbor-core": "true",
            })
            self.assertIsNone(scope("1" * 40))


if __name__ == "__main__":
    unittest.main()
