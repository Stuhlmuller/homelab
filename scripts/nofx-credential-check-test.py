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
    allow_build = base / "allow-build"
    def write(relative, content):
        target = repo / relative
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_text(content)
        return target
    def git(*args, input=None):
        return subprocess.check_output([real_git, "-C", str(repo), *args], input=input, text=True, stderr=subprocess.PIPE).strip()
    write("scripts/nofx-credential-check.sh", wrapper.read_text())
    write("scripts/nofx-credential-check/main.go", "package main\n")
    manifest = write("clusters/homelab/apps/nofx/deployment.yaml", "# synthetic fixture\n")
    write(".gitignore", "scripts/nofx-credential-check/ignored.go\n")
    write("builds/nofx/prepare-source.py", f'''import json, sys
from pathlib import Path
root = Path(__file__).resolve().parents[2]
revision = root / "builds/nofx/revision.txt"
Path({str(marker)!r}).write_text(json.dumps({{
    "archived": root != Path({str(repo)!r}),
    "revision": revision.read_text().strip() if revision.exists() else None,
    "ignored": (root / "scripts/nofx-credential-check/ignored.go").exists(),
    "helper": (root / "scripts/nofx-credential-check/main.go").read_text(),
    "manifest": (root / "clusters/homelab/apps/nofx/deployment.yaml").exists(),
}}))
if Path({str(allow_build)!r}).exists():
    (Path(sys.argv[1]) / "upstream").mkdir(parents=True)
else:
    raise SystemExit(89)
''')
    git("init", "-b", "main")
    git("add", ".")
    git("-c", "user.name=Fixture", "-c", "user.email=fixture@example.invalid", "-c", "commit.gpgsign=false", "-c", "core.hooksPath=/dev/null", "commit", "-m", "test: synthetic fixture")
    head = git("rev-parse", "HEAD")
    remote.write_text(head)
    mock_git = mocks / "git"
    mock_git.write_text(f'''#!{sys.executable}
import os, sys
args = sys.argv[1:]
assert not any(command in args for command in ("ls-remote", "fetch", "pull", "push", "clone")), "git network command forbidden"
os.execv({real_git!r}, [{real_git!r}, *args])
''')
    mock_git.chmod(0o755)
    mock_gh = mocks / "gh"
    mock_gh.write_text(f'''#!{sys.executable}
import pathlib, sys
assert sys.argv[1:] == ["api", "--hostname", "github.com", "repos/Stuhlmuller/homelab/git/ref/heads/main", "--jq", ".object.sha"]
pathlib.Path({str(remote_marker)!r}).touch()
print(pathlib.Path({str(remote)!r}).read_text().strip())
''')
    mock_gh.chmod(0o755)
    for command in ("go", "kubectl", "yq"):
        mock = mocks / command
        mock.write_text(f"#!{sys.executable}\nfrom pathlib import Path\nPath({str(base / command)!r}).touch()\nraise SystemExit(97)\n")
        mock.chmod(0o755)
    expected_go_env = dict(GOENV="off", GOWORK="off", GOFLAGS="", GOTOOLCHAIN="local", GOROOT=None, GO111MODULE="on", CGO_ENABLED="0")
    (mocks / "go").write_text(f'''#!{sys.executable}
import json, os, pathlib, sys
settings = {{key: os.environ.get(key) for key in {tuple(expected_go_env)!r}}}
with pathlib.Path({str(base / "go")!r}).open("a") as output:
    output.write(json.dumps({{"command": sys.argv[1], "settings": settings}}) + "\\n")
assert settings == {expected_go_env!r}, "ambient Go settings reached the build"
root = pathlib.Path.cwd().parents[1]
for variable, directory in {{"GOPATH": "go", "GOMODCACHE": "modules", "GOCACHE": "go-build"}}.items():
    cache = pathlib.Path(os.environ[variable]).resolve()
    assert cache == root / directory, "ambient Go cache reached the build"
    if sys.argv[1] == "test":
        assert not cache.exists(), "Go cache was not fresh"
        cache.mkdir()
    else:
        assert cache.is_dir(), "build did not reuse this inspection's isolated cache"
''')
    env = dict(os.environ, PATH=str(mocks) + os.pathsep + os.environ["PATH"])
    def run(name, args, expected_prepare=False, expected_build=False):
        for path in (marker, remote_marker, base / "go", base / "kubectl", base / "yq"):
            path.unlink(missing_ok=True)
        result = subprocess.run(["bash", str(repo / "scripts/nofx-credential-check.sh"), *args], cwd=repo, env=env, capture_output=True, text=True)
        assert (result.returncode == 0) == expected_build, name + ": unexpected exit: " + result.stderr
        assert marker.exists() == expected_prepare, name + ": unexpected prepare reachability: " + result.stderr
        assert (base / "go").exists() == expected_build, name + ": unexpected build reachability"
        assert not any((base / command).exists() for command in ("kubectl", "yq")), name + ": reached runtime command"
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
    assert json.loads(marker.read_text()) == dict(archived=True, revision=head, ignored=False, helper="package main\n", manifest=True), "preparer did not use exact reviewed archive"
    original = git("rev-parse", head + ":scripts/nofx-credential-check/main.go")
    replacement = git("hash-object", "-w", "--stdin", input="package main // unreviewed replacement\n")
    git("replace", original, replacement)
    assert git("show", head + ":scripts/nofx-credential-check/main.go") != "package main", "replacement fixture ineffective"
    run("replacement blob excluded from archive", ["inspect", head], True)
    assert json.loads(marker.read_text())["helper"] == "package main\n", "archive accepted unreviewed replacement blob"
    git("replace", "-d", original)
    canonical = "https://github.com/Stuhlmuller/homelab.git"
    rewrite = "url." + repo.as_uri() + ".insteadOf"
    git("config", rewrite, canonical)
    assert git("-c", "protocol.allow=never", "-c", "protocol.file.allow=always", "ls-remote", canonical, "refs/heads/main") == head + "\trefs/heads/main", "local URL rewrite fixture ineffective"
    remote.write_text("e" * 40)
    run("URL rewrite cannot spoof canonical main", ["inspect", head])
    assert remote_marker.exists(), "canonical GitHub main was not checked"
    git("config", "--unset", rewrite)
    remote.write_text(head)
    run("credential-free test mode", ["test"], True)
    assert not remote_marker.exists(), "test mode contacted remote main"
    allow_build.touch()
    env.update(GOENV="/fixture/goenv", GOWORK="/fixture/go.work", GOFLAGS="-overlay=/fixture/unreviewed.json", GOTOOLCHAIN="unreviewed-toolchain", GOROOT="/fixture/goroot", GO111MODULE="off", GOPATH="/fixture/gopath", GOMODCACHE="/fixture/modules", GOCACHE="/fixture/cache")
    run("ambient Go settings isolated", ["test"], True, True)
    calls = [json.loads(line) for line in (base / "go").read_text().splitlines()]
    assert calls == [dict(command=command, settings=expected_go_env) for command in ("test", "build")], "both Go calls must use isolated settings"
    assert not remote_marker.exists(), "test mode contacted remote main"
