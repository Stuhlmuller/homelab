#!/usr/bin/env python3
"""Offline review-gate regression using synthetic disposable Git repositories."""
import json
import os
from pathlib import Path
import shutil
import subprocess
import sys
import tempfile

wrapper = Path(sys.argv[1]).resolve() if len(sys.argv) > 1 else Path(__file__).with_name("nofx-credential-check.sh")
real_git = shutil.which("git")
assert real_git, "git required"
with tempfile.TemporaryDirectory(prefix="nofx-credential-guard-") as temporary:
    base = Path(temporary)
    repo, mocks = base / "repo", base / "bin"
    repo.mkdir()
    mocks.mkdir()
    marker, remote, remote_marker = base / "prepare.json", base / "remote", base / "remote-called"
    def write(relative, content):
        target = repo / relative
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_text(content)
        return target
    def git(*args):
        return subprocess.check_output([real_git, "-C", str(repo), *args], text=True, stderr=subprocess.PIPE).strip()
    write("scripts/nofx-credential-check.sh", wrapper.read_text())
    write("scripts/nofx-credential-check/main.go", "package main\n")
    manifest = write("clusters/homelab/apps/nofx/deployment.yaml", "# synthetic fixture\n")
    write(".gitignore", "scripts/nofx-credential-check/ignored.go\n")
    write("builds/nofx/prepare-source.py", f'''import json
from pathlib import Path
root = Path(__file__).resolve().parents[2]
revision = root / "builds/nofx/revision.txt"
Path({str(marker)!r}).write_text(json.dumps({{
    "archived": root != Path({str(repo)!r}),
    "revision": revision.read_text().strip() if revision.exists() else None,
    "ignored": (root / "scripts/nofx-credential-check/ignored.go").exists(),
    "helper": (root / "scripts/nofx-credential-check/main.go").exists(),
    "manifest": (root / "clusters/homelab/apps/nofx/deployment.yaml").exists(),
}}))
raise SystemExit(89)
''')
    git("init", "-b", "main")
    git("add", ".")
    git("-c", "user.name=Fixture", "-c", "user.email=fixture@example.invalid", "-c", "commit.gpgsign=false", "-c", "core.hooksPath=/dev/null", "commit", "-m", "test: synthetic fixture")
    head = git("rev-parse", "HEAD")
    remote.write_text(head)
    mock_git = mocks / "git"
    mock_git.write_text(f'''#!{sys.executable}
import os, pathlib, sys
args = sys.argv[1:]
if "ls-remote" in args:
    assert "https://github.com/Stuhlmuller/homelab.git" in args
    assert "refs/heads/main" in args
    pathlib.Path({str(remote_marker)!r}).touch()
    print(pathlib.Path({str(remote)!r}).read_text().strip() + "\\trefs/heads/main")
else:
    os.execv({real_git!r}, [{real_git!r}, *args])
''')
    mock_git.chmod(0o755)
    for command in ("go", "kubectl", "yq"):
        mock = mocks / command
        mock.write_text(f"#!{sys.executable}\nfrom pathlib import Path\nPath({str(base / command)!r}).touch()\nraise SystemExit(97)\n")
        mock.chmod(0o755)
    env = dict(os.environ, PATH=str(mocks) + os.pathsep + os.environ["PATH"])
    def run(name, args, expected_prepare=False):
        for path in (marker, remote_marker, base / "go", base / "kubectl", base / "yq"):
            path.unlink(missing_ok=True)
        result = subprocess.run(["bash", str(repo / "scripts/nofx-credential-check.sh"), *args], cwd=repo, env=env, capture_output=True, text=True)
        assert result.returncode != 0, name + ": expected rejection or fixture stop"
        assert marker.exists() == expected_prepare, name + ": unexpected prepare reachability: " + result.stderr
        assert not any((base / command).exists() for command in ("go", "kubectl", "yq")), name + ": reached build or runtime command"
        print("PASS", name)
    run("missing reviewed SHA", ["inspect"])
    run("malformed SHA", ["inspect", "not-a-sha"])
    manifest.write_text("# dirty tracked fixture\n")
    run("dirty tracked checkout", ["inspect", head])
    manifest.write_text("# synthetic fixture\n")
    untracked = write("untracked.txt", "fixture\n")
    run("dirty untracked checkout", ["inspect", head])
    untracked.unlink()
    run("local HEAD mismatch", ["inspect", "f" * 40])
    remote.write_text("e" * 40)
    run("remote main mismatch", ["inspect", head])
    remote.write_text(head)
    write("scripts/nofx-credential-check/ignored.go", "package main // must not be archived\n")
    run("clean reviewed archive with ignored file", ["inspect", head], True)
    assert json.loads(marker.read_text()) == dict(archived=True, revision=head, ignored=False, helper=True, manifest=True), "preparer did not use exact reviewed archive"
    run("credential-free test mode", ["test"], True)
    assert not remote_marker.exists(), "test mode contacted remote main"
