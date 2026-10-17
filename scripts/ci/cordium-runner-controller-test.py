#!/usr/bin/env python3
"""Verify projected-secret copying preserves private guards and detects bad input."""
import importlib.util
import subprocess
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch

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



class Revision(unittest.TestCase):
    def test_shallow_image_accepts_deployment_commit_but_rejects_code_drift_and_rewritten_main(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            origin, image, mirror = root / "origin", root / "image", root / "source.git"
            def git(*args):
                result = subprocess.run(["git", *map(str, args)], capture_output=True, check=True)
                return result.stdout.decode().strip()
            def commit(message):
                git("-C", origin, "add", ".")
                # Unsigned synthetic history is intentional; it never leaves this fixture.
                git("-C", origin, "-c", "user.name=Fixture", "-c", "user.email=fixture@example.invalid",
                    "-c", "commit.gpgsign=false", "commit", "-m", message)
                return git("-C", origin, "rev-parse", "HEAD")
            git("init", "--initial-branch=main", origin)
            (origin / "scripts").mkdir()
            executable = origin / "scripts/cordium-runner.py"
            executable.write_text("reviewed runner fixture\n")
            source = commit("fixture image source")
            git("clone", "--depth=1", origin.as_uri(), image)
            (origin / "deployment.yaml").write_text("fixture deployment\n")
            deployment = commit("fixture image consumer")
            def command(*args):
                arguments = [origin.as_uri() if str(item) == controller.REPOSITORY else str(item) for item in args]
                result = subprocess.run(arguments, capture_output=True)
                if result.returncode:
                    raise RuntimeError("Fixture git boundary failed")
                return result.stdout
            with patch.object(controller, "ROOT", image), patch.object(controller.runner.github_operator, "command", side_effect=command):
                self.assertEqual(controller.reviewed_controller_main(source, mirror), deployment)
                executable.write_text("changed runner fixture\n")
                commit("fixture unrefreshed executable")
                with self.assertRaises(RuntimeError):
                    controller.reviewed_controller_main(source, mirror)
                executable.write_text("reviewed runner fixture\n")
                restored = commit("fixture restored executable")
                self.assertEqual(controller.reviewed_controller_main(source, mirror), restored)
                git("-C", origin, "checkout", "--orphan", "rewritten")
                commit("fixture rewritten history")
                git("-C", origin, "branch", "-M", "main")
                with self.assertRaises(RuntimeError):
                    controller.reviewed_controller_main(source, mirror)
                (image / "unreviewed").write_text("dirty fixture")
                with self.assertRaises(RuntimeError):
                    controller.reviewed_controller_main(source, mirror)


if __name__ == "__main__":
    unittest.main()
