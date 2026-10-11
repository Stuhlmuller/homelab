#!/usr/bin/env python3
"""Exercise the candidate against disposable upstream Harbor services."""
import base64
import gzip
import hashlib
import io
import json
import os
from pathlib import Path
import re
import secrets
import subprocess
import sys
import tarfile
import tempfile
import time
import urllib.error
import urllib.parse
import urllib.request


IMAGES = {
    "prepare": "sha256:79b5614d0d02b5d2c6c9b7b9755f5caaea882797353bfcb6421f77e6d69cc317",
    "harbor-db": "sha256:a32d51e636d76303e086a7c5251a2c8415c6f165b2f87bafa914efd866c5403f",
    "registry-photon": "sha256:dc0cb388a6445c69c8a0c406679290d2991c9698833d9e6e86a23bdfaf2f83c3",
    "harbor-registryctl": "sha256:30bd1ace4e3bb390d75b84673f98ddb4a69fcc6d116932ea764391df01943fb7",
    "harbor-portal": "sha256:01edf478505b21dba23a83c095f6ecac0c1e705690093edbab41e9a4d6754a75",
    "harbor-jobservice": "sha256:f143578ef30e2be5c48873298257ed0fca31545025958c534e536a06765d2b82",
    "valkey-photon": "sha256:bb022e8f236f56f53cee7bb1f609595e497da67d829048e0af2284f97e6eb54f",
    "nginx-photon": "sha256:7eff0287d5ad0f35754e162c8481ced04bbde107153ce586cefb15ee74fa1311",
}
BASE = "http://127.0.0.1:18085"
OCI = "application/vnd.oci.image."


def image(name):
    return f"docker.io/goharbor/{name}:v2.15.4@{IMAGES[name]}"


def command(*args):
    return subprocess.check_output(args, text=True)


def encoded(value):
    return json.dumps(value, separators=(",", ":"), ensure_ascii=False).encode()


def digest(data):
    return "sha256:" + hashlib.sha256(data).hexdigest()


def request(method, path, data=None, **headers):
    url = urllib.parse.urljoin(BASE, path)
    # Registry upload locations must remain on the disposable loopback endpoint.
    assert urllib.parse.urlsplit(url).netloc == "127.0.0.1:18085", url
    with urllib.request.urlopen(urllib.request.Request(
            url, data=data, headers=headers, method=method), timeout=15) as response:
        return response.read(), response.headers


def fixture_payloads():
    raw_layer = io.BytesIO()
    with tarfile.open(fileobj=raw_layer, mode="w"):
        pass
    layer = gzip.compress(raw_layer.getvalue(), mtime=0)
    config = encoded({"architecture": "amd64", "os": "linux", "config": {},
                      "rootfs": {"type": "layers", "diff_ids": [digest(raw_layer.getvalue())]}})
    child = encoded({"schemaVersion": 2, "mediaType": OCI + "manifest.v1+json",
                     "config": {"mediaType": OCI + "config.v1+json", "digest": digest(config), "size": len(config)},
                     "layers": [{"mediaType": OCI + "layer.v1.tar+gzip", "digest": digest(layer), "size": len(layer)}]})
    descriptor = {"mediaType": OCI + "manifest.v1+json", "digest": digest(child), "size": len(child),
                  "platform": {"architecture": "amd64", "os": "linux"},
                  "annotations": {"org.opencontainers.image.title": "repeated-λ"}}
    index = encoded({"schemaVersion": 2, "mediaType": OCI + "index.v1+json", "manifests": [descriptor] * 8})
    return config, layer, child, index


def fixture_config(template, work, password):
    config, count = re.subn(r"^https:\n(?:[ \t].*\n|\n)*", "", template, flags=re.MULTILINE)
    assert count == 1
    for old, new in (("hostname: reg.mydomain.com", "hostname: harbor-fixture.invalid\nexternal_url: " + BASE),
                     ("  port: 80", "  port: 18085"),
                     ("harbor_admin_password: Harbor12345", "harbor_admin_password: " + password),
                     ("data_volume: /data", "data_volume: " + str(work / "data")),
                     ("    location: /var/log/harbor", "    location: " + str(work / "logs"))):
        assert config.count(old) == 1, old
        config = config.replace(old, new)
    return config


def acceptance(compose, password):
    for _ in range(120):
        try:
            request("GET", "/api/v2.0/ping")
            break
        except (OSError, urllib.error.URLError):
            time.sleep(2)
    else:
        raise RuntimeError("disposable Harbor did not become ready")
    basic = "Basic " + base64.b64encode(f"admin:{password}".encode()).decode()
    token, _ = request("GET", "/service/token?service=harbor-registry&scope=repository:library/repeated:pull,push",
                       Authorization=basic)
    auth = {"Authorization": "Bearer " + json.loads(token)["token"]}
    config, layer, child, index = fixture_payloads()
    for blob in (config, layer):
        _, headers = request("POST", "/v2/library/repeated/blobs/uploads/", b"", **auth)
        location = headers["Location"]
        separator = "&" if "?" in location else "?"
        request("PUT", location + separator + urllib.parse.urlencode({"digest": digest(blob)}), blob,
                **auth, **{"Content-Type": "application/octet-stream"})
    for reference, manifest, media in ((digest(child), child, "manifest"), ("repeated", index, "index")):
        request("PUT", "/v2/library/repeated/manifests/" + reference, manifest,
                **auth, **{"Content-Type": OCI + media + ".v1+json"})
    for reference, expected, media in ((digest(index), index, "index"), (digest(child), child, "manifest")):
        pulled, headers = request("GET", "/v2/library/repeated/manifests/" + reference,
                                  **auth, Accept=OCI + media + ".v1+json")
        assert pulled == expected and headers["Docker-Content-Digest"] == digest(expected)
    for blob in (config, layer):
        pulled, _ = request("GET", "/v2/library/repeated/blobs/" + digest(blob), **auth)
        assert pulled == blob
    sql = ("SELECT count(*) FROM artifact_reference r JOIN artifact a ON a.id=r.parent_id "
           f"WHERE a.digest='{digest(index)}';")
    count = command(*compose, "exec", "-T", "postgresql", "psql", "-U", "postgres", "-d", "registry", "-Atc", sql)
    assert count.strip() == "1", count
    print(f"Registry acceptance passed: eight unchanged descriptors, one PostgreSQL relation, {digest(index)}")


def main():
    assert len(sys.argv) == 2, "Usage: registry-test.py prepared-source-context"
    source = Path(sys.argv[1]) / "upstream/make/harbor.yml.tmpl"
    work = Path(tempfile.mkdtemp(prefix="harbor-index-fixture-"))
    project = "harbor-index-" + secrets.token_hex(6)
    compose = ["docker", "compose", "--project-name", project, "--project-directory", str(work),
               "--file", str(work / "fixture.json")]
    prepare = image("prepare")
    try:
        for directory in ("input", "common/config", "data", "logs"):
            (work / directory).mkdir(parents=True, exist_ok=True)
        password = secrets.token_urlsafe(24)
        config = fixture_config(source.read_text(), work, password)
        (work / "input/harbor.yml").write_text(config)
        command("docker", "run", "--rm", "--network=none",
                "--mount", f"type=bind,src={work / 'input'},dst=/input,readonly",
                "--mount", f"type=bind,src={work / 'data'},dst=/data",
                "--mount", f"type=bind,src={work},dst=/compose_location",
                "--mount", f"type=bind,src={work / 'common/config'},dst=/config",
                "--mount", f"type=bind,src={work},dst=/hostfs{work}", prepare, "prepare")
        # Compose reads root-owned env files on the host; retain all runtime file owners.
        command("docker", "run", "--rm", "--network=none", "--entrypoint", "python3",
                "--mount", f"type=bind,src={work / 'common/config'},dst=/config", prepare, "-c",
                "import os,pathlib,sys; [os.chown(p,int(sys.argv[1]),int(sys.argv[2])) for p in pathlib.Path('/config').rglob('env')]",
                str(os.getuid()), str(os.getgid()))
        generated = json.loads(command("docker", "compose", "--project-directory", str(work),
                                       "--file", str(work / "docker-compose.yml"), "config", "--format", "json"))
        del generated["services"]["log"]
        for name, service in generated["services"].items():
            service.pop("container_name", None)
            service.pop("logging", None)
            service["restart"] = "no"
            service.pop("ports", None)
            service.get("depends_on", {}).pop("log", None)
            if name == "core":
                service["image"] = "homelab-harbor-core:build"
                service["pull_policy"] = "never"
            else:
                component = service["image"].split("/")[-1].split(":")[0]
                service["image"] = image(component)
        generated["services"]["proxy"]["ports"] = [{"target": 8080, "published": "18085", "host_ip": "127.0.0.1"}]
        for network in generated["networks"].values():
            network["internal"] = True
        (work / "fixture.json").write_text(json.dumps(generated))
        command(*compose, "pull")
        command(*compose, "up", "--detach")
        acceptance(compose, password)
    except Exception:
        if (work / "fixture.json").exists():
            print(command(*compose, "logs", "--no-color", "--tail", "100"), file=sys.stderr)
        raise
    finally:
        if (work / "fixture.json").exists():
            command(*compose, "down", "--volumes", "--remove-orphans")
        # Upstream prepare assigns service UIDs; clean only this owned fixture mount.
        command("docker", "run", "--rm", "--network=none", "--entrypoint", "python3",
                "--mount", f"type=bind,src={work},dst=/fixture", prepare, "-c",
                "import pathlib,shutil; [shutil.rmtree(p) if p.is_dir() else p.unlink() for p in pathlib.Path('/fixture').iterdir()]")
        work.rmdir()


if __name__ == "__main__":
    main()
