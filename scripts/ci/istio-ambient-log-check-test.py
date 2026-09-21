#!/usr/bin/env python3
"""Exercise the ambient log gate's time window and fail-closed CLI contract."""

import gzip
import os
from pathlib import Path
import subprocess
import sys
import tempfile
import unittest


CHECKER = Path(__file__).resolve().parents[1] / "istio-ambient-log-check.py"
WINDOW_END = "2026-09-06T12:00:00Z"
CURRENT = "2026-09-06T06:00:00Z"
PRIVATE_MESSAGE = "private-log-content-sentinel"
PRIVATE_FILENAME = "private-pod-name-sentinel"
SIGNATURES = (
    "Readiness probe returned HTTP 500",
    "READINESS check FAILED",
    "HTTP 500 during readiness check",
    "bind [::1]:15053: cannot assign requested address",
    "route ::/0 unavailable",
    "IPv6 bind failure",
    "IPV6 route ERROR",
)


class AmbientLogCheck(unittest.TestCase):
    def setUp(self):
        self.temporary = tempfile.TemporaryDirectory()
        self.addCleanup(self.temporary.cleanup)
        self.directory = Path(self.temporary.name) / "private-capture-sentinel"
        self.directory.mkdir()

    def write_log(self, text, name=PRIVATE_FILENAME + ".current.log"):
        path = self.directory / name
        path.write_text(text, encoding="utf-8")
        return path

    def run_check(self, expected, window_end=WINDOW_END, directory=None):
        result = subprocess.run(
            [sys.executable, str(CHECKER), "--window-end", window_end,
             str(self.directory if directory is None else directory)],
            capture_output=True,
            text=True,
            timeout=10,
            check=False,
        )
        output = result.stdout + result.stderr
        for private in (PRIVATE_MESSAGE, PRIVATE_FILENAME, str(self.directory)):
            self.assertNotIn(private, output)
        self.assertEqual(result.returncode, expected, output)
        return result

    def test_clean_kubectl_and_cri_logs(self):
        self.write_log(
            f"{CURRENT} info CNI configuration loaded {PRIVATE_MESSAGE}\n"
            f"{CURRENT} stdout F info proxy ready {PRIVATE_MESSAGE}\n"
            f"{CURRENT} stderr F status ready {PRIVATE_MESSAGE}\n"
            f"{CURRENT} readiness returned HTTP 200; IPv6 disabled\n"
            f"{CURRENT} unrelated HTTP 500 response\n"
        )
        self.run_check(0)

    def test_each_current_signature_fails_in_both_log_formats(self):
        for signature in SIGNATURES:
            for framing in ("", "stdout F ", "stderr F "):
                with self.subTest(signature=signature, framing=framing):
                    self.write_log(f"{CURRENT} {framing}{signature} {PRIVATE_MESSAGE}\n")
                    self.run_check(1)

    def test_historical_and_future_signatures_are_excluded(self):
        self.write_log(
            f"2026-09-01T00:00:00Z stderr F readiness failed {PRIVATE_MESSAGE}\n"
            f"2026-09-05T11:59:59.999999999Z IPv6 error {PRIVATE_MESSAGE}\n"
            f"{CURRENT} info healthy {PRIVATE_MESSAGE}\n"
            f"2026-09-06T12:00:00.000000001Z readiness failed {PRIVATE_MESSAGE}\n"
            f"2026-09-07T00:00:00Z stdout F route ::/0 {PRIVATE_MESSAGE}\n"
        )
        self.run_check(0)

    def test_integral_window_boundaries_are_nanosecond_accurate(self):
        cases = (
            ("2026-09-05T11:59:59.999999999Z", 0),
            ("2026-09-05T12:00:00Z", 0),
            ("2026-09-05T12:00:00.000000000Z", 0),
            ("2026-09-05T12:00:00.000000001Z", 1),
            ("2026-09-06T11:59:59.999999999Z", 1),
            ("2026-09-06T12:00:00Z", 1),
            ("2026-09-06T12:00:00.000000000Z", 1),
            ("2026-09-06T12:00:00.000000001Z", 0),
        )
        for timestamp, expected in cases:
            with self.subTest(timestamp=timestamp):
                self.write_log(f"{timestamp} readiness failed {PRIVATE_MESSAGE}\n")
                self.run_check(expected)

    def test_fractional_window_boundaries_are_nanosecond_accurate(self):
        cases = (
            ("2026-09-05T12:00:00.123456788Z", 0),
            ("2026-09-05T12:00:00.123456789Z", 0),
            ("2026-09-05T12:00:00.123456790Z", 1),
            ("2026-09-06T12:00:00.123456788Z", 1),
            ("2026-09-06T12:00:00.123456789Z", 1),
            ("2026-09-06T12:00:00.123456790Z", 0),
        )
        for timestamp, expected in cases:
            with self.subTest(timestamp=timestamp):
                self.write_log(f"{timestamp} stdout F IPv6 error {PRIVATE_MESSAGE}\n")
                self.run_check(expected, window_end="2026-09-06T12:00:00.123456789Z")

    def test_all_supported_fraction_lengths(self):
        for precision in range(1, 10):
            with self.subTest(precision=precision):
                fraction = "123456789"[:precision]
                self.write_log(f"2026-09-06T06:00:00.{fraction}Z readiness failed\n")
                self.run_check(1, window_end=f"2026-09-06T12:00:00.{fraction}Z")

    def test_equivalent_fraction_precisions_have_identical_boundaries(self):
        for timestamp_fraction, end_fraction in (("1", "100000000"), ("100000000", "1")):
            for day, expected in (("05", 0), ("06", 1)):
                with self.subTest(timestamp_fraction=timestamp_fraction, day=day):
                    self.write_log(
                        f"2026-09-{day}T12:00:00.{timestamp_fraction}Z readiness failed\n"
                    )
                    self.run_check(
                        expected,
                        window_end=f"2026-09-06T12:00:00.{end_fraction}Z",
                    )

    def test_all_files_are_scanned_regardless_of_extension_or_order(self):
        self.write_log(f"{CURRENT} info healthy {PRIVATE_MESSAGE}\n", "a.current.log")
        self.write_log(
            "2026-09-07T00:00:00Z info future\n"
            f"{CURRENT} stderr F readiness failed {PRIVATE_MESSAGE}\n"
            "2026-09-01T00:00:00Z info historical\n",
            PRIVATE_FILENAME + ".rotation",
        )
        self.run_check(1)

    def test_timestamped_final_line_without_newline(self):
        self.write_log(f"{CURRENT} info healthy {PRIVATE_MESSAGE}")
        self.run_check(0)

    def test_timestamped_empty_messages_are_valid(self):
        for message in ("", "stdout F ", "stderr F "):
            with self.subTest(message=message):
                self.write_log(f"{CURRENT} {message}\n")
                self.run_check(0)

    def test_capture_files_remain_unchanged(self):
        self.write_log(f"{CURRENT} readiness failed {PRIVATE_MESSAGE}\n")
        self.write_log("2026-09-01T00:00:00Z info healthy\n", "rotation.log")
        before = {path.name: path.read_bytes() for path in self.directory.iterdir()}
        self.run_check(1)
        after = {path.name: path.read_bytes() for path in self.directory.iterdir()}
        self.assertEqual(after, before)

    def test_malformed_lines_are_invalid_even_after_historical_records(self):
        bad_lines = (
            f"{PRIVATE_MESSAGE}\n",
            "\n",
            f"2026-09-01T00:00:00 {PRIVATE_MESSAGE}\n",
            f"2026-09-01T00:00:00+00:00 {PRIVATE_MESSAGE}\n",
            f"2026-09-01T00:00:00.Z {PRIVATE_MESSAGE}\n",
            f"2026-09-01T00:00:00.1234567890Z {PRIVATE_MESSAGE}\n",
            f"2026-09-01T00:00:00z {PRIVATE_MESSAGE}\n",
            f"2026-02-30T00:00:00Z {PRIVATE_MESSAGE}\n",
            f"2026-13-01T00:00:00Z {PRIVATE_MESSAGE}\n",
            f"2026-09-01T24:00:00Z {PRIVATE_MESSAGE}\n",
            f"2026-09-01T00:60:00Z {PRIVATE_MESSAGE}\n",
            f"{CURRENT}\n",
        )
        for bad_line in bad_lines:
            with self.subTest(bad_line=bad_line):
                self.write_log(
                    "2026-09-01T00:00:00Z info historical\n" + bad_line
                    + f"{CURRENT} info healthy\n"
                )
                self.run_check(2)

    def test_partial_or_malformed_cri_records_are_invalid(self):
        messages = (
            f"stdout P readiness fai {PRIVATE_MESSAGE}",
            f"stderr P info healthy {PRIVATE_MESSAGE}",
            f"stdout X readiness failed {PRIVATE_MESSAGE}",
            f"stderr {PRIVATE_MESSAGE}",
            "stdout F",
            "stderr F",
        )
        for timestamp in ("2026-09-01T00:00:00Z", CURRENT):
            for message in messages:
                with self.subTest(timestamp=timestamp, message=message):
                    self.write_log(f"{timestamp} {message}\n")
                    self.run_check(2)

    def test_invalid_window_end_is_private_input_error(self):
        self.write_log(f"{CURRENT} info healthy\n")
        for window_end in (
            PRIVATE_MESSAGE,
            "2026-09-06T12:00:00",
            "2026-09-06T12:00:00+00:00",
            "2026-09-06T12:00:00.1234567890Z",
            "2026-02-30T12:00:00Z",
        ):
            with self.subTest(window_end=window_end):
                self.run_check(2, window_end=window_end)

    def test_empty_inventory_is_invalid(self):
        self.run_check(2)

    def test_empty_file_is_invalid(self):
        self.write_log("")
        self.run_check(2)

    def test_invalid_utf8_is_invalid(self):
        path = self.write_log(f"{CURRENT} info healthy\n")
        with path.open("ab") as stream:
            stream.write(f"{CURRENT} {PRIVATE_MESSAGE} ".encode() + b"\xff\n")
        self.run_check(2)

    def test_invalid_record_takes_precedence_over_signature(self):
        self.write_log(
            f"{CURRENT} readiness failed {PRIVATE_MESSAGE}\n"
            f"{PRIVATE_MESSAGE} missing timestamp\n"
        )
        self.run_check(2)

    def test_invalid_file_takes_precedence_over_clean_or_failing_file(self):
        for message in ("info healthy", "readiness failed"):
            for invalid_name in ("a.invalid.log", "z.invalid.log"):
                with self.subTest(message=message, invalid_name=invalid_name):
                    self.write_log(f"{CURRENT} {message} {PRIVATE_MESSAGE}\n")
                    invalid = self.write_log("", invalid_name)
                    try:
                        self.run_check(2)
                    finally:
                        invalid.unlink()

    def test_nested_directory_is_invalid(self):
        self.write_log(f"{CURRENT} info healthy\n")
        (self.directory / PRIVATE_FILENAME).mkdir()
        self.run_check(2)

    def test_symlink_and_broken_symlink_are_invalid(self):
        target = self.write_log(f"{CURRENT} info healthy\n")
        link = self.directory / "linked.log"
        for destination in (target, self.directory / "missing.log"):
            with self.subTest(destination=destination.name):
                link.symlink_to(destination)
                try:
                    self.run_check(2)
                finally:
                    link.unlink()

    @unittest.skipUnless(hasattr(os, "mkfifo"), "FIFO support required")
    def test_nonregular_file_is_rejected_without_opening_it(self):
        self.write_log(f"{CURRENT} info healthy\n")
        os.mkfifo(self.directory / PRIVATE_FILENAME)
        self.run_check(2)

    def test_missing_or_nondirectory_capture_is_invalid(self):
        self.run_check(2, directory=self.directory / PRIVATE_FILENAME)
        file_path = self.write_log(f"{CURRENT} info healthy\n")
        self.run_check(2, directory=file_path)
        link = Path(self.temporary.name) / PRIVATE_FILENAME
        link.symlink_to(self.directory, target_is_directory=True)
        self.run_check(2, directory=link)

    def test_compressed_inputs_are_invalid(self):
        clean = f"{CURRENT} info healthy {PRIVATE_MESSAGE}\n"
        for name, content in (
            (PRIVATE_FILENAME + ".gz", clean.encode()),
            (PRIVATE_FILENAME + ".log", gzip.compress(clean.encode())),
        ):
            with self.subTest(name=name):
                path = self.directory / name
                path.write_bytes(content)
                try:
                    self.run_check(2)
                finally:
                    path.unlink()


if __name__ == "__main__":
    unittest.main()
