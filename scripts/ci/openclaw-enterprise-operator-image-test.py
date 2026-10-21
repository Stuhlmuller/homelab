#!/usr/bin/env python3
"""Check the source-bound, non-root journal operator image build offline."""

import importlib.util
import os
from pathlib import Path
import shutil
import subprocess
import tempfile
import unittest
from unittest import mock


ROOT = Path(__file__).resolve().parents[2]
SHA = "a" * 40
SOURCE = ROOT / "scripts/openclaw-enterprise.py"
spec = importlib.util.spec_from_file_location("oce_source", SOURCE)
source = importlib.util.module_from_spec(spec)
spec.loader.exec_module(source)


class OperatorImageBuild(unittest.TestCase):
    def setUp(self):
        self.temporary = tempfile.TemporaryDirectory(prefix="oce-operator-image-")
        self.addCleanup(self.temporary.cleanup)
        self.root = Path(self.temporary.name)
        for path in ("builds/openclaw-enterprise", "scripts", "bin",
                     "clusters/homelab/apps/openclaw-enterprise"):
            (self.root / path).mkdir(parents=True)
        for path in ("builds/openclaw-enterprise/build-operator.sh",
                     "builds/openclaw-enterprise/operator.Dockerfile",
                     "scripts/openclaw-enterprise.py",
                     "clusters/homelab/apps/openclaw-enterprise/installation.yaml",
                     "clusters/homelab/apps/openclaw-enterprise/values.yaml"):
            shutil.copyfile(ROOT / path, self.root / path)
        self.calls = self.root / "docker-calls"
        self.context = self.root / "context-record"
        self.executable("git", f'''case "$1" in
  rev-parse) printf '%s\\n' {SHA} ;;
  status) [[ "${{FIXTURE_DIRTY:-}}" != true ]] || printf ' M scripts/openclaw-enterprise.py\\n' ;;
  *) exit 97 ;;
esac
''')
        self.executable("uname", '''case "$1" in
  -s) printf 'Linux\\n' ;;
  -m) printf 'x86_64\\n' ;;
  *) exit 97 ;;
esac
''')
        self.executable("kubectl", "printf 'fixture kubectl\\n'\n")
        self.executable("yq", "printf 'fixture yq\\n'\n")
        self.executable("docker", '''printf '%s\\n' "$*" >>"$DOCKER_CALLS"
if [[ "$1 $2" == 'buildx build' ]]; then
  context="${@: -1}"
  sha256sum "$context/scripts/openclaw-enterprise.py" >"$CONTEXT_RECORD"
  cat "$context/operator-source.sha" >>"$CONTEXT_RECORD"
  test -s "$context/clusters/homelab/apps/openclaw-enterprise/installation.yaml"
  test -s "$context/clusters/homelab/apps/openclaw-enterprise/values.yaml"
elif [[ "$1 $2" == 'image inspect' ]]; then
  printf '%s\\n' "${FIXTURE_LABEL_SHA:-$FIXTURE_SHA}"
elif [[ "$1" == run && "$*" == *'--entrypoint cat'* ]]; then
  printf '%s\\n' "$FIXTURE_SHA"
fi
''')

    def executable(self, name, body):
        path = self.root / "bin" / name
        path.write_text("#!/usr/bin/env bash\nset -euo pipefail\n" + body)
        path.chmod(0o700)

    def build(self, **extra):
        return subprocess.run(
            ["bash", str(self.root / "builds/openclaw-enterprise/build-operator.sh")],
            cwd=self.root,
            env={**os.environ, "PATH": f"{self.root / 'bin'}:{os.environ['PATH']}",
                 "TMPDIR": str(self.root), "DOCKER_CALLS": str(self.calls),
                 "CONTEXT_RECORD": str(self.context), "FIXTURE_SHA": SHA, **extra},
            capture_output=True, text=True, timeout=20, check=False,
        )

    def test_clean_source_builds_one_nonroot_image_with_complete_inputs(self):
        result = self.build()
        self.assertEqual(result.returncode, 0, result.stderr)
        calls = self.calls.read_text().splitlines()
        self.assertEqual(len([call for call in calls if call.startswith("buildx build ")]), 1)
        self.assertIn("--platform linux/amd64", calls[0])
        self.assertIn("org.opencontainers.image.revision=" + SHA, calls[0])
        self.assertIn("homelab-oce-operator:build", calls[0])
        self.assertTrue(any("--network none --read-only --user 10001:10001" in call
                            and "--help" in call for call in calls))
        self.assertTrue(any("--entrypoint kubectl" in call for call in calls))
        self.assertTrue(any("--entrypoint yq" in call for call in calls))
        self.assertEqual(self.context.read_text().splitlines()[-1], SHA)
        dockerfile = (self.root / "builds/openclaw-enterprise/operator.Dockerfile").read_text()
        self.assertIn("python:3.13-bookworm@sha256:", dockerfile)
        self.assertIn("USER 10001:10001", dockerfile)

    def test_dirty_checkout_and_wrong_label_fail(self):
        result = self.build(FIXTURE_DIRTY="true")
        self.assertNotEqual(result.returncode, 0)
        self.assertFalse(self.calls.exists())
        result = self.build(FIXTURE_LABEL_SHA="b" * 40)
        self.assertNotEqual(result.returncode, 0)
        self.assertTrue(self.calls.exists())

    def test_embedded_source_marker_must_match_reviewed_sha(self):
        with mock.patch.object(source, "ROOT", self.root):
            with self.assertRaisesRegex(source.Blocked, "unavailable"):
                source._require_operator_image_source(SHA)
            (self.root / "operator-source.sha").write_text("b" * 40 + "\n")
            with self.assertRaisesRegex(source.Blocked, "changed"):
                source._require_operator_image_source(SHA)
            (self.root / "operator-source.sha").write_text(SHA + "\n")
            source._require_operator_image_source(SHA)


if __name__ == "__main__":
    unittest.main()
