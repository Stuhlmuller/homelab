#!/usr/bin/env python3
"""Check the dormant restore image's reviewed source and publication gates."""

import os
from pathlib import Path
import shutil
import subprocess
import tempfile
import unittest


ROOT = Path(__file__).resolve().parents[2]
SHA = "a" * 40
BASE = "docker.io/library/postgres:18.6-bookworm@sha256:afc7e2d441324c0388fa80c3d24f733b4194a4eb7f47dd8ee2b08eb1a24a647c"
WORKFLOW = ROOT / ".github/workflows/openclaw-enterprise-images.yml"


class RestoreImageBuild(unittest.TestCase):
    def setUp(self):
        self.temporary = tempfile.TemporaryDirectory(prefix="oce-restore-image-")
        self.addCleanup(self.temporary.cleanup)
        self.root = Path(self.temporary.name)
        for directory in ("builds/openclaw-enterprise-restore", "scripts/config", "bin"):
            (self.root / directory).mkdir(parents=True)
        for name in ("build.sh", "Dockerfile", "safe-extract.py"):
            shutil.copyfile(ROOT / "builds/openclaw-enterprise-restore" / name,
                            self.root / "builds/openclaw-enterprise-restore" / name)
        shutil.copyfile(ROOT / "scripts/config/harbor-images.json",
                        self.root / "scripts/config/harbor-images.json")
        self.calls = self.root / "docker-calls"
        self.executable("git", f'''case "$1" in
  rev-parse) printf '%s\\n' {SHA} ;;
  status) [[ "${{FIXTURE_DIRTY:-}}" != true ]] || printf ' M Dockerfile\\n' ;;
  *) exit 97 ;;
esac
''')
        self.executable("uname", '''case "$1" in
  -s) printf 'Linux\\n' ;;
  -m) printf 'x86_64\\n' ;;
  *) exit 97 ;;
esac
''')
        self.executable("docker", '''printf '%s\\n' "$*" >>"$DOCKER_CALLS"
if [[ "$1 $2" == 'image inspect' ]]; then
  case "$4" in
    '{{.Id}}') printf 'sha256:%064d\\n' 1 ;;
    *) printf '%s\\n' "${FIXTURE_LABEL_SHA:-$GITHUB_SHA}" ;;
  esac
elif [[ "$1" == run ]]; then
  case "$*" in
    *'--entrypoint age '*) printf 'v1.3.1\\n' ;;
    *'--entrypoint sha256sum '*) sha256sum builds/openclaw-enterprise-restore/safe-extract.py ;;
  esac
elif [[ "$1" == save ]]; then
  [[ "$2" == --output ]]
  printf 'fixture archive' >"$3"
fi
''')
        self.executable("nix", '''[[ "$1 $2" == 'build --out-link' ]] || exit 97
mkdir -p "$3/bin"
cat >"$3/bin/grype" <<'GRYPE'
#!/usr/bin/env bash
set -euo pipefail
while [[ "$1" != --file ]]; do shift; done
printf '{}' >"$2"
GRYPE
chmod +x "$3/bin/grype"
''')
        self.executable("python3", '''[[ "$1" == -I && "$2" == scripts/ci/harbor-core-scan-check.py &&
   "$3" == --expected-distro && "$4" == debian:12 && "$5" == --archive ]] || exit 97
test -s "$6" && test -s "$7"
[[ "${FIXTURE_SCAN_FAIL:-}" != true ]] || exit 1
''')

    def executable(self, name, body):
        path = self.root / "bin" / name
        path.write_text("#!/usr/bin/env bash\nset -euo pipefail\n" + body)
        path.chmod(0o700)

    def build(self, **extra):
        return subprocess.run(
            ["bash", str(self.root / "builds/openclaw-enterprise-restore/build.sh")],
            cwd=self.root,
            env={**os.environ, "PATH": f"{self.root / 'bin'}:{os.environ['PATH']}",
                 "DOCKER_CALLS": str(self.calls), "GITHUB_SHA": SHA, **extra},
            capture_output=True, text=True, timeout=20, check=False,
        )

    def test_reviewed_catalog_source_builds_and_smokes_one_image(self):
        result = self.build()
        self.assertEqual(result.returncode, 0, result.stderr)
        calls = self.calls.read_text().splitlines()
        self.assertEqual(len([call for call in calls if call.startswith("buildx build ")]), 1)
        self.assertIn("--platform linux/amd64", calls[0])
        self.assertIn("org.opencontainers.image.revision=" + SHA, calls[0])
        self.assertIn("homelab-oce-restore:build", calls[0])
        for command in ("age", "python3", "jq", "mountpoint", "pg_restore", "pg_dump", "sha256sum"):
            self.assertTrue(any(f"--network none --read-only --user 999:999 --entrypoint {command} " in call
                                for call in calls), command)
        dockerfile = (self.root / "builds/openclaw-enterprise-restore/Dockerfile").read_text()
        self.assertIn("FROM --platform=linux/amd64 " + BASE, dockerfile)
        self.assertIn("--no-install-recommends python3 jq util-linux", dockerfile)

    def test_dirty_source_wrong_revision_and_wrong_base_block_before_publish(self):
        self.assertNotEqual(self.build(FIXTURE_DIRTY="true").returncode, 0)
        self.assertFalse(self.calls.exists())
        self.assertNotEqual(self.build(GITHUB_SHA="b" * 40).returncode, 0)
        self.assertFalse(self.calls.exists())
        dockerfile = self.root / "builds/openclaw-enterprise-restore/Dockerfile"
        dockerfile.write_text(dockerfile.read_text().replace(BASE, "docker.io/library/postgres:latest"))
        self.assertNotEqual(self.build().returncode, 0)
        self.assertFalse(self.calls.exists())

    def test_wrong_image_revision_blocks_after_build(self):
        result = self.build(FIXTURE_LABEL_SHA="b" * 40)
        self.assertNotEqual(result.returncode, 0)
        self.assertEqual(len(self.calls.read_text().splitlines()), 2)

    def test_scan_and_publication_bind_the_same_image_before_credentials(self):
        workflow = WORKFLOW.read_text()
        build = "bash builds/openclaw-enterprise-restore/build.sh"
        scan = "bash builds/openclaw-enterprise-restore/scan.sh"
        credentials = "- name: Configure AWS Credentials"
        self.assertLess(workflow.index(build), workflow.index(scan))
        self.assertLess(workflow.index(scan), workflow.index(credentials))
        self.assertIn("EXPECTED_RESTORE_IMAGE_ID: ${{ steps.restore_scan.outputs.restore_image_id }}", workflow)
        self.assertIn("restore: ${{ steps.publication.outputs.restore }}", workflow)
        self.assertIn("RESTORE_REFERENCE: ${{ needs.publish.outputs.restore }}", workflow)
        self.assertIn("oce-restore-published-image-${{ github.run_id }}-${{ github.run_attempt }}", workflow)
        scan_script = (ROOT / "builds/openclaw-enterprise-restore/scan.sh").read_text()
        self.assertIn("--expected-distro debian:12", scan_script)
        self.assertIn("--archive \"$scratch/image.tar\"", scan_script)
        self.assertIn("printf 'restore_image_id=%s\\n' \"$image_id\" >>\"$GITHUB_OUTPUT\"", scan_script)
        self.assertNotIn("OCTELIUM_AUTH_TOKEN", workflow[:workflow.index(credentials)])

    def test_scan_emits_image_id_only_after_private_checker_passes(self):
        output = self.root / "scan-output"
        env = {**os.environ, "PATH": f"{self.root / 'bin'}:{os.environ['PATH']}",
               "DOCKER_CALLS": str(self.calls), "GITHUB_ACTIONS": "true",
               "GITHUB_SHA": SHA, "RUNNER_TEMP": str(self.root),
               "GITHUB_OUTPUT": str(output)}
        command = ["bash", str(ROOT / "builds/openclaw-enterprise-restore/scan.sh")]
        failed = subprocess.run(command, cwd=self.root, env={**env, "FIXTURE_SCAN_FAIL": "true"},
                                capture_output=True, text=True, timeout=20, check=False)
        self.assertNotEqual(failed.returncode, 0)
        self.assertFalse(output.exists())
        passed = subprocess.run(command, cwd=self.root, env=env,
                                capture_output=True, text=True, timeout=20, check=False)
        self.assertEqual(passed.returncode, 0, passed.stderr)
        self.assertEqual(output.read_text(), "restore_image_id=sha256:" + "0" * 63 + "1\n")


if __name__ == "__main__":
    unittest.main()
