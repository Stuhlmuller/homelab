#!/usr/bin/env python3
"""Exercise backup publication and failure handling without live credentials."""

import hashlib
import json
import os
import shutil
import subprocess
import tempfile
import time
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
APP = ROOT / "clusters/homelab/apps/fleet"
DUMP = "CREATE TABLE example (id int);\n-- Dump completed on 2026-10-03 00:00:00\n"


class BackupTest(unittest.TestCase):
    def setUp(self):
        self.directory = tempfile.TemporaryDirectory()
        self.addCleanup(self.directory.cleanup)
        self.root = Path(self.directory.name)
        self.bin = self.root / "bin"
        self.bin.mkdir()
        self.backups = self.root / "backups"
        self.backups.mkdir()
        self.write_tool("mysqldump", f"""
import sys
from pathlib import Path
assert '--max-allowed-packet=512M' in sys.argv
assert '--single-transaction' in sys.argv
target = next(arg.split('=', 1)[1] for arg in sys.argv if arg.startswith('--result-file='))
Path(target).write_text({DUMP!r})
""")
        self.expired = self.backups / "fleet-20200101T000000Z"
        self.expired.mkdir()
        (self.expired / "fleet.sql").write_text("old recovery copy")
        old = time.time() - 15 * 86400
        os.utime(self.expired, (old, old))

    def write_tool(self, name, body):
        tool = self.bin / name
        tool.write_text("#!/usr/bin/env python3\n" + body)
        tool.chmod(0o755)

    def run_backup(self):
        return subprocess.run(
            ["bash", str(APP / "backup.sh"), str(self.backups)],
            env={**os.environ, "PATH": str(self.bin) + os.pathsep + os.environ["PATH"]},
            text=True, capture_output=True, check=False)

    def test_complete_set_is_verified_before_atomic_publication_and_pruning(self):
        self.write_tool("mv", f"""
import hashlib
import os
from pathlib import Path
import sys
assert sys.argv[1:3] == ['-T', '--']
source = Path(sys.argv[3])
assert sorted(p.name for p in source.iterdir()) == ['fleet.sql', 'fleet.sql.sha256']
assert hashlib.sha256((source / 'fleet.sql').read_bytes()).hexdigest() == (source / 'fleet.sql.sha256').read_text().split()[0]
os.execv({shutil.which("mv")!r}, [{shutil.which("mv")!r}] + sys.argv[1:])
""")
        recent = self.backups / "fleet-20261002T000000Z"
        recent.mkdir()
        unrelated = self.backups / "keep-me"
        unrelated.mkdir()
        result = self.run_backup()
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertFalse(self.expired.exists())
        self.assertTrue(recent.exists())
        self.assertTrue(unrelated.exists())
        published = [p for p in self.backups.glob("fleet-*") if p != recent]
        self.assertEqual(len(published), 1)
        self.assertEqual((published[0] / "fleet.sql").read_text(), DUMP)
        self.assertEqual((published[0] / "fleet.sql.sha256").read_text().split()[0],
                         hashlib.sha256(DUMP.encode()).hexdigest())
        self.assertEqual(list(self.backups.glob(".pending-*")), [])

    def test_dump_failures_never_publish_or_prune(self):
        for body in ("raise SystemExit(1)", "", "SELECT 1;\n"):
            with self.subTest(body=body):
                self.write_tool("mysqldump", f"""
import sys
from pathlib import Path
target = next(arg.split('=', 1)[1] for arg in sys.argv if arg.startswith('--result-file='))
Path(target).write_text({(body if body != "raise SystemExit(1)" else DUMP)!r})
{body if body == "raise SystemExit(1)" else ""}
""")
                result = self.run_backup()
                self.assertNotEqual(result.returncode, 0)
                self.assertEqual(list(self.backups.iterdir()), [self.expired])

    def test_checksum_failure_never_publishes_or_prunes(self):
        self.write_tool("sha256sum", f"""
import os
import sys
if '--check' in sys.argv:
    raise SystemExit(1)
os.execv({shutil.which("sha256sum")!r}, [{shutil.which("sha256sum")!r}] + sys.argv[1:])
""")
        self.assertNotEqual(self.run_backup().returncode, 0)
        self.assertEqual(list(self.backups.iterdir()), [self.expired])

    def test_publication_collision_preserves_existing_backup_and_prevents_pruning(self):
        self.write_tool("date", "print('20200101T000000Z')")
        self.assertNotEqual(self.run_backup().returncode, 0)
        self.assertEqual(list(self.backups.iterdir()), [self.expired])
        self.assertEqual((self.expired / "fleet.sql").read_text(), "old recovery copy")

    def test_postsync_and_nightly_jobs_share_the_tested_pod_contract(self):
        job = json.loads(subprocess.check_output(
            ["yq", "-o=json", ".", str(APP / "backup-job.yaml")], text=True))
        cron = json.loads(subprocess.check_output(
            ["yq", "-o=json", ".", str(APP / "backup-cronjob.yaml")], text=True))
        self.assertEqual(job["metadata"]["annotations"]["argocd.argoproj.io/hook"], "PostSync")
        self.assertEqual(job["spec"]["template"], cron["spec"]["jobTemplate"]["spec"]["template"])


if __name__ == "__main__":
    unittest.main()
