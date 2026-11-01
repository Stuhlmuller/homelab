#!/usr/bin/env python3
"""Read-only PR dependency planning and checkout-local delivery checkpoints."""

import argparse
from concurrent.futures import ThreadPoolExecutor
from contextlib import contextmanager
import fcntl
import json
import os
from pathlib import Path
import re
import subprocess
import tempfile

REPO = "Stuhlmuller/homelab"
SHA = re.compile(r"[0-9a-f]{40}")


def command(*args):
    return subprocess.run(args, check=True, capture_output=True, text=True).stdout


def api(path, paginate=False):
    args = ["gh", "api", f"repos/{REPO}/{path}"]
    if paginate:
        args += ["--paginate", "--slurp"]
        return [item for page in json.loads(command(*args)) for item in page]
    return json.loads(command(*args))


def dependencies(pr, prs):
    parents = set()
    for line in (pr.get("body") or "").splitlines():
        if line.strip().startswith("Depends-On:"):
            match = re.fullmatch(r"Depends-On: #([1-9][0-9]*)", line.strip())
            if not match:
                raise ValueError(f"PR #{pr['number']}: malformed Depends-On line")
            parents.add(int(match[1]))
    if pr["base"]["ref"] != "main":
        matches = [p for p in prs.values() if p["head"]["ref"] == pr["base"]["ref"]
                   and (p["head"].get("repo") or {}).get("full_name") == REPO]
        if len(matches) != 1:
            raise ValueError(f"PR #{pr['number']}: base needs manual identification")
        parents.add(matches[0]["number"])
    return sorted(parents)


def make_plan(snapshot, roots=None, records=None):
    prs = {p["number"]: p for p in snapshot["pull_requests"]}
    required = snapshot["required_checks"]
    if not required:
        raise ValueError("No required main checks discovered; inspect repository rules")
    roots = roots or [n for n, p in prs.items() if p["state"] == "open"]
    records = records or {}
    result, visiting, visited = [], set(), set()

    def visit(number):
        if number in visiting:
            raise ValueError(f"Dependency cycle at PR #{number}")
        if number in visited:
            return
        if number not in prs:
            raise ValueError(f"Missing dependency PR #{number}")
        pr = prs[number]
        if pr["state"] != "open":
            if not pr.get("merged_at"):
                raise ValueError(f"Dependency PR #{number} closed without merging")
            if pr["base"]["ref"] != "main":
                raise ValueError(f"Dependency PR #{number} merged off main; verify reachability")
            visited.add(number)
            return
        visiting.add(number)
        parents = dependencies(pr, prs)
        for parent in parents:
            visit(parent)
        visiting.remove(number)
        visited.add(number)
        checks = pr.get("checks", {})
        missing = [c["context"] for c in required if c["context"] not in checks]
        failed = [c["context"] for c in required
                  if checks.get(c["context"]) in {"failure", "cancelled", "timed_out",
                                                 "action_required", "error", "startup_failure"}]
        pending = [c["context"] for c in required
                   if c["context"] in checks
                   and checks[c["context"]] not in {"success", "neutral", "skipped"}
                   and c["context"] not in failed]
        waiting = [n for n in parents if not prs[n].get("merged_at")]
        labels = [label["name"] for label in pr.get("labels", [])]
        if (pr["head"].get("repo") or {}).get("full_name") != REPO:
            action = "inspect-fork"
        elif "delivery/hold" in labels:
            action = "external-hold"
        elif waiting:
            action = "wait-parent"
        elif pr["base"]["ref"] != "main":
            action = "restack"
        elif pr.get("mergeable_state") == "dirty" or pr.get("mergeable") is False:
            action = "repair-conflicts"
        elif failed:
            action = "repair-checks"
        elif missing:
            action = "inspect-missing-checks"
        elif pending:
            action = "wait-checks"
        elif pr.get("draft"):
            action = "review-draft"
        elif pr.get("mergeable") is not True:
            action = "refresh-mergeability"
        else:
            action = "verify-and-merge"
        record = records.get(str(number))
        result.append({"number": number, "head": pr["head"]["sha"],
                       "base": pr["base"]["sha"], "parents": parents,
                       "action": action, "draft": bool(pr.get("draft")),
                       "missing_checks": missing, "failed_checks": failed,
                       "pending_checks": pending, "checkpoint": record,
                       "checkpoint_stale": bool(record and (record["head"] != pr["head"]["sha"] or record.get("base") != pr["base"]["sha"]))})

    for number in sorted(roots):
        visit(number)
    return {"repository": REPO, "required_checks": required, "actions": result,
            "notice": "Advisory plan. Verify signatures, reviews, App identities and activation gates before merging."}


def live_snapshot(roots=None):
    prs = {p["number"]: p for p in api("pulls?state=open&per_page=100", True)}
    selected, seen = list(roots or prs), set()
    while selected:
        number = selected.pop()
        if number in seen:
            continue
        seen.add(number)
        if number not in prs:
            prs[number] = api(f"pulls/{number}")
        pr = prs[number]
        if pr["state"] != "open":
            continue
        base = pr["base"]["ref"]
        if base != "main" and not any(p["head"]["ref"] == base for p in prs.values()):
            # Pass branch names as API parameters, never shell source or URL fragments.
            pages = json.loads(command("gh", "api", "--method", "GET",
                                       f"repos/{REPO}/pulls", "-f", "state=all",
                                       "-f", f"head=Stuhlmuller:{base}",
                                       "-f", "per_page=100", "--paginate", "--slurp"))
            candidates = [p for page in pages for p in page]
            if len(candidates) != 1:
                raise ValueError(f"PR #{number}: base branch has ambiguous history")
            prs[candidates[0]["number"]] = candidates[0]
        selected.extend(dependencies(pr, prs))

    def inspect(number):
        pr = api(f"pulls/{number}")
        if pr["head"]["sha"] != prs[number]["head"]["sha"]:
            raise ValueError(f"PR #{number}: head changed during snapshot; retry")
        checks = {}
        if pr["state"] == "open":
            sha = pr["head"]["sha"]
            # REST lists newest first; retain latest result per context.
            for status in api(f"commits/{sha}/statuses?per_page=100", True):
                checks.setdefault(status["context"], status["state"])
            pages = json.loads(command("gh", "api", f"repos/{REPO}/commits/{sha}/check-runs?per_page=100",
                                       "--paginate", "--slurp"))
            runs = [run for page in pages for run in page["check_runs"]]
            for run in sorted(runs, key=lambda r: r["id"], reverse=True):
                checks.setdefault(run["name"], run["conclusion"] or run["status"])
        pr["checks"] = checks
        return number, pr

    with ThreadPoolExecutor(max_workers=4) as pool:
        for number, pr in pool.map(inspect, sorted(seen)):
            prs[number] = pr
    rules = api("rules/branches/main")
    required = [check for rule in rules if rule["type"] == "required_status_checks"
                for check in rule["parameters"]["required_status_checks"]]
    return {"pull_requests": list(prs.values()), "required_checks": required}


def state_directory():
    common = command("git", "rev-parse", "--path-format=absolute", "--git-common-dir").strip()
    return Path(common) / "pr-delivery"


@contextmanager
def locked_state(directory):
    directory.mkdir(mode=0o700, parents=True, exist_ok=True)
    with (directory / "state.lock").open("a") as lock:
        fcntl.flock(lock, fcntl.LOCK_EX)
        path = directory / "state.json"
        state = json.loads(path.read_text()) if path.exists() else {}
        yield state
        with tempfile.NamedTemporaryFile(mode="w", dir=directory, delete=False) as tmp:
            json.dump(state, tmp, indent=2)
            tmp.write("\n")
            tmp.flush()
            os.fsync(tmp.fileno())
        os.replace(tmp.name, path)


def checkpoint(directory, number, head, owner, next_action, blocker, current_head, base=None):
    if not SHA.fullmatch(head) or head != current_head:
        raise ValueError("Head changed or invalid; refresh before recording")
    with locked_state(directory) as state:
        old = state.get(str(number))
        if old and old["owner"] != owner and not old.get("released"):
            raise ValueError(f"PR #{number} is owned by {old['owner']}; coordinate a handoff")
        state[str(number)] = {"head": head, "base": base, "owner": owner, "next_action": next_action,
                              "blocker": blocker, "released": False}


def release(directory, number, owner):
    with locked_state(directory) as state:
        record = state.get(str(number))
        if record:
            if record["owner"] != owner:
                raise ValueError("Only the recorded owner can release this checkpoint")
            record["released"] = True


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    sub = parser.add_subparsers(dest="operation", required=True)
    plan = sub.add_parser("plan")
    plan.add_argument("--pr", type=int, action="append")
    plan.add_argument("--snapshot", type=Path)
    record = sub.add_parser("record")
    record.add_argument("--pr", type=int, required=True)
    record.add_argument("--head", required=True)
    record.add_argument("--owner", required=True)
    record.add_argument("--next-action", required=True)
    record.add_argument("--blocker", required=True)
    unlock = sub.add_parser("release")
    unlock.add_argument("--pr", type=int, required=True)
    unlock.add_argument("--owner", required=True)
    sub.add_parser("state")
    args = parser.parse_args()
    directory = state_directory()
    path = directory / "state.json"
    if args.operation == "plan":
        snapshot = json.loads(args.snapshot.read_text()) if args.snapshot else live_snapshot(args.pr)
        records = json.loads(path.read_text()) if path.exists() else {}
        print(json.dumps(make_plan(snapshot, args.pr, records), indent=2))
    elif args.operation == "state":
        print(path.read_text() if path.exists() else "{}")
    elif args.operation == "record":
        pr = api(f"pulls/{args.pr}")
        checkpoint(directory, args.pr, args.head, args.owner, args.next_action,
                   args.blocker, pr["head"]["sha"], pr["base"]["sha"])
    else:
        release(directory, args.pr, args.owner)


if __name__ == "__main__":
    try:
        main()
    except (ValueError, KeyError, OSError, subprocess.CalledProcessError) as error:
        raise SystemExit(f"PR delivery stopped: {error}") from error
