#!/usr/bin/env python3
"""Run the exact synthetic fixture script on a local tested image; Docker proof only."""
import importlib.util
import json
import os
from pathlib import Path
import re
import select
import subprocess
import sys
import tempfile
import time
import uuid

ROOT = Path(__file__).resolve().parents[2]
LABEL = "homelab.restore-native-fixture"


def bounded_output(command, timeout=600, limit=2 * 1024 * 1024):
    """Drain both attach pipes; reject excess bytes before they accumulate."""
    process = subprocess.Popen(command, stdin=subprocess.DEVNULL,
                               stdout=subprocess.PIPE, stderr=subprocess.PIPE)
    streams = [process.stdout, process.stderr]
    output, errors = bytearray(), bytearray()
    total = 0
    deadline = time.monotonic() + timeout
    try:
        while streams:
            remaining = deadline - time.monotonic()
            if remaining <= 0:
                raise TimeoutError("Native fixture output timed out")
            readable = select.select(streams, [], [], remaining)[0]
            if not readable:
                raise TimeoutError("Native fixture output timed out")
            for stream in readable:
                chunk = os.read(stream.fileno(), 65536)
                if not chunk:
                    streams.remove(stream)
                    continue
                total += len(chunk)
                if total > limit:
                    raise ValueError("Native fixture output exceeded its bound")
                if stream is process.stdout:
                    output.extend(chunk)
                else:
                    errors.extend(chunk[:max(0, 512 - len(errors))])
        if process.wait(timeout=max(0.001, deadline - time.monotonic())):
            raise RuntimeError("Native fixture attach failed")
        return output.decode("utf-8")
    except (OSError, ValueError, RuntimeError, subprocess.SubprocessError) as error:
        error.add_note(f"Synthetic fixture stderr (first 512 bytes): {errors.decode('utf-8', errors='replace')!r}")
        raise
    finally:
        if process.poll() is None:
            process.kill()
            process.wait(timeout=5)
        process.stdout.close()
        process.stderr.close()


def load(name, filename):
    spec = importlib.util.spec_from_file_location(name, ROOT / "scripts/ci" / filename)
    module = importlib.util.module_from_spec(spec)
    sys.modules[name] = module
    spec.loader.exec_module(module)
    return module


def inspect_owned(reference, name, nonce):
    result = subprocess.run(["docker", "container", "inspect", reference], check=False,
                            text=True, capture_output=True, timeout=30)
    if result.returncode:
        if result.returncode == 1 and result.stderr.strip() == f"Error: No such container: {reference}":
            return None
        raise RuntimeError("Native fixture container lookup failed; absence is unproved")
    info = json.loads(result.stdout)
    if (len(info) != 1 or not re.fullmatch(r"[0-9a-f]{64}", info[0].get("Id", ""))
            or info[0].get("Name") != "/" + name
            or info[0].get("Config", {}).get("Labels", {}).get(LABEL) != nonce):
        raise RuntimeError("Native fixture container ownership mismatch")
    return info[0]


def run_fixture(image_id, boundary):
    if not re.fullmatch(r"sha256:[0-9a-f]{64}", image_id):
        raise RuntimeError("Native fixtures require the already tested immutable image ID")
    talos = load("restore_talos_fixture_source", "restore-talos-synthetic.py")
    files = talos.fixture_files()
    nonce = uuid.uuid4().hex
    name = "restore-talos-native-" + nonce
    with tempfile.TemporaryDirectory(prefix="restore-talos-native-") as directory:
        scratch = Path(directory)
        scratch.chmod(0o755)  # Only public synthetic code/binaries are mounted.
        for filename, data in files.items():
            target = scratch / filename
            target.write_bytes(data)
            target.chmod(0o555)
        # Keep the established Docker profile and 128Mi tmpfs. Actual Talos disk
        # emptyDir, placement, admission, CRI identity and cleanup are separate gates.
        command = boundary.runtime_options()
        command[1] = "create"
        reference = name
        try:
            created = boundary.run(*command, "--name", name, "--label", f"{LABEL}={nonce}",
                                   "--mount", f"type=bind,src={scratch},dst=/tests,readonly",
                                   "--entrypoint", boundary.LAUNCHER, image_id,
                                   "/bin/sh", "/tests/talos.sh", capture_output=True).stdout.strip()
            if not re.fullmatch(r"[0-9a-f]{64}", created):
                raise RuntimeError("Docker did not return an exact fixture container ID")
            reference = created
            info = inspect_owned(reference, name, nonce)
            if info is None or info["Image"] != image_id:
                raise RuntimeError("Native fixture image identity mismatch")
            output = bounded_output(["docker", "start", "--attach", reference])
            info = inspect_owned(reference, name, nonce)
            if info is None or info["State"].get("Running") or info["State"].get("ExitCode") != 0:
                raise RuntimeError("Native fixture container did not exit successfully")
            profiles = [json.loads(line.removeprefix("RESTORE_PROFILE ")) for line in output.splitlines()
                        if line.startswith("RESTORE_PROFILE ")]
            expected = {"uid": 65534, "gid": 65534, "capabilities": 0, "no_new_privs": 1, "seccomp": 2}
            if (len(profiles) != 1 or set(profiles[0]) != {*expected, "filters"}
                    or any(type(profiles[0][key]) is not int or profiles[0][key] != value
                           for key, value in expected.items())
                    or type(profiles[0]["filters"]) is not int or profiles[0]["filters"] < 2
                    or output.splitlines().count("RESTORE_TALOS_SYNTHETIC_PASSED") != 1):
                raise RuntimeError("Native fixture receipt is missing or invalid")
            print("Synthetic Talos fixture script passed on Docker: process profile, inherited denial, "
                  "in-filter startup failures and PostgreSQL restore; actual Talos remains unverified", flush=True)
        finally:
            # A timed-out create may still have succeeded. Reconcile only this
            # invocation's unpredictable name and label, then remove its exact ID
            # and anonymous image-declared volumes. Never use a broad selector.
            info = inspect_owned(reference, name, nonce)
            if info is not None:
                boundary.run("docker", "rm", "--force", "--volumes", info["Id"], capture_output=True)


def main():
    boundary = load("restore_native_boundary", "restore-egress-check.py")
    with boundary.verified_image() as image:
        run_fixture(image.image_id, boundary)


if __name__ == "__main__":
    main()
