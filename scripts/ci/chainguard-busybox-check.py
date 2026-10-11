#!/usr/bin/env python3
"""Run declared BusyBox commands in the exact candidate image on disposable volumes."""

import json
import subprocess
import tempfile
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
IMAGE = "harbor.stinkyboi.com/mirror/cgr.dev/chainguard/busybox:latest@sha256:f7d9063f22547e726221275158930e5033be3c6d8340c6867afb7d0d779fad8d"


def load(app, filename):
    path = ROOT / "clusters/homelab/apps" / app / filename
    return json.loads(subprocess.check_output(["yq", "ea", "-o=json", "-I=0", "[.]", str(path)], text=True))


def image(container):
    value = container["image"]
    return value if isinstance(value, str) else value["repository"] + ":" + value["tag"]


def run_case(name, container, uid, verify, *, caps=(), readonly_config=False, probe=None):
    assert image(container) == IMAGE, f"Unexpected candidate for {name}"
    with tempfile.TemporaryDirectory(prefix="busybox-compat-") as directory:
        root = Path(directory)
        for part in ("config", "backup", "downloads", "target", "grafana", "host-sysctl"):
            (root / part).mkdir()
        (root / "config/config.xml").write_text("<Config><ApiKey>fixture</ApiKey></Config>\n")
        (root / "grafana/grafana.db").write_bytes(b"retained database fixture\n")
        (root / "host-sysctl/user.max_user_namespaces").write_text("0\n")
        backup = root / "backup/local-backups"
        backup.mkdir()
        for filename in ("20200101T000000Z.tar.gz", ".old.partial", "retain-unrelated"):
            (backup / filename).write_text("old fixture")
        mounts = []
        for part in ("config", "backup", "downloads", "target", "host-sysctl"):
            mounts += ["--volume", f"{root / part}:/{part}"]
        mounts += ["--volume", f"{root / 'grafana'}:/var/lib/grafana"]
        source = IMAGE.removeprefix("harbor.stinkyboi.com/mirror/")
        common = ["docker", "run", "--rm", "--network", "none", "--read-only", "--cap-drop", "ALL"]
        # Seed only disposable volumes; no host chown or production paths.
        setup = 'chown -R "$1:$1" /config /backup /downloads /target /var/lib/grafana /host-sysctl; chmod -R u+rwX,go+rX /config /backup /downloads /target /var/lib/grafana; touch -t 202001010000 /backup/local-backups/20200101T000000Z.tar.gz /backup/local-backups/.old.partial'
        subprocess.run(common + ["--cap-add", "CHOWN", "--cap-add", "FOWNER", "--user", "0:0"] + mounts
                       + ["--entrypoint", "/bin/sh", source, "-ec", setup, "fixture", str(uid)], check=True)
        if readonly_config:
            mounts[mounts.index(f"{root / 'config'}:/config")] += ":ro"
        security = ["--user", f"{uid}:{uid}"]
        for capability in caps:
            security += ["--cap-add", capability]
        command = container.get("command", []) + container.get("args", [])
        assert command[:2] == ["/bin/sh", "-ec"], f"Unexpected shell contract for {name}"
        subprocess.run(common + security + mounts + ["--entrypoint", command[0], source] + command[1:], check=True, timeout=30)
        subprocess.run(common + security + mounts + ["--entrypoint", "/bin/sh", source, "-ec", verify], check=True, timeout=30)
        if probe:
            assert image(probe) == IMAGE and probe["securityContext"]["runAsUser"] == 65534
            for name in ("readinessProbe", "livenessProbe"):
                command = probe[name]["exec"]["command"]
                subprocess.run(common + ["--user", "65534:65534"] + mounts
                               + ["--entrypoint", command[0], source] + command[1:], check=True, timeout=30)
        print(f"Passed {name} at UID {uid}", flush=True)


def main():
    for app in ("radarr", "sonarr", "deluge"):
        cron = next(d for d in load(app, "backup-cronjob.yaml") if d and d.get("kind") == "CronJob")
        pod = cron["spec"]["jobTemplate"]["spec"]["template"]["spec"]
        assert pod["securityContext"]["runAsUser"] == 1000
        verify = 'set -- /backup/local-backups/20*.tar.gz; test "$#" -eq 1; test ! -e /backup/local-backups/20200101T000000Z.tar.gz; test ! -e /backup/local-backups/.old.partial; test -f /backup/local-backups/retain-unrelated; test "$(stat -c %a "$1")" = 600; tar -xOzf "$1" ./config.xml | cmp - /config/config.xml'
        run_case(app + " backup", pod["containers"][0], 1000, verify, readonly_config=True)
        job = next(d for d in load(app, "media-storage.yaml") if d and d.get("kind") == "Job")
        pod = job["spec"]["template"]["spec"]
        assert pod["securityContext"]["runAsUser"] == 65534
        run_case(app + " NAS directories", pod["containers"][0], 65534,
                 'test -n "$(find /target -mindepth 1 -type d)"; test -z "$(find /target -mindepth 1 -type d ! -perm 0777)"')
    for app in ("radarr", "sonarr", "bazarr", "deluge"):
        controller = load(app, "values.yaml")[0]["controllers"][app]
        container = controller["initContainers"]["download-dirs" if app == "deluge" else "prepare-config"]
        assert container["securityContext"]["runAsUser"] == 0
        caps = container["securityContext"].get("capabilities", {}).get("add", [])
        verify = 'test -d /downloads/complete/radarr; test -d /downloads/complete/sonarr' if app == "deluge" else 'test "$(stat -c %u:%g /config)" = 1000:1000'
        run_case(app + " init", container, 0, verify, caps=caps)
    grafana = load("grafana", "values.yaml")[0]["extraInitContainers"][0]
    run_case("Grafana retained database", grafana, 472,
             'cmp /var/lib/grafana/grafana.db /var/lib/grafana/grafana.db.pre-v13')
    daemon = next(d for d in load("cordium", "user-namespace-sysctl.yaml") if d and d.get("kind") == "DaemonSet")
    pod = daemon["spec"]["template"]["spec"]
    run_case("Cordium sysctl file command", pod["initContainers"][0], 0,
             'test "$(cat /host-sysctl/user.max_user_namespaces)" = 28633', probe=pod["containers"][0])
    print("BusyBox command compatibility passed; live NAS and kernel behavior remain rollout gates")


if __name__ == "__main__":
    main()
