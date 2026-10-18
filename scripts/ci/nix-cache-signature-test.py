#!/usr/bin/env python3
"""Verify signed substitution, unknown-key rejection and unsigned rejection."""

import argparse
from pathlib import Path
import subprocess
import tempfile


def run(*args):
    return subprocess.check_output(args, text=True).strip()


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--output", help="Already-built check output; defaults to this platform's manifest check")
    args = parser.parse_args()
    system = run("nix", "eval", "--impure", "--raw", "--expr", "builtins.currentSystem")
    output = args.output or run("nix", "eval", "--raw", f".#checks.{system}.manifest-policy.outPath")
    with tempfile.TemporaryDirectory(prefix="nix-signature-proof-") as temporary:
        root = Path(temporary).resolve()
        key, public_file, cache = root / "signing.key", root / "signing.pub", root / "cache"
        subprocess.run(["nix-store", "--generate-binary-cache-key", "cache-test-1",
                        str(key), str(public_file)], check=True)
        key.chmod(0o600)
        subprocess.run(["nix", "copy", "--to", cache.as_uri(), output], check=True)
        subprocess.run(["nix", "store", "sign", "--store", cache.as_uri(),
                        "--key-file", str(key), output], check=True)
        public = public_file.read_text().strip()

        def copy(label, trusted_key, expected):
            target = "local?root=" + str(root / label)
            result = subprocess.run(["nix", "--store", target, "copy", "--from", cache.as_uri(),
                                     "--option", "require-sigs", "true", "--option",
                                     "trusted-public-keys", trusted_key, output], capture_output=True, text=True)
            if (result.returncode == 0) != expected:
                raise AssertionError(result.stderr or f"Unexpected import result: {label}")
            if not expected and "signature" not in result.stderr.lower():
                raise AssertionError(f"Rejection did not prove signature validation: {result.stderr}")
            print(f"{label}: {'accepted' if expected else 'rejected'}")

        copy("signed", public, True)
        copy("unknown-key", "", False)
        info = next(cache.glob("*.narinfo"))
        info.write_text("\n".join(line for line in info.read_text().splitlines()
                                 if not line.startswith("Sig:")) + "\n")
        copy("unsigned", public, False)


if __name__ == "__main__":
    main()
