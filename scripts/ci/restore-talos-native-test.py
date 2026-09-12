#!/usr/bin/env python3
"""Exercise real pipe pressure and deadlines without Docker, credentials or a pin."""
import importlib.util
from pathlib import Path
import sys
import unittest

SPEC = importlib.util.spec_from_file_location("native", Path(__file__).with_name("restore-talos-native-check.py"))
NATIVE = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(NATIVE)


class NativeOutputTests(unittest.TestCase):
    def command(self, source):
        return [sys.executable, "-c", source]

    def test_stderr_larger_than_pipe_buffer_does_not_block_stdout(self):
        output = NATIVE.bounded_output(self.command(
            "import os; os.write(2,b'e'*200000); os.write(1,b'fixture passed\\n')"), timeout=5)
        self.assertEqual(output, "fixture passed\n")

    def test_each_stream_is_stopped_before_noisy_child_finishes(self):
        for stream in (1, 2):
            with self.subTest(stream=stream), self.assertRaisesRegex(ValueError, "exceeded"):
                NATIVE.bounded_output(self.command(
                    f"import os,time; os.write({stream},b'x'*200000); time.sleep(30)"), timeout=5, limit=8192)

    def test_combined_stream_limit_is_enforced(self):
        with self.assertRaisesRegex(ValueError, "exceeded"):
            NATIVE.bounded_output(self.command(
                "import os; os.write(1,b'x'*5000); os.write(2,b'e'*5000)"), timeout=5, limit=8192)

    def test_idle_child_times_out(self):
        with self.assertRaises(TimeoutError):
            NATIVE.bounded_output(self.command("import time; time.sleep(30)"), timeout=0.1)

    def test_nonzero_child_is_not_success(self):
        with self.assertRaisesRegex(RuntimeError, "attach failed"):
            NATIVE.bounded_output(self.command("import sys; print('fake success'); sys.exit(1)"), timeout=5)


if __name__ == "__main__":
    unittest.main()
