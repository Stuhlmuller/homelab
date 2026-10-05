#!/usr/bin/env python3
"""Exercise NAS repair boundaries without contacting the NAS or Kubernetes."""
import contextlib
import importlib.util
import io
import json
import os
from pathlib import Path
import shlex
import subprocess
import tempfile
import unittest
from unittest import mock

SPEC = importlib.util.spec_from_file_location("repair", Path(__file__).resolve().parents[1] / "nas-media-permissions.py")
repair = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(repair)


class RepairTests(unittest.TestCase):
    def inventory(self, *pairs):
        fields = ["base", "/share/disk/media", *(field for pair in pairs for field in pair), ""]
        return mock.Mock(stdout="\0".join(fields).encode())

    def test_registered_paths_cannot_select_share_or_escape(self):
        self.assertEqual(repair.relative_path("sonarr", "/tv/Series's $name"), "tv/Series's $name")
        for path in ("/tv", "/tv/", "/tv/../private", "/tv//x", "/tv/x/./y", "/tv/x\ny", "/movies/x", "/tv/x\\y"):
            with self.subTest(path=path), self.assertRaises(ValueError):
                repair.relative_path("sonarr", path)

    def test_inventory_counts_missing_and_only_modes_needing_repair(self):
        result = self.inventory(("missing", "/share/disk/media/tv/Absent"),
                                ("d 1000 770 1 2", "/share/disk/media/tv/Series"),
                                ("f 1000 664 1 3", "/share/disk/media/tv/Series/video.mkv"))
        with mock.patch.object(repair, "run", return_value=result) as run:
            base, entries, missing = repair.inspect(["tv/Series", "tv/Absent"])
        self.assertEqual((base, len(entries), missing), ("/share/disk/media", 1, 1))
        script = run.call_args.kwargs["input"].decode()
        self.assertIn("-user 1000", script)
        self.assertNotIn("find -L", script)
        self.assertIn('else\n[ -d "$root" ]', script)
        subprocess.run(["/bin/sh", "-n"], input=script.encode(), check=True)

    def test_registered_root_on_another_filesystem_is_not_scanned(self):
        with tempfile.TemporaryDirectory() as directory:
            base = Path(directory).resolve()
            (base / "tv/Series").mkdir(parents=True)
            marker = base / "find-was-called"
            # Emulate a mounted registered root without requiring mount privileges.
            # Execute the real generated shell; a find call would create the marker.
            preamble = f"set -eu\nbase={shlex.quote(str(base))}\n"
            preamble += 'stat() { if [ "$3" = "$base" ]; then echo 1; else echo 2; fi; }\n'
            preamble += f"find() {{ touch {shlex.quote(str(marker))}; }}\n"
            preamble += repair.PREAMBLE[repair.PREAMBLE.index("validate() {"):]

            def shell(_command, **kwargs):
                return subprocess.run(["/bin/sh"], capture_output=True, check=True, **kwargs)

            with mock.patch.object(repair, "PREAMBLE", preamble), \
                 mock.patch.object(repair, "run", side_effect=shell), \
                 self.assertRaises(subprocess.CalledProcessError) as error:
                repair.inspect(["tv/Series"])
            self.assertEqual(error.exception.returncode, 79)
            self.assertFalse(marker.exists())

    def test_unowned_and_escaped_inventory_rejected(self):
        for meta, path in (("f 65534 600 1 2", "/share/disk/media/tv/Series/a"),
                           ("f 1000 600 1 2", "/share/disk/media/private/a")):
            with mock.patch.object(repair, "run", return_value=self.inventory((meta, path))), self.assertRaises(ValueError):
                repair.inspect(["tv/Series"])

    def test_preview_never_sends_mutation(self):
        with mock.patch.object(repair, "registered", return_value=({}, ["tv/Series"])), \
             mock.patch.object(repair, "inspect", return_value=("/share/disk/media", [{"path": "private"}], 0)), \
             mock.patch.object(repair, "run") as run, contextlib.redirect_stdout(io.StringIO()) as out:
            repair.main([])
        run.assert_not_called()
        self.assertEqual(json.loads(out.getvalue())["applied_changes"], 0)
        self.assertNotIn("private", out.getvalue())

    def test_execution_requires_journal_and_reviewed_main(self):
        with self.assertRaises(ValueError):
            repair.main(["--execute"])
        with mock.patch.object(repair, "reviewed_main", side_effect=ValueError("guard")) as guard, \
             mock.patch.object(repair, "registered") as inventory, self.assertRaises(ValueError):
            repair.main(["--execute", "--journal", "/private/tmp/modes.json", "--expected-sha", "bad"])
        guard.assert_called_once_with("bad")
        inventory.assert_not_called()
        with self.assertRaises(ValueError):
            repair.main(["--rescan"])

    def test_journal_is_private_exclusive_and_outside_repo(self):
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "modes.json"
            repair.save_journal(path, {"entries": []})
            self.assertEqual(path.stat().st_mode & 0o777, 0o600)
            with self.assertRaises(FileExistsError):
                repair.save_journal(path, {})
        with self.assertRaises(ValueError):
            repair.save_journal(repair.ROOT / "private-modes.json", {})

    def test_shell_quoting_and_symlink_boundary_before_chmod(self):
        with tempfile.TemporaryDirectory() as directory:
            base = Path(directory).resolve()
            folder = base / "Series's $(touch injected)"
            folder.mkdir(mode=0o700)
            entry = {"path": str(folder), "kind": "d", "mode": "700", "identity": "1000 700 1 2"}
            # Keep the real boundary function and chmod; stand in for NAS uid/stat only.
            preamble = f"set -eu\nbase={shlex.quote(str(base))}\nstat() {{ printf '1000 700 1 2\\n'; }}\n"
            preamble += repair.PREAMBLE[repair.PREAMBLE.index("validate() {"):]
            with mock.patch.object(repair, "PREAMBLE", preamble):
                script = repair.mutation_script(str(base), [entry])
            subprocess.run(["/bin/sh"], input=script.encode(), cwd=base, check=True)
            self.assertEqual(folder.stat().st_mode & 0o777, 0o777)
            self.assertFalse((base / "injected").exists())
            link = base / "link"
            link.symlink_to(folder, target_is_directory=True)
            entry["path"] = str(link)
            with mock.patch.object(repair, "PREAMBLE", preamble):
                script = repair.mutation_script(str(base), [entry])
            result = subprocess.run(["/bin/sh"], input=script.encode(), capture_output=True)
            self.assertEqual(result.returncode, 73)

    def test_regular_files_gain_read_only_and_identity_checked(self):
        entry = {"path": "/share/disk/media/tv/Series/file", "kind": "f", "identity": "1000 600 1 2"}
        script = repair.mutation_script("/share/disk/media", [entry])
        self.assertIn("chmod a+r ", script)
        self.assertNotIn("chmod a+rwX", script)
        self.assertEqual(script.count('stat -c "%u %a %d %i"'), 2)
        self.assertLess(script.index("1000 600 1 2"), script.index("chmod"))


if __name__ == "__main__":
    unittest.main()
