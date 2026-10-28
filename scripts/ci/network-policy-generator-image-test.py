#!/usr/bin/env python3
"""Check fixed source, runtime, and credential boundaries for patched images."""

import hashlib
import json
from pathlib import Path
import unittest


ROOT = Path(__file__).resolve().parents[2]
BUILD = ROOT / "builds/network-policy-generators"


class GeneratorImageContract(unittest.TestCase):
    def test_source_and_runtime_are_immutable_and_licenses_exist(self):
        spec = json.loads((BUILD / "source.json").read_text())
        catalog = json.loads((ROOT / "scripts/config/harbor-images.json").read_text())
        catalog_refs = {entry["source"] for entry in catalog["images"]}
        self.assertEqual(spec["goToolchain"], "go1.25.8")
        for name in ("cordium", "octelium"):
            source = spec[name]
            self.assertRegex(source["revision"], r"^[0-9a-f]{40}$")
            self.assertRegex(source["tag"], r"^v[0-9]+\.[0-9]+\.[0-9]+$")
            self.assertEqual(hashlib.sha256((BUILD / source["patch"]).read_bytes()).hexdigest(),
                             source["patchSha256"])
        for name in ("cordiumGenesis", "octeliumGenesis"):
            self.assertIn(spec["runtimeBaseImages"][name], catalog_refs)
        for image in spec["runtimeBaseImages"].values():
            self.assertRegex(image, r"^ghcr\.io/octelium/[a-z-]+:[0-9]+\.[0-9]+\.[0-9]+@sha256:[0-9a-f]{64}$")

    def test_base_runtime_is_inherited_and_compared_before_publish(self):
        dockerfile = (BUILD / "runtime.Dockerfile").read_text()
        self.assertIn("FROM ${BASE_IMAGE}", dockerfile)
        self.assertNotRegex(dockerfile, r"(?m)^(?:RUN|USER|ENTRYPOINT|ENV|CMD) ")
        build = (BUILD / "build.sh").read_text()
        self.assertIn('[[ "$built_config" == "$base_config" ]]', build)
        self.assertIn('ImageRegistry=ghcr.io', build)
        self.assertIn('ImageRegistryPrefix=octelium', build)
        self.assertIn('image-ref-probe.go', build)
        for tool in ("helm", "bash", "curl", "openssl"):
            self.assertIn(f"command -v {tool}", build)
        self.assertIn('test "$OCTELIUM_CONTAINER_MODE" = true', build)
        workflow = (ROOT / ".github/workflows/policy-generator-images.yml").read_text()
        self.assertLess(workflow.index("Build Pinned Patched Sources Before Credentials"),
                        workflow.index("Configure AWS Credentials"))
        self.assertLess(workflow.index("Verify Current Main Commit Before Credentials"),
                        workflow.index("Configure AWS Credentials"))
        self.assertIn("publish-policy-generators", workflow)


if __name__ == "__main__":
    unittest.main()
