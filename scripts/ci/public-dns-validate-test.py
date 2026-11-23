#!/usr/bin/env python3
"""Exercise queued and moving main with local Git and stubbed validation."""

import os
from pathlib import Path
import subprocess
import tempfile

SCRIPT = Path(__file__).resolve().with_name("public-dns-validate.sh")
WORKFLOW = Path(".github/workflows/mastodon-public-dns.yml")


def exercise(case):
    with tempfile.TemporaryDirectory() as directory:
        root = Path(directory)
        origin = root / "origin"
        clone = root / "work"
        origin.mkdir()

        def git(*args, cwd=origin):
            return subprocess.check_output(["git", *args], cwd=cwd, text=True).strip()

        def write(path, contents):
            path.parent.mkdir(parents=True, exist_ok=True)
            path.write_text(contents)

        def commit(message):
            git("add", ".")
            git("commit", "-qm", message)
            return git("rev-parse", "HEAD")

        git("init", "-q", "--initial-branch=main")
        git("config", "user.name", "DNS test")
        git("config", "user.email", "dns@example.invalid")
        git("config", "commit.gpgsign", "false")
        write(origin / WORKFLOW, "workflow definition\n")
        write(origin / "scripts/config/nix-cache.json", "{}\n")
        write(origin / "scripts/ci/nix-checks.sh", 'test "$1" = --policy && test -s "$2"\n')
        write(origin / "scripts/ci/static-checks.sh", """set -eu
test "$1" = --offline-verified
git rev-parse HEAD >>"$SEEN"
if [[ -n "$ADVANCE_TO" && "$(wc -l <"$SEEN")" -eq 1 ]]; then
  git -C "$ORIGIN" update-ref refs/heads/main "$ADVANCE_TO"
fi
test "$CASE" != failed-check
""")
        original = commit("dispatch")
        write(origin / "wiki.md", "first update\n")
        first = commit("first update")
        write(origin / "wiki.md", "second update\n")
        second = commit("second update")
        write(origin / WORKFLOW, "changed workflow\n")
        changed_workflow = commit("change workflow")
        git("reset", "--hard", first)
        git("clone", "-q", str(origin), str(clone), cwd=root)
        git("checkout", "-q", "--detach", original, cwd=clone)
        if case == "workflow-change":
            git("update-ref", "refs/heads/main", changed_workflow)
        if case == "rewritten-main":
            git("checkout", "-q", "--orphan", "other")
            git("commit", "--allow-empty", "-qm", "unrelated history")
            git("update-ref", "refs/heads/main", git("rev-parse", "HEAD"))

        nix = root / "bin/nix"
        write(nix, '#!/usr/bin/env bash\nset -eu\ntest "$1 $2" = "develop --command"\nshift 2\nexec "$@"\n')
        nix.chmod(0o755)
        output = root / "output"
        output.touch()
        seen = root / "seen"
        env = {
            **os.environ, "GITHUB_REPOSITORY": "Stuhlmuller/homelab",
            "GITHUB_REF": "refs/heads/main", "GITHUB_EVENT_NAME": "workflow_dispatch",
            "GITHUB_SHA": original, "EXPECTED_SHA": original, "GITHUB_OUTPUT": str(output),
            "PATH": f"{nix.parent}:{os.environ['PATH']}", "ORIGIN": str(origin), "SEEN": str(seen),
            "CASE": case, "ADVANCE_TO": second if case == "advances-during-checks" else "",
        }
        result = subprocess.run(["bash", str(SCRIPT)], cwd=clone, env=env, capture_output=True, text=True)
        tested = seen.read_text().splitlines() if seen.exists() else []
        if case in {"workflow-change", "rewritten-main", "failed-check"}:
            assert result.returncode != 0 and not output.read_text(), result.stderr
            assert tested == ([first] if case == "failed-check" else [])
        else:
            assert result.returncode == 0, result.stderr
            assert tested == ([first, second] if case == "advances-during-checks" else [first])
            assert output.read_text() == f"sha={tested[-1]}\n"


for case in ("queued", "advances-during-checks", "workflow-change", "rewritten-main", "failed-check"):
    exercise(case)
print("Public DNS validation follows reviewed main and rejects stale or unvalidated output")
