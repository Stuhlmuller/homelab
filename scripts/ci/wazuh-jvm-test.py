#!/usr/bin/env python3
"""Exercise Wazuh JVM log routing with a local JDK (17 or newer), no cluster.

The fatal-report test deliberately crashes only an isolated, empty Java child.
Its environment is empty and core/heap dumps are disabled for that child.
"""
from pathlib import Path
import shutil
import subprocess
import tempfile
import unittest

ROOT = Path(__file__).resolve().parents[2]
OPTIONS = ROOT / "clusters/homelab/apps/wazuh/jvm.options"
JAVA = shutil.which("java")

PROBE = """
import java.lang.reflect.Field;
import sun.misc.Unsafe;

class LogProbe {
    public static void main(String[] args) throws Exception {
        System.gc();
        if (args.length != 0) {
            Field field = Unsafe.class.getDeclaredField("theUnsafe");
            field.setAccessible(true);
            ((Unsafe) field.get(null)).putAddress(0L, 0L);
        }
        System.out.println("GC_PROBE_COMPLETE");
    }
}
"""


class JvmLogTests(unittest.TestCase):
    def run_probe(self, crash=False):
        self.assertIsNotNone(JAVA, "JDK 17+ must be available on PATH")
        options = [line for line in OPTIONS.read_text().splitlines()
                   if line.startswith("-")]
        with tempfile.TemporaryDirectory(prefix="wazuh-jvm-test-") as directory:
            work = Path(directory)
            source = work / "LogProbe.java"
            source.write_text(PROBE)
            # The pinned image enables these before jvm.options.d overrides.
            packaged = [
                "-XX:+HeapDumpOnOutOfMemoryError",
                "-XX:HeapDumpPath=" + directory,
                "-XX:ErrorFile=" + str(work / "hs_err_pid%p.log"),
                "-Xlog:gc*,gc+age=trace,safepoint:file=" + str(work / "gc.log")
                + ":utctime,pid,tags:filecount=32,filesize=64m",
            ]
            # Bound test resources; never produce a memory/core dump.
            test_options = ["-Xms32m", "-Xmx32m", "-XX:-HeapDumpOnOutOfMemoryError",
                            "-XX:-CreateCoredumpOnCrash"]
            result = subprocess.run(
                [JAVA, *packaged, *options, *test_options, str(source),
                 *(["crash"] if crash else [])],
                cwd=directory, env={}, capture_output=True, text=True, timeout=30,
                check=False,
            )
            self.assertFalse(list(work.glob("*.hprof")))
            self.assertFalse(list(work.glob("hs_err*")), "Fatal report stayed file-only")
            self.assertFalse(list(work.glob("core*")))
            for logfile in work.glob("gc.log*"):
                self.assertEqual(logfile.stat().st_size, 0, "GC still writes packaged log file")
            return result

    def test_gc_and_safepoints_reach_stdout_without_file_duplicates(self):
        result = self.run_probe()
        self.assertEqual(result.returncode, 0, result.stderr[:1000])
        self.assertIn("GC_PROBE_COMPLETE", result.stdout)
        self.assertIn("Pause Full (System.gc())", result.stdout)
        self.assertRegex(result.stdout, r"\[safepoint\s*\]")
        self.assertNotIn("Pause Full (System.gc())", result.stderr)

    def test_complete_fatal_report_reaches_stdout_without_dump_files(self):
        result = self.run_probe(crash=True)
        self.assertNotEqual(result.returncode, 0)
        self.assertEqual(result.stdout.count("A fatal error has been detected"), 1)
        self.assertIn("S U M M A R Y", result.stdout)
        self.assertIn("P R O C E S S", result.stdout)
        self.assertIn("S Y S T E M", result.stdout)
        self.assertNotIn("A fatal error has been detected", result.stderr)
        self.assertNotIn("GC_PROBE_COMPLETE", result.stdout)


if __name__ == "__main__":
    unittest.main()
