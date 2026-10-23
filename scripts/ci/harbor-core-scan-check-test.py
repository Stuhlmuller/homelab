"""Exact-image, freshness, completeness and remediation audit boundaries."""
import base64
import copy
from datetime import datetime, timedelta, timezone
import hashlib
import importlib.util
import json
from pathlib import Path
import unittest
from contextlib import redirect_stderr, redirect_stdout
import io
import os
import subprocess
import tarfile
import tempfile

spec = importlib.util.spec_from_file_location("scan", Path(__file__).with_name("harbor-core-scan-check.py"))
scan = importlib.util.module_from_spec(spec)
spec.loader.exec_module(scan)
CONFIG = json.dumps({"os": "linux", "architecture": "amd64"}).encode()
IMAGE = "sha256:" + hashlib.sha256(CONFIG).hexdigest()
CORE_PUBLICATION_WORKFLOW = Path(__file__).resolve().parents[2] / ".github/workflows/harbor-core-images.yml"
SCAN_SCRIPT = Path(__file__).resolve().parents[2] / "builds/harbor-core/scan.sh"
STATUS_SCRIPT = Path(__file__).with_name("harbor-core-audit-status.sh")
VALIDATE_WORKFLOW = Path(__file__).resolve().parents[2] / ".github/workflows/validate.yml"


class ScanTests(unittest.TestCase):
    def report(self):
        now = datetime.now(timezone.utc).isoformat()
        return {"source": {"type": "image", "target": {"imageID": IMAGE, "os": "", "architecture": "",
            "layers": ["fixture"], "imageSize": 1, "config": base64.b64encode(CONFIG).decode()}},
            "distro": {"name": "photon", "version": "5.0"}, "matches": [], "descriptor": {
            "name": "grype", "version": "0.112.0", "timestamp": now,
            "db": {"status": {"valid": True, "built": now}}, "configuration": {
            "only-fixed": False, "only-notfixed": False, "ignore-wontfix": "", "ignore": [],
            "exclude": [], "vex-documents": [], "search": {"scope": "squashed"}}}}

    def test_unresolved_findings_remain_unchanged(self):
        for state in ("not-fixed", "unknown", "wont-fix", ""):
            report = self.report()
            report["matches"] = [{"vulnerability": {"severity": "Unknown", "fix": {"state": state, "versions": []}}}]
            original = copy.deepcopy(report)
            scan.verify(report, IMAGE)
            self.assertEqual(report, original)

    def test_refuses_available_fixes(self):
        for fix in ({"state": "fixed", "versions": ["fixed-version"]},
                    {"state": "", "versions": ["fixed-version"]},
                    {"state": "unknown", "versions": [], "available": [{"version": "fixed-version"}]}):
            report = self.report()
            report["matches"] = [{"vulnerability": {"severity": "Unknown", "fix": fix}}]
            with self.assertRaisesRegex(AssertionError, "remediation"):
                scan.verify(report, IMAGE)

    def test_publication_clearance_requires_zero_matches(self):
        scan.verify(self.report(), IMAGE, require_zero_matches=True)
        report = self.report()
        report["matches"] = [{"vulnerability": {"severity": "Unknown", "fix": {"state": "unknown", "versions": []}}}]
        with self.assertRaisesRegex(AssertionError, "clearance"):
            scan.verify(report, IMAGE, require_zero_matches=True)

    def test_publication_switch_requires_zero_matches(self):
        report = self.report()
        report["matches"] = [{"vulnerability": {"severity": "Unknown", "fix": {"state": "unknown", "versions": []}}}]
        with tempfile.TemporaryDirectory() as root:
            path = Path(root) / "report.json"
            path.write_text(json.dumps(report))
            error = io.StringIO()
            with redirect_stderr(error):
                self.assertEqual(scan.main([str(path), IMAGE, "--require-zero-matches"]), 1)
        self.assertIn("clearance", error.getvalue())

    def test_protected_publication_wires_the_zero_match_gate(self):
        workflow = CORE_PUBLICATION_WORKFLOW.read_text()
        self.assertIn("bash builds/harbor-core/scan.sh --require-zero-matches", workflow)
        self.assertLess(workflow.index("bash builds/harbor-core/scan.sh --require-zero-matches"),
                        workflow.index("Configure AWS Credentials"))
        self.assertIn('"$@"', SCAN_SCRIPT.read_text())

    def test_failed_report_writes_only_fixed_category(self):
        report = self.report()
        report["matches"] = [{"vulnerability": {"severity": "High", "fix": {
            "state": "fixed", "versions": ["PRIVATE_VERSION"]}}}]
        with tempfile.TemporaryDirectory() as root:
            path = Path(root) / "report.json"
            diagnostic = Path(root) / "diagnostic"
            path.write_text(json.dumps(report))
            error = io.StringIO()
            with redirect_stderr(error):
                self.assertEqual(scan.main(["--diagnostic-file", str(diagnostic), str(path), IMAGE]), 1)
            self.assertEqual(diagnostic.read_text(), "validation:remediation\n")
            self.assertNotIn("PRIVATE_VERSION", error.getvalue())

    def test_identity_failures_write_only_specific_categories(self):
        cases = [
            ("identity-source", lambda r: r["source"].update(type="directory"), IMAGE),
            ("identity-image-id", lambda r: r["source"]["target"].update(imageID="sha256:" + "1" * 64), IMAGE),
            ("identity-archive", lambda r: r["source"]["target"].update(layers=[]), IMAGE),
            ("identity-report-config", lambda r: r["source"]["target"].update(config=base64.b64encode(b"{}").decode()), IMAGE),
            ("identity-distro", lambda r: r["distro"].update(name="unknown"), IMAGE),
        ]
        for category, change, image in cases:
            with self.subTest(category=category), tempfile.TemporaryDirectory() as root:
                report = self.report()
                change(report)
                path = Path(root) / "report.json"
                diagnostic = Path(root) / "diagnostic"
                path.write_text(json.dumps(report))
                with redirect_stderr(io.StringIO()):
                    self.assertEqual(scan.main(["--diagnostic-file", str(diagnostic), str(path), image]), 1)
                self.assertEqual(diagnostic.read_text(), f"validation:{category}\n")
        with tempfile.TemporaryDirectory() as root:
            report = self.report()
            raw = json.dumps({"os": "linux", "architecture": "arm64"}).encode()
            image = "sha256:" + hashlib.sha256(raw).hexdigest()
            report["source"]["target"].update(imageID=image, config=base64.b64encode(raw).decode())
            path = Path(root) / "report.json"
            diagnostic = Path(root) / "diagnostic"
            path.write_text(json.dumps(report))
            with redirect_stderr(io.StringIO()):
                self.assertEqual(scan.main(["--diagnostic-file", str(diagnostic), str(path), image]), 1)
            self.assertEqual(diagnostic.read_text(), "validation:identity-platform\n")

    def test_archive_and_report_config_are_bound_to_inspected_id(self):
        with tempfile.TemporaryDirectory() as root:
            root = Path(root)
            archive_path = root / "image.tar"
            report_path = root / "report.json"
            diagnostic = root / "diagnostic"

            def write_archive(config, config_name):
                with tarfile.open(archive_path, "w") as archive:
                    for name, data in (("manifest.json", json.dumps([{"Config": config_name}]).encode()),
                                       (config_name, config)):
                        member = tarfile.TarInfo(name)
                        member.size = len(data)
                        archive.addfile(member, io.BytesIO(data))

            report = self.report()
            report_path.write_text(json.dumps(report))
            for config_name in (IMAGE[7:] + ".json", "blobs/sha256/" + IMAGE[7:]):
                write_archive(CONFIG, config_name)
                with redirect_stdout(io.StringIO()):
                    self.assertEqual(scan.main(["--archive", str(archive_path), str(report_path), IMAGE]), 0)

            config_name = "blobs/sha256/" + IMAGE[7:]
            write_archive(b"PRIVATE_WRONG_CONFIG", config_name)
            with redirect_stderr(io.StringIO()):
                self.assertEqual(scan.main(["--diagnostic-file", str(diagnostic), "--archive", str(archive_path),
                                            str(report_path), IMAGE]), 1)
            self.assertEqual(diagnostic.read_text(), "validation:identity-archive-config-hash\n")

            write_archive(CONFIG, "blobs/sha256/" + "1" * 64)
            with redirect_stderr(io.StringIO()):
                self.assertEqual(scan.main(["--diagnostic-file", str(diagnostic), "--archive", str(archive_path),
                                            str(report_path), IMAGE]), 1)
            self.assertEqual(diagnostic.read_text(), "validation:identity-archive-config-hash\n")

            other_config = b'{"os":"linux","architecture":"amd64","other":true}'
            other_name = "blobs/sha256/" + hashlib.sha256(other_config).hexdigest()
            write_archive(other_config, other_name)
            with redirect_stderr(io.StringIO()):
                self.assertEqual(scan.main(["--diagnostic-file", str(diagnostic), "--archive", str(archive_path),
                                            str(report_path), IMAGE]), 1)
            self.assertEqual(diagnostic.read_text(), "validation:identity-archive-inspect-id\n")

            write_archive(CONFIG, config_name)
            report["source"]["target"]["config"] = base64.b64encode(b"PRIVATE_WRONG_CONFIG").decode()
            report_path.write_text(json.dumps(report))
            with redirect_stderr(io.StringIO()):
                self.assertEqual(scan.main(["--diagnostic-file", str(diagnostic), "--archive", str(archive_path),
                                            str(report_path), IMAGE]), 1)
            self.assertEqual(diagnostic.read_text(), "validation:identity-report-config\n")

            report = self.report()
            report["source"]["target"]["imageID"] = "sha256:" + "1" * 64
            report_path.write_text(json.dumps(report))
            with redirect_stderr(io.StringIO()):
                self.assertEqual(scan.main(["--diagnostic-file", str(diagnostic), "--archive", str(archive_path),
                                            str(report_path), IMAGE]), 1)
            self.assertEqual(diagnostic.read_text(), "validation:identity-image-id\n")

    def test_containerd_archive_binds_target_descriptor_to_selected_config(self):
        index_type = "application/vnd.oci.image.index.v1+json"
        manifest_type = "application/vnd.oci.image.manifest.v1+json"
        with tempfile.TemporaryDirectory() as root:
            root = Path(root)
            archive_path = root / "image.tar"
            report_path = root / "report.json"
            diagnostic = root / "diagnostic"
            report_path.write_text(json.dumps(self.report()))

            def encoded(value):
                return json.dumps(value, sort_keys=True, separators=(",", ":")).encode()

            def identity(raw):
                return "sha256:" + hashlib.sha256(raw).hexdigest()

            def write_oci(manifest_config=IMAGE, corrupt_target=False, direct_manifest=False):
                platform_manifest = encoded({
                    "schemaVersion": 2, "mediaType": manifest_type,
                    "config": {"mediaType": "application/vnd.oci.image.config.v1+json",
                               "digest": manifest_config, "size": len(CONFIG)},
                    "layers": [],
                })
                manifest_id = identity(platform_manifest)
                target = platform_manifest if direct_manifest else encoded({
                    "schemaVersion": 2, "mediaType": index_type,
                    "manifests": [{"mediaType": manifest_type, "digest": manifest_id,
                                   "size": len(platform_manifest),
                                   "platform": {"os": "linux", "architecture": "amd64"}}],
                })
                target_id = identity(target)
                target_type = manifest_type if direct_manifest else index_type
                content = {
                    "manifest.json": encoded([{"Config": "blobs/sha256/" + IMAGE[7:]}]),
                    "index.json": encoded({"schemaVersion": 2, "manifests": [
                        {"mediaType": target_type, "digest": target_id, "size": len(target)}]}),
                    "blobs/sha256/" + IMAGE[7:]: CONFIG,
                    "blobs/sha256/" + manifest_id[7:]: platform_manifest,
                    "blobs/sha256/" + target_id[7:]: b"bad target" if corrupt_target else target,
                }
                with tarfile.open(archive_path, "w") as archive:
                    for name, data in content.items():
                        member = tarfile.TarInfo(name)
                        member.size = len(data)
                        archive.addfile(member, io.BytesIO(data))
                return target_id

            for direct_manifest in (False, True):
                target_id = write_oci(direct_manifest=direct_manifest)
                with redirect_stdout(io.StringIO()):
                    self.assertEqual(scan.main(["--archive", str(archive_path), str(report_path), target_id]), 0)

            with redirect_stderr(io.StringIO()):
                self.assertEqual(scan.main(["--diagnostic-file", str(diagnostic), "--archive", str(archive_path),
                                            str(report_path), "sha256:" + "1" * 64]), 1)
            self.assertEqual(diagnostic.read_text(), "validation:identity-archive-inspect-id\n")

            target_id = write_oci(manifest_config="sha256:" + "1" * 64)
            with redirect_stderr(io.StringIO()):
                self.assertEqual(scan.main(["--diagnostic-file", str(diagnostic), "--archive", str(archive_path),
                                            str(report_path), target_id]), 1)
            self.assertEqual(diagnostic.read_text(), "validation:identity-archive-descriptor\n")

            target_id = write_oci(corrupt_target=True)
            with redirect_stderr(io.StringIO()):
                self.assertEqual(scan.main(["--diagnostic-file", str(diagnostic), "--archive", str(archive_path),
                                            str(report_path), target_id]), 1)
            self.assertEqual(diagnostic.read_text(), "validation:identity-archive-descriptor\n")

    def test_status_printer_whitelists_diagnostics(self):
        with tempfile.TemporaryDirectory() as root:
            path = Path(root) / "diagnostic"
            for status in ("launcher", "scanner-run", "validation:identity-archive-config-hash",
                           "validation:identity-archive-inspect-id", "validation:identity-archive-descriptor",
                           "validation:identity-report-config",
                           "validation:identity-distro", "validation:remediation"):
                path.write_text(status + "\n")
                result = subprocess.run(["bash", str(STATUS_SCRIPT), str(path)],
                                        capture_output=True, text=True, check=True)
                self.assertEqual(result.stdout,
                                 f"::error::Runtime audit failed ({status}); private output withheld.\n")
            path.write_text("validation:remediation\nPRIVATE_REPORT")
            result = subprocess.run(["bash", str(STATUS_SCRIPT), str(path)],
                                    capture_output=True, text=True, check=True)
            self.assertEqual(result.stdout,
                             "::error::Runtime audit failed (unknown); private output withheld.\n")
            self.assertNotIn("PRIVATE_REPORT", result.stdout + result.stderr)

    def test_scan_records_failed_stage_without_private_command_output(self):
        with tempfile.TemporaryDirectory() as root:
            root = Path(root)
            bin_dir = root / "bin"
            bin_dir.mkdir()
            (bin_dir / "uname").write_text("#!/bin/sh\necho Linux\n")
            (bin_dir / "docker").write_text("#!/bin/sh\necho PRIVATE_REPORT >&2\nexit 4\n")
            for executable in bin_dir.iterdir():
                executable.chmod(0o755)
            diagnostic = root / "diagnostic"
            environment = dict(os.environ, GITHUB_ACTIONS="true", RUNNER_TEMP=str(root),
                               PATH=str(bin_dir) + os.pathsep + os.environ["PATH"])
            result = subprocess.run(["bash", str(SCAN_SCRIPT), "--diagnostic-file", str(diagnostic)],
                                    capture_output=True, text=True, env=environment)
            self.assertNotEqual(result.returncode, 0)
            self.assertEqual(diagnostic.read_text(), "image-inspect\n")
            self.assertIn('docker save --output "$scratch/image.tar" "$(cat "$scratch/image-id")"',
                          SCAN_SCRIPT.read_text())

    def test_ci_keeps_raw_scan_output_in_private_log(self):
        workflow = VALIDATE_WORKFLOW.read_text()
        self.assertIn('--diagnostic-file "$diagnostic_file" >"$private_log" 2>&1', workflow)
        self.assertIn('bash scripts/ci/harbor-core-audit-status.sh "$diagnostic_file"', workflow)
        self.assertIn('trap \'rm -f "$private_log" "$diagnostic_file"\' EXIT', workflow)

    def test_refuses_wrong_or_filtered_or_stale_reports(self):
        changes = [
            lambda r: r["source"].update(type="directory"),
            lambda r: r["source"]["target"].update(imageID="sha256:" + "1" * 64),
            lambda r: r["source"]["target"].update(config=base64.b64encode(b"{}").decode()),
            lambda r: r["source"]["target"].update(layers=[]),
            lambda r: r["source"]["target"].update(architecture="arm64"),
            lambda r: r["distro"].update(name="unknown"),
            lambda r: r["descriptor"].update(version="other"),
            lambda r: r["descriptor"]["db"]["status"].update(valid=False),
            lambda r: r["descriptor"]["db"]["status"].update(built=(datetime.now(timezone.utc) - timedelta(days=3)).isoformat()),
            lambda r: r["descriptor"]["configuration"].update(**{"only-fixed": True}),
            lambda r: r["descriptor"]["configuration"].update(exclude=["fixture"]),
            lambda r: r.update(ignoredMatches=["fixture"]),
        ]
        scan.verify(self.report(), IMAGE)
        for change in changes:
            report = self.report()
            change(report)
            with self.assertRaises(AssertionError):
                scan.verify(report, IMAGE)

    def test_summary_withholds_raw_image_metadata_and_clearance(self):
        report = self.report()
        raw = json.dumps({"os": "linux", "architecture": "amd64", "env": ["PRIVATE_VALUE=fixture-do-not-print"]}).encode()
        image = "sha256:" + hashlib.sha256(raw).hexdigest()
        report["source"]["target"].update(imageID=image, config=base64.b64encode(raw).decode())
        with tempfile.TemporaryDirectory() as root:
            path = Path(root) / "report.json"
            path.write_text(json.dumps(report))
            output = io.StringIO()
            with redirect_stdout(output):
                self.assertEqual(scan.main([str(path), image]), 0)
        text = output.getvalue()
        self.assertNotIn("fixture-do-not-print", text)
        self.assertIn('"cve_clearance": false', text)
        self.assertIn(image, text)


if __name__ == "__main__":
    unittest.main()
