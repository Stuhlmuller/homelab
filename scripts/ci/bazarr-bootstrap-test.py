#!/usr/bin/env python3
"""Exercise credential handling, profile preservation and consistent SQLite backup."""

import contextlib
import hashlib
import importlib.util
import io
import json
from pathlib import Path
import sqlite3
import tarfile
import tempfile
import unittest
from unittest.mock import patch


ROOT = Path(__file__).resolve().parents[2]
SPEC = importlib.util.spec_from_file_location(
    "bazarr_bootstrap", ROOT / "clusters/homelab/apps/bazarr/bootstrap.py")
BOOTSTRAP = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(BOOTSTRAP)


class BootstrapTests(unittest.TestCase):
    def test_postsync_only_configures_and_schedules_imports(self):
        calls = []

        def api(url, _key, fields=None):
            calls.append((url.removeprefix(BOOTSTRAP.API), fields))
            return [] if fields is None else None

        with patch.object(BOOTSTRAP, "api_config", return_value={"auth": {"apikey": "test"}}), \
                patch.object(BOOTSTRAP, "PROFILE", ROOT / "clusters/homelab/apps/bazarr/profile.json"), \
                patch.object(BOOTSTRAP, "request", side_effect=api), \
                patch.object(BOOTSTRAP, "library") as library, \
                patch.object(BOOTSTRAP, "search_missing") as search, contextlib.redirect_stdout(io.StringIO()):
            BOOTSTRAP.reconcile()
        self.assertEqual([path for path, _ in calls],
                         ["system/languages/profiles", "system/settings", "system/tasks", "system/tasks"])
        fields = dict(calls[1][1])
        self.assertEqual(fields["settings-general-serie_default_profile"], "1")
        self.assertEqual(fields["settings-general-movie_default_profile"], "1")
        self.assertEqual([fields["taskid"] for _, fields in calls[2:]], ["update_series", "update_movies"])
        library.assert_not_called()
        search.assert_not_called()

    def test_finish_waits_for_import_assigns_only_null_and_captures_revision(self):
        profile_bytes = (ROOT / "clusters/homelab/apps/bazarr/profile.json").read_bytes()
        profile = json.loads(profile_bytes)
        expected = {"sonarr": [{"id": 10, "statistics": {"episodeFileCount": 2}}],
                    "radarr": [{"id": 20, "hasFile": True}]}
        assigned = []
        snapshots = iter([[{"job_id": 1, "job_name": "Syncing series with Sonarr", "status": "running"}], []])

        def api(url, _key, fields=None):
            endpoint = url.removeprefix(BOOTSTRAP.API)
            if endpoint == "system/languages/profiles":
                return [profile]
            if fields is not None:
                assigned.append((endpoint, fields))
                return None
            if endpoint == "series":
                return {"data": [{"sonarrSeriesId": 10, "episodeFileCount": 2,
                                  "profileId": 1 if assigned else None}]}
            if endpoint == "movies":
                return {"data": [{"radarrId": 20, "profileId": 2}]}
            if endpoint == "system/jobs":
                return {"data": next(snapshots)}
            raise AssertionError(f"Unexpected endpoint {endpoint}")

        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            path = root / "profile.json"
            path.write_bytes(profile_bytes)
            with patch.object(BOOTSTRAP, "CONFIG", root), patch.object(BOOTSTRAP, "PROFILE", path), \
                    patch.object(BOOTSTRAP, "api_config", return_value={"auth": {"apikey": "test"}}), \
                    patch.object(BOOTSTRAP, "library", return_value=expected), \
                    patch.object(BOOTSTRAP, "request", side_effect=api), \
                    patch.object(BOOTSTRAP.time, "sleep") as sleep, \
                    patch.object(BOOTSTRAP, "search_missing", side_effect=lambda *args, **kwargs: path.write_text("{}")) \
                    as search, contextlib.redirect_stdout(io.StringIO()):
                BOOTSTRAP.finish_setup()
            self.assertEqual(assigned, [("series", [("seriesid", 10), ("profileid", 1)])])
            sleep.assert_called_once_with(5)
            self.assertGreater(search.call_args.kwargs["timeout"], 0)
            self.assertLessEqual(search.call_args.kwargs["timeout"], 1800)
            self.assertEqual((root / ".homelab-profile").read_text().strip(),
                             hashlib.sha256(profile_bytes).hexdigest())
            self.assertFalse((root / ".homelab-profile.partial").exists())

    def test_finish_does_not_mark_failed_search_complete(self):
        profile = json.loads((ROOT / "clusters/homelab/apps/bazarr/profile.json").read_text())

        def api(url, _key, fields=None):
            return [profile] if url.endswith("system/languages/profiles") else {"data": []}

        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            with patch.object(BOOTSTRAP, "CONFIG", root), \
                    patch.object(BOOTSTRAP, "PROFILE", ROOT / "clusters/homelab/apps/bazarr/profile.json"), \
                    patch.object(BOOTSTRAP, "api_config", return_value={"auth": {"apikey": "test"}}), \
                    patch.object(BOOTSTRAP, "library", return_value={"sonarr": [], "radarr": []}), \
                    patch.object(BOOTSTRAP, "request", side_effect=api), \
                    patch.object(BOOTSTRAP, "search_missing", side_effect=RuntimeError("failed")):
                with self.assertRaises(RuntimeError):
                    BOOTSTRAP.finish_setup()
            self.assertFalse((root / ".homelab-profile").exists())

    def test_file_credentials_and_existing_identity_survive_restart(self):
        with tempfile.TemporaryDirectory() as directory:
            xml = Path(directory) / "config.xml"
            xml.write_text("<Config><ApiKey>test&amp;key</ApiKey></Config>")
            key = BOOTSTRAP.arr_key(xml)
        current = {"general": {"use_sonarr": True}, "auth": {"apikey": "existing"},
                   "opensubtitlescom": {"username": "keep"}}
        updated = BOOTSTRAP.desired_config(current, {"sonarr": key, "radarr": "test2"})
        self.assertEqual(updated["sonarr"]["apikey"], "test&key")
        self.assertEqual(updated["auth"]["apikey"], "existing")
        self.assertEqual(updated["opensubtitlescom"], {"username": "keep"})
        self.assertTrue(updated["general"]["use_sonarr"])
        self.assertFalse(updated["general"]["use_radarr"])
        self.assertNotIn("radarr", current)

    def test_ambiguous_credentials_fail_closed(self):
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "config.xml"
            for value in ("", "<ApiKey/>", "<ApiKey>a</ApiKey><ApiKey>b</ApiKey>"):
                path.write_text(f"<Config>{value}</Config>")
                with self.assertRaises(ValueError):
                    BOOTSTRAP.arr_key(path)

    def test_profiles_are_not_deleted_or_overwritten(self):
        profile = json.loads((ROOT / "clusters/homelab/apps/bazarr/profile.json").read_text())
        separate = {"profileId": 2, "name": "French"}
        self.assertEqual(BOOTSTRAP.merged_profiles([separate], profile), [separate, profile])
        self.assertEqual(BOOTSTRAP.merged_profiles([separate, profile], profile), [separate, profile])
        with self.assertRaises(ValueError):
            BOOTSTRAP.merged_profiles([{"profileId": 1, "name": "French"}], profile)

    def test_backup_includes_committed_wal_without_leaking_config(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            config = root / "config"
            (config / "db").mkdir(parents=True)
            (config / "config").mkdir()
            (config / "config/config.yaml").write_text("private-test-marker")
            with contextlib.closing(sqlite3.connect(config / "db/bazarr.db")) as database:
                database.execute("PRAGMA journal_mode=WAL")
                database.execute("CREATE TABLE sample (value TEXT)")
                database.execute("INSERT INTO sample VALUES ('committed')")
                database.commit()
                output = io.StringIO()
                with contextlib.redirect_stdout(output):
                    BOOTSTRAP.backup(config, root / "backups")
                self.assertNotIn("private-test-marker", output.getvalue())
                archive_path, = (root / "backups").glob("*.tar.gz")
                with tarfile.open(archive_path) as archive:
                    self.assertEqual(archive.extractfile("config/config.yaml").read(), b"private-test-marker")
                    restored = root / "restored.db"
                    restored.write_bytes(archive.extractfile("db/bazarr.db").read())
                with contextlib.closing(sqlite3.connect(restored)) as restored_db:
                    self.assertEqual(restored_db.execute("SELECT value FROM sample").fetchall(), [("committed",)])
                    self.assertEqual(restored_db.execute("PRAGMA integrity_check").fetchone(), ("ok",))

    def test_backup_closes_connections_before_snapshot_cleanup(self):
        real_connect = sqlite3.connect
        real_directory = tempfile.TemporaryDirectory
        testcase = self
        for fail_copy in (False, True):
            with self.subTest(fail_copy=fail_copy), real_directory() as directory:
                root = Path(directory)
                config = root / "config"
                (config / "db").mkdir(parents=True)
                (config / "config").mkdir()
                (config / "config/config.yaml").write_text("synthetic: true")
                with contextlib.closing(real_connect(config / "db/bazarr.db")) as database:
                    database.execute("CREATE TABLE sample (value INTEGER)")
                    database.commit()
                connections = []
                cleanup_checked = []

                class Connection(sqlite3.Connection):
                    def backup(self, *args, **kwargs):
                        if fail_copy:
                            raise RuntimeError("Synthetic backup failure")
                        return super().backup(*args, **kwargs)

                def connect(*args, **kwargs):
                    connection = real_connect(*args, factory=Connection, **kwargs)
                    connections.append(connection)
                    return connection

                class SnapshotDirectory(real_directory):
                    def __exit__(self, *args):
                        try:
                            testcase.assertEqual(len(connections), 2)
                            for connection in connections:
                                with testcase.assertRaises(sqlite3.ProgrammingError):
                                    connection.execute("SELECT 1")
                            cleanup_checked.append(True)
                        finally:
                            super().__exit__(*args)

                try:
                    with patch.object(BOOTSTRAP.sqlite3, "connect", side_effect=connect), \
                            patch.object(BOOTSTRAP.tempfile, "TemporaryDirectory", SnapshotDirectory), \
                            contextlib.redirect_stdout(io.StringIO()):
                        expected = self.assertRaisesRegex(RuntimeError, "Synthetic backup failure") \
                            if fail_copy else contextlib.nullcontext()
                        with expected:
                            BOOTSTRAP.backup(config, root / "backups")
                    self.assertEqual(cleanup_checked, [True])
                finally:
                    for connection in connections:
                        connection.close()

    def test_search_waits_for_new_jobs_instead_of_old_completion(self):
        old = [{"job_id": 1, "job_name": "Searched for missing series subtitles", "status": "completed"},
               {"job_id": 2, "job_name": "Searched for missing movies subtitles", "status": "completed"}]
        completed = [{**job, "job_id": job["job_id"] + 2} for job in old]
        snapshots = iter([old, old, old + completed])
        scheduled = []

        def api(url, _key, fields=None):
            if fields is not None:
                scheduled.append(fields["taskid"])
                return None
            return {"data": next(snapshots)}

        with patch.object(BOOTSTRAP, "request", side_effect=api), patch.object(BOOTSTRAP.time, "sleep"):
            BOOTSTRAP.search_missing("private-key")
        self.assertEqual(set(scheduled), {"wanted_search_missing_subtitles_series",
                                         "wanted_search_missing_subtitles_movies"})

    def test_search_reuses_active_jobs_and_rejects_throttling(self):
        jobs = [{"job_id": number, "job_name": f"Searching for missing {kind} subtitles",
                 "status": "running"} for number, kind in enumerate(("series", "movies"))]
        failed = [{**job, "status": "completed", "progress_message": "All providers throttled"} for job in jobs]
        with patch.object(BOOTSTRAP, "request", side_effect=[{"data": jobs}, {"data": failed}]) as api:
            with self.assertRaises(RuntimeError):
                BOOTSTRAP.search_missing("private-key")
        self.assertEqual(api.call_count, 2)
        self.assertTrue(all(len(call.args) == 2 for call in api.call_args_list))

    def test_search_does_not_claim_success_when_scheduler_has_not_started(self):
        def api(_url, _key, fields=None):
            return None if fields else {"data": []}

        with patch.object(BOOTSTRAP, "request", side_effect=api):
            with self.assertRaises(RuntimeError):
                BOOTSTRAP.search_missing("private-key", timeout=0)


if __name__ == "__main__":
    unittest.main()
