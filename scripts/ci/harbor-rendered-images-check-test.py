#!/usr/bin/env python3
"""Catch a non-Harbor image in a rendered Argo Kustomize source."""

import importlib.util
from pathlib import Path
import tempfile


spec = importlib.util.spec_from_file_location("rendered_images", Path(__file__).with_name("harbor-rendered-images-check.py"))
check = importlib.util.module_from_spec(spec)
spec.loader.exec_module(check)

with tempfile.TemporaryDirectory() as directory:
    root = Path(directory)
    app = root / "clusters/homelab/apps/fixture"
    app.mkdir(parents=True)
    (app / "kustomization.yaml").write_text("apiVersion: kustomize.config.k8s.io/v1beta1\n"
                                             "kind: Kustomization\nresources: [pod.yaml]\n")
    (app / "pod.yaml").write_text("apiVersion: v1\nkind: Pod\nmetadata:\n  name: fixture\n"
                                   "spec:\n  containers:\n    - name: app\n      image: docker.io/library/busybox:1.37\n")
    images = list(check.kustomize_images(root))
    assert images == [(Path("clusters/homelab/apps/fixture/kustomization.yaml"),
                       "docker.io/library/busybox:1.37")], images
    assert not check.pinned(images[0][1])
    assert check.pinned("harbor.stinkyboi.com/mirror/docker.io/library/busybox@sha256:" + "a" * 64)
