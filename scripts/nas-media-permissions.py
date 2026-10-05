#!/usr/bin/env python3
"""Preview or repair owner-1000 media permissions for the guest-squashed NAS export."""
import argparse
import json
import os
from pathlib import Path, PurePosixPath
import re
import shlex
import subprocess
import sys

ROOT = Path(__file__).resolve().parent.parent
SSH = ["ssh", "-T", "-o", "BatchMode=yes", "themanofrod@10.1.0.2", "/bin/sh", "-s"]
APPS = {"sonarr": (8989, "series", "/tv/", "tv/"),
        "radarr": (7878, "movie", "/movies/", "movies/")}
PREAMBLE = r'''set -eu
[ "$(id -u)" = 1000 ] || exit 70
base=$(cd -P /share/media && pwd)
case "$base" in /share/*) ;; *) exit 71;; esac
validate() {
  case "$1" in "$base"/*) ;; *) exit 72;; esac
  p=$1
  while [ "$p" != "$base" ]; do
    [ ! -L "$p" ] || exit 73
    p=${p%/*}
  done
}
'''


def run(command, **kwargs):
    return subprocess.run(command, capture_output=True, check=True, timeout=300, **kwargs)


def reviewed_main(expected):
    if not expected or not re.fullmatch(r"[0-9a-f]{40}", expected):
        raise ValueError("A full reviewed main SHA is required")
    git = ["git", "-C", str(ROOT)]
    if run(git + ["status", "--porcelain=v1", "--untracked-files=all"]).stdout:
        raise ValueError("A clean checkout is required")
    head = run(git + ["rev-parse", "HEAD"]).stdout.decode().strip()
    remote = run(["git", "ls-remote", "https://github.com/Stuhlmuller/homelab.git",
                  "refs/heads/main"]).stdout.decode().split()[0]
    if head != expected or remote != expected:
        raise ValueError("Checkout and remote main must match the reviewed SHA")


def arr(app, endpoint, body=None):
    port = APPS[app][0]
    command = r'''set -eu
key=$(sed -n 's:.*<ApiKey>\([^<]*\)</ApiKey>.*:\1:p' /config/config.xml)
case "$key" in *[!a-fA-F0-9]*|'') exit 1;; esac
printf 'header = "X-Api-Key: %s"\n' "$key" | curl -fsS --config -'''
    command += " " + shlex.quote(f"http://127.0.0.1:{port}/api/v3/{endpoint}")
    if body is not None:
        command += " -H 'Content-Type: application/json' --data " + shlex.quote(json.dumps(body))
    response = run(["kubectl", "-n", "media", "exec", f"deploy/{app}", "-c", "app",
                    "--", "/bin/sh", "-ec", command])
    return json.loads(response.stdout)


def relative_path(app, path):
    prefix, target = APPS[app][2:]
    if (not isinstance(path, str) or not path.startswith(prefix) or path == prefix
            or any(ord(c) < 32 for c in path) or "\\" in path
            or any(p in ("", ".", "..") for p in path[1:].split("/"))):
        raise ValueError("Unsafe registered media path")
    return target + path[len(prefix):]


def registered():
    libraries = {app: arr(app, values[1]) for app, values in APPS.items()}
    roots = sorted({relative_path(app, item["path"])
                    for app, items in libraries.items() for item in items})
    return libraries, roots


def inspect(roots):
    script = PREAMBLE + "printf 'base\\0%s\\0' \"$base\"\n"
    for root in roots:
        script += 'root="$base"/' + shlex.quote(root) + '\nvalidate "$root"\n'
        script += r'''if [ ! -e "$root" ]; then printf 'missing\0%s\0' "$root"; else
[ -d "$root" ] || exit 74
[ "$(stat -c "%d" "$root")" = "$(stat -c "%d" "$base")" ] || exit 79
find "$root" -xdev \( -type d -o -type f \) -user 1000 -exec sh -c '
  device=$1; shift
  for file do
    [ ! -L "$file" ] || exit 75
    [ "$(stat -c "%d" "$file")" = "$device" ] || continue
    if [ -d "$file" ]; then kind=d; else kind=f; fi
    printf "%s %s\0%s\0" "$kind" "$(stat -c "%u %a %d %i" "$file")" "$file"
  done' sh "$(stat -c "%d" "$root")" {} +
fi
'''
    parts = run(SSH, input=script.encode()).stdout.decode().split("\0")
    if parts[-1] != "" or parts[:1] != ["base"] or len(parts) % 2 != 1:
        raise ValueError("Invalid NAS inventory")
    base, records, missing = parts[1], {}, 0
    for meta, path in zip(parts[2:-1:2], parts[3:-1:2]):
        if not any(PurePosixPath(path).is_relative_to(PurePosixPath(base) / root) for root in roots):
            raise ValueError("NAS inventory escaped registered roots")
        if meta == "missing":
            missing += 1
            continue
        kind, uid, mode, device, inode = meta.split()
        if kind not in ("d", "f") or uid != "1000" or not re.fullmatch(r"[0-7]{1,4}", mode):
            raise ValueError("Unexpected NAS ownership or mode")
        wanted = int(mode, 8) | (0o777 if kind == "d" else 0o444)
        if wanted != int(mode, 8):
            records[path] = {"path": path, "kind": kind, "mode": mode,
                             "identity": f"{uid} {mode} {device} {inode}"}
    return base, list(records.values()), missing


def mutation_script(base, entries):
    script = PREAMBLE + '[ "$base" = ' + shlex.quote(base) + ' ] || exit 76\n'
    # Check the entire snapshot before any chmod, then check again at each change.
    def check(entry):
        path = shlex.quote(entry["path"])
        return (f"validate {path}\n[ -{entry['kind']} {path} ] || exit 77\n"
                f'[ "$(stat -c "%u %a %d %i" {path})" = '
                f"{shlex.quote(entry['identity'])} ] || exit 78\n")
    script += "".join(check(entry) for entry in entries)
    for entry in entries:
        mode = "a+rwX" if entry["kind"] == "d" else "a+r"
        script += check(entry) + f"chmod {mode} {shlex.quote(entry['path'])}\n"
    return script


def save_journal(path, data):
    target = Path(path).absolute()
    if target.resolve().is_relative_to(ROOT):
        raise ValueError("Mode journals must remain outside the public repository")
    descriptor = os.open(target, os.O_WRONLY | os.O_CREAT | os.O_EXCL | os.O_NOFOLLOW, 0o600)
    with os.fdopen(descriptor, "w") as stream:
        json.dump(data, stream)
        stream.flush()
        os.fsync(stream.fileno())


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--execute", action="store_true")
    parser.add_argument("--expected-sha")
    parser.add_argument("--journal", help="New private mode-snapshot file outside the repository")
    parser.add_argument("--rescan", action="store_true", help="Queue registered Arr item rescans after repair")
    args = parser.parse_args(argv)
    if args.execute:
        if not args.journal:
            raise ValueError("Execution requires a private --journal destination")
        reviewed_main(args.expected_sha)
    elif args.rescan:
        raise ValueError("Rescanning requires --execute")
    libraries, roots = registered()
    base, entries, missing = inspect(roots)
    if args.journal:
        save_journal(args.journal, {"base": base, "roots": roots, "entries": entries})
    if args.execute:
        run(SSH, input=mutation_script(base, entries).encode())
        if inspect(roots)[1]:
            raise RuntimeError("NAS permission repair did not converge")
        if args.rescan:
            for app, items in libraries.items():
                for item in items:
                    arr(app, "command", {"name": "RescanSeries" if app == "sonarr" else "RescanMovie",
                                         "seriesId" if app == "sonarr" else "movieId": item["id"]})
    print(json.dumps({"registered_roots": len(roots), "missing_roots": missing,
                      "planned_changes": len(entries), "applied_changes": len(entries) if args.execute else 0}))


if __name__ == "__main__":
    if not sys.flags.isolated:
        raise SystemExit("Run this operator command with python3 -I")
    try:
        main()
    except Exception as error:
        print(f"NAS media permission check failed ({type(error).__name__}); private details withheld", file=sys.stderr)
        raise SystemExit(1) from None
