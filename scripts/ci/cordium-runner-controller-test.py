#!/usr/bin/env python3
"""Verify projected-secret copying preserves private guards and detects bad input."""
import importlib.util
from pathlib import Path
import tempfile
import unittest

spec = importlib.util.spec_from_file_location("controller", Path(__file__).resolve().parents[1] / "cordium-runner-controller.py")
controller = importlib.util.module_from_spec(spec)
spec.loader.exec_module(controller)


class Projection(unittest.TestCase):
    def test_group_readable_projection_becomes_private_and_rotation_replaces(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            source, target = root / "source", root / "private"
            source.mkdir()
            for key in controller.KEYS:
                path = source / key
                path.write_bytes(b"private-fixture")
                path.chmod(0o440)
            controller.private_copies(source, target)
            self.assertEqual(target.stat().st_mode & 0o777, 0o700)
            for key in controller.KEYS:
                self.assertEqual((target / key).stat().st_mode & 0o777, 0o400)
            (source / "auth-token").unlink()
            (source / "auth-token").write_bytes(b"rotated-fixture")
            (source / "auth-token").chmod(0o440)
            controller.private_copies(source, target)
            self.assertEqual((target / "auth-token").read_bytes(), b"rotated-fixture")
            self.assertEqual(list(target.glob(".credential-*")), [])

    def test_bad_second_key_does_not_replace_first(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            source, target = root / "source", root / "private"
            source.mkdir()
            for key in controller.KEYS:
                path = source / key
                path.write_bytes(b"original-fixture")
                path.chmod(0o440)
            controller.private_copies(source, target)
            for key, value in zip(controller.KEYS, (b"new-fixture", b""), strict=True):
                (source / key).unlink()
                (source / key).write_bytes(value)
                (source / key).chmod(0o440)
            with self.assertRaises(RuntimeError):
                controller.private_copies(source, target)
            self.assertEqual((target / controller.KEYS[0]).read_bytes(), b"original-fixture")

    def test_world_readable_projection_is_rejected(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            source = root / "source"
            source.mkdir()
            for key in controller.KEYS:
                (source / key).write_bytes(b"fixture")
                (source / key).chmod(0o444)
            with self.assertRaises(RuntimeError):
                controller.private_copies(source, root / "private")


if __name__ == "__main__":
    unittest.main()
