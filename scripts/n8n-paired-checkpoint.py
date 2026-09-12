#!/usr/bin/env python3
"""Capture a cold n8n pair, resume pinned service and unpin through existing units."""
import argparse
import datetime
import importlib.util
import json
import os
import re
import shutil
import signal
import subprocess
import tarfile
import tempfile
import threading
import time
import uuid
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
_spec = importlib.util.spec_from_file_location("phase", ROOT / "scripts/n8n-checkpoint-phase.py")
phase = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(phase)
_backup_spec = importlib.util.spec_from_file_location("etcd_backup", ROOT / "scripts/talos-etcd-backup.py")
etcd_backup = importlib.util.module_from_spec(_backup_spec)
_backup_spec.loader.exec_module(etcd_backup)
CLAIMS = {"n8n": "n8n", "n8n-postgres": "data-n8n-postgres-0"}
READERS = {"n8n-checkpoint-n8n", "n8n-checkpoint-postgres"}


def private_destination(path):
    path = etcd_backup.private_directory(path)
    temporary_roots = (Path("/tmp"), Path("/var/tmp"), Path("/var/folders"), Path(tempfile.gettempdir()))
    for temporary in temporary_roots:
        temporary = temporary.resolve()
        if path == temporary or temporary in path.parents:
            raise ValueError("use durable storage outside temporary/cache directories")
    return path


class CommandCleanupError(RuntimeError):
    """A command group could not be reaped; do not start recovery mutations."""


def terminate_command(process):
    """Stop the owned process group, including providers, before recovery can run."""
    try:
        os.killpg(process.pid, signal.SIGTERM)
    except ProcessLookupError:
        pass
    try:
        process.wait(timeout=2)
    except subprocess.TimeoutExpired:
        pass
    finally:
        # A parent may exit while a child ignores TERM or has closed its pipes.
        try:
            os.killpg(process.pid, signal.SIGKILL)
        except ProcessLookupError:
            pass
    process.communicate(timeout=2)


def run(command, **kwargs):
    timeout = kwargs.pop("timeout", 30)
    process = subprocess.Popen(command, stdout=subprocess.PIPE, stderr=subprocess.PIPE,
                               text=True, start_new_session=True, **kwargs)
    try:
        output, error = process.communicate(timeout=timeout)
        if process.returncode:
            raise subprocess.CalledProcessError(process.returncode, command, output, error)
        return output
    except BaseException:
        try:
            terminate_command(process)
        except BaseException as cleanup_failure:
            raise CommandCleanupError(f"command group {process.pid} cleanup failed; recovery was not started") from cleanup_failure
        raise
    finally:
        process.stdout.close()
        process.stderr.close()


def kube(*args):
    return json.loads(run(["kubectl", "--request-timeout=20s", *args, "-o", "json"]))


def now():
    return datetime.datetime.now(datetime.timezone.utc).isoformat()


def write_json(path, value):
    """Never replace a prior receipt; fsync both the file and containing directory."""
    with path.open("x", encoding="utf-8") as stream:
        json.dump(value, stream, indent=2)
        stream.write("\n")
        stream.flush()
        os.fsync(stream.fileno())
    fsync_directory(path.parent)


def fsync_directory(path):
    descriptor = os.open(path, os.O_RDONLY)
    try:
        os.fsync(descriptor)
    finally:
        os.close(descriptor)


def node_metadata():
    return {item["metadata"]["name"]: {
        "boot_id": item["status"]["nodeInfo"]["bootID"],
        "address": next(x["address"] for x in item["status"]["addresses"] if x["type"] == "InternalIP"),
        "ready": any(c["type"] == "Ready" and c["status"] == "True" for c in item["status"]["conditions"]),
    } for item in kube("get", "nodes")["items"]}


def claim_metadata():
    result = {}
    for claim in CLAIMS.values():
        pvc = kube("get", "pvc", claim, "-n", "automation")
        if pvc.get("status", {}).get("phase") != "Bound":
            raise ValueError("source claim is not Bound")
        pv = kube("get", "pv", pvc["spec"]["volumeName"])
        if pv["spec"].get("persistentVolumeReclaimPolicy") != "Retain" or "nfs" not in pv["spec"]:
            raise ValueError("review changed source storage before checkpoint")
        result[claim] = {"claim_uid": pvc["metadata"]["uid"], "volume": pvc["spec"]["volumeName"],
                         "volume_uid": pv["metadata"]["uid"], "source": pv["spec"]["nfs"]}
    return result


def expected_revision(application, revision):
    status = application.get("status", {}).get("sync", {})
    revisions = status.get("revisions", [status.get("revision")])
    sources = application["spec"]["sources"]
    return len(revisions) == len(sources) and all(
        revisions[i] == revision for i, source in enumerate(sources)
        if source["repoURL"] == "https://github.com/Stuhlmuller/homelab.git")


def require_capture_ready(live, revision):
    if any(phase.markers(item)[phase.PHASE] != "normal" for item in live.values()):
        raise ValueError("existing maintenance must be resumed and unpinned first")
    if any(not expected_revision(item, revision)
           or item.get("status", {}).get("health", {}).get("status") != "Healthy"
           or item.get("status", {}).get("sync", {}).get("status") != "Synced" for item in live.values()):
        raise ValueError("both Applications must be Healthy and Synced on prepared main")


def check_nodes(expected, current):
    if current != expected or not all(x["ready"] for x in current.values()):
        raise ValueError("node identity/readiness changed; do not start another writer")


def source_pods():
    return [item for item in kube("get", "pods", "-n", "automation")["items"]
            if any(v.get("persistentVolumeClaim", {}).get("claimName") in CLAIMS.values()
                   for v in item["spec"].get("volumes", []))]


def pod_identity(pod):
    return {"name": pod["metadata"]["name"], "uid": pod["metadata"]["uid"],
            "resource_version": pod["metadata"]["resourceVersion"],
            "node": pod["spec"]["nodeName"],
            "images": {c["name"]: c["image"] for c in pod["spec"]["containers"]},
            "containers": {c["name"]: c["containerID"] for c in pod["status"]["containerStatuses"]},
            "mounts": {v["name"]: {"claim": v["persistentVolumeClaim"], "mounts": [
                {"container": c["name"], **mount} for c in pod["spec"]["containers"]
                for mount in c.get("volumeMounts", []) if mount["name"] == v["name"]]}
                for v in pod["spec"].get("volumes", []) if "persistentVolumeClaim" in v}}


def check_talos_rows(output, nodes, stopped):
    if not output.startswith("NODE"):
        raise ValueError("unrecognized Talos container metadata")
    rows = [row.split() for row in output.splitlines()[1:] if row.strip()]
    if not {n["address"] for n in nodes.values()} <= {row[0] for row in rows}:
        raise ValueError("Talos did not answer for every node")
    for writer in stopped:
        for row in rows:
            if (any(word.startswith("automation/" + writer["name"] + ":") for word in row)
                    and (row[-1] != "CONTAINER_EXITED" or row[-2] != "0")):
                raise ValueError("prior source container still exists with a running task")


def talos_fence(session, stopped):
    output = run([session["talosctl"], "--talosconfig", session["talosconfig"], "--nodes",
                  ",".join(n["address"] for n in session["nodes"].values()),
                  "containers", "--kubernetes"], timeout=25)
    check_talos_rows(output, session["nodes"], stopped)


def fence(session, stopped, readers=False, check_survivors=True):
    check_nodes(session["nodes"], node_metadata())
    if claim_metadata() != session["claims"]:
        raise ValueError("source claim or volume identity changed")
    stopped_names = {item["name"] for item in stopped}
    all_names = {item["name"] for item in session["writers"].values()}
    for pod in source_pods():
        name = pod["metadata"]["name"]
        if readers and name in READERS:
            spec = pod["spec"]
            uid = 1000 if name.endswith("-n8n") else 65534
            containers = spec["containers"]
            if (spec["securityContext"].get("runAsUser") != uid or "fsGroup" in spec["securityContext"]
                    or len(containers) != 1 or len(spec["volumes"]) != 2
                    or len(containers[0]["volumeMounts"]) != 2
                    or any(not mount.get("readOnly") for mount in containers[0]["volumeMounts"])
                    or any(not v.get("persistentVolumeClaim", {}).get("readOnly", True) for v in spec["volumes"])):
                raise ValueError("reader identity or read-only mounts changed")
            continue
        if name in stopped_names or name not in all_names:
            raise ValueError("a source writer is present while its fence must hold")
        if check_survivors:
            original = next(item for item in session["writers"].values() if item["name"] == name)
            current = pod_identity(pod)
            if any(current[key] != original[key] for key in ("uid", "containers", "mounts")):
                raise ValueError("remaining source writer changed before shutdown")
    talos_fence(session, stopped)


class PodExitWatch:
    """Start before scaling; missing terminal status fails the graceful-stop gate."""
    def __init__(self, writer):
        self.writer, self.terminal, self.error, self.observed = writer, {}, None, False
        self.process = subprocess.Popen([
            "kubectl", "--request-timeout=0", "get", "pod", writer["name"], "-n", "automation",
            "--watch", "--output-watch-events",
            "-o", "json"], stdout=subprocess.PIPE, stderr=subprocess.PIPE)
        self.thread = threading.Thread(target=self.consume, daemon=True)
        self.thread.start()

    def consume(self):
        buffer, decoder = "", json.JSONDecoder()
        try:
            while True:
                data = os.read(self.process.stdout.fileno(), 65536)
                if not data:
                    break
                buffer += data.decode()
                while buffer.strip():
                    buffer = buffer.lstrip()
                    try:
                        event, end = decoder.raw_decode(buffer)
                    except json.JSONDecodeError:
                        break
                    buffer = buffer[end:]
                    pod = event["object"]
                    if pod.get("metadata", {}).get("uid") != self.writer["uid"]:
                        raise ValueError("pod watch identity changed or API watch expired")
                    self.observed = True
                    for status in pod.get("status", {}).get("containerStatuses", []):
                        if status.get("containerID") != self.writer["containers"].get(status["name"]):
                            raise ValueError("container identity changed during pod watch")
                        terminal = status.get("state", {}).get("terminated")
                        if terminal:
                            if status.get("containerID") != self.writer["containers"].get(status["name"]):
                                raise ValueError("container identity changed during shutdown")
                            self.terminal[status["name"]] = terminal
            if not self.terminal:
                raise ValueError("pod watch ended without terminal status")
        except Exception as exc:  # noqa: BLE001 - Every watcher failure must reject clean shutdown.
            self.error = str(exc)

    def require_clean(self):
        if self.error or set(self.terminal) != set(self.writer["containers"]):
            raise ValueError("normal shutdown was not observed for every original container")
        if any(t["exitCode"] != 0 or t.get("signal", 0) != 0 for t in self.terminal.values()):
            raise ValueError("source exited abnormally; capture cannot proceed")

    def close(self):
        self.process.terminate()
        self.process.wait(timeout=10)
        self.thread.join(timeout=10)
        self.process.stdout.close()
        self.process.stderr.close()


def terragrunt(unit, *args, timeout=900):
    return run(["terragrunt", "--log-disable", "run", "--disable-bucket-update",
                "--backend-bootstrap=false", "--", *args], cwd=unit, timeout=timeout)


def validate_plan(plan, desired):
    changes = [change for change in plan.get("resource_changes", [])
               if change["change"]["actions"] != ["no-op"]]
    if len(changes) != 1 or changes[0]["address"] != "kubernetes_manifest.this":
        raise ValueError("phase plan changes resources outside its existing Application")
    change = changes[0]["change"]
    if change["actions"] != ["update"] or change["after"]["manifest"] != desired:
        raise ValueError("phase plan differs from the closed repository profile")


def apply_phase(directory, session, app, target, expected_main_revision=None):
    """Always plan against current original state; never reuse a previous phase plan."""
    live = phase.load_live()
    desired = phase.profile(session["bases"][app], target, session["id"], session["revision"])
    phase.validate_transition(app, desired, live, session["id"])
    attempt = Path(tempfile.mkdtemp(prefix=f"{app}-{target}-", dir=directory))
    var_file, plan = attempt / "profile.tfvars.json", attempt / "phase.plan"
    write_json(var_file, {"manifest": desired})
    write_json(Path(str(var_file) + ".profile.json"), {"session": session["id"], "phase": target, "revision": session["revision"]})
    unit = ROOT / "IaC/live/argocd-apps" / app
    output = terragrunt(unit, "plan", "-input=false", "-no-color", "-lock-timeout=30s",
                       "-var-file=" + str(var_file), "-out=" + str(plan))
    (attempt / "plan.log").write_text(output)
    rendered = json.loads(terragrunt(unit, "show", "-json", str(plan)))
    validate_plan(rendered, desired)
    write_json(Path(str(plan) + ".n8n-permit.json"), {
        "plan_sha256": phase.digest(plan), "var_file": str(var_file),
        "before": {name: phase.markers(item) for name, item in live.items()}})
    output = terragrunt(unit, "apply", "-input=false", "-no-color", "-lock-timeout=30s", str(plan))
    (attempt / "apply.log").write_text(output)
    wait_for(lambda: application_synced(app, desired, expected_main_revision or session["revision"]), 240, f"{app} {target} reconciliation")


def application_synced(app, desired, revision):
    obj = kube("get", "application", app, "-n", "argocd")
    return ((revision is None or expected_revision(obj, revision)) and phase.markers(obj) == phase.markers(desired)
            and obj.get("status", {}).get("sync", {}).get("status") == "Synced"
            and phase.normalized_sources(obj["spec"]["sources"]) == phase.normalized_sources(desired["spec"]["sources"]))


def wait_for(predicate, seconds, label):
    deadline = time.monotonic() + seconds
    while time.monotonic() < deadline:
        if predicate():
            return
        time.sleep(2)
    raise TimeoutError(label)


def absent(name):
    return all(p["metadata"]["name"] != name for p in source_pods())


def ready(app, session):
    candidates = [p for p in source_pods() if p["metadata"]["name"].startswith(app + "-")
                  and p["metadata"]["name"] not in READERS]
    if app == "n8n":
        candidates = [p for p in candidates if not p["metadata"]["name"].startswith("n8n-postgres-")]
    return (len(candidates) == 1
            and {c["name"]: c["image"] for c in candidates[0]["spec"]["containers"]} == session["writers"][app]["images"]
            and all(s.get("ready") and s.get("restartCount", 0) == 0
                    for s in candidates[0].get("status", {}).get("containerStatuses", []))
            and bool(candidates[0].get("status", {}).get("containerStatuses")))


def verify_archive(path, kind):
    names = set()
    with tarfile.open(path, "r:") as archive:
        for item in archive:
            name = item.name.removeprefix("./").rstrip("/")
            if name in ("", "."):
                continue
            if name.startswith("/") or ".." in Path(name).parts or name in names:
                raise ValueError("unsafe or duplicate archive member")
            if not (item.isfile() or item.isdir()):
                raise ValueError("archive contains a link or special file")
            names.add(name)
            if item.isfile():
                # Consume every payload to detect truncation without extracting secrets.
                stream = archive.extractfile(item)
                count = sum(len(chunk) for chunk in iter(lambda stream=stream: stream.read(1024 * 1024), b""))
                if count != item.size:
                    raise ValueError("truncated archive member")
    required = {"config"} if kind == "n8n" else {"pgdata/PG_VERSION", "pgdata/global/pg_control", "pgdata/pg_wal"}
    if not required <= names:
        raise ValueError("archive lacks required recovery paths")
    return {"bytes": path.stat().st_size, "sha256": phase.digest(path), "members": len(names)}


def stream_archive(directory, kind, assert_fence=None):
    target = directory / (kind + ".tar")
    with target.open("xb") as stream, (directory / (kind + "-reader.log")).open("xb") as errors:
        process = subprocess.Popen(["kubectl", "--request-timeout=330s", "exec", "-n", "automation",
                                    "n8n-checkpoint-" + kind, "-c", "reader", "--", "timeout", "300",
                                    "/bin/bash", "/capture/read.sh", kind], stdout=stream, stderr=errors)
        try:
            deadline = time.monotonic() + 320
            while process.poll() is None and time.monotonic() < deadline:
                if assert_fence:
                    assert_fence()
                if shutil.disk_usage(directory).free < 128 * 1024 ** 2:
                    raise ValueError("archive reached private filesystem reserve")
                time.sleep(1)
            code = process.wait(timeout=1)
            if code != 0:
                raise ValueError("reader failed; partial archive is not accepted")
            stream.flush()
            os.fsync(stream.fileno())
        finally:
            if process.poll() is None:
                process.terminate()
                process.wait(timeout=10)
    fsync_directory(directory)
    result = verify_archive(target, kind)
    remote = re.findall(r"^archive-sha256: ([0-9a-f]{64})  -$",
                        (directory / (kind + "-reader.log")).read_text(), re.MULTILINE)
    if remote != [result["sha256"]]:
        raise ValueError("local archive differs from remote stream checksum")
    return result


class CaptureFence:
    def __init__(self, session):
        self.session, self.error, self.stop = session, None, threading.Event()
        self.last_success, self.observations = 0.0, 0
        self.thread = threading.Thread(target=self.observe, daemon=True)
        self.thread.start()

    def observe(self):
        try:
            while not self.stop.is_set():
                started = time.monotonic()
                live = phase.load_live()
                if any(not expected_revision(live[app], self.session["revision"]) for app in phase.APPS):
                    raise ValueError("Git revision changed during capture")
                if any(phase.markers(live[app])[phase.SESSION] != self.session["id"] for app in phase.APPS):
                    raise ValueError("maintenance session changed during capture")
                if phase.markers(live["n8n"])[phase.PHASE] != "stopped" or phase.markers(live["n8n-postgres"])[phase.PHASE] not in ("capture", "cold"):
                    raise ValueError("writer phase changed during capture")
                fence(self.session, list(self.session["writers"].values()), readers=True)
                if time.monotonic() - started > 45 or (self.last_success and started - self.last_success > 10):
                    raise ValueError("capture observation exceeded its continuity budget")
                self.last_success, self.observations = time.monotonic(), self.observations + 1
                self.stop.wait(2)
        except Exception as exc:  # noqa: BLE001 - Any observer failure invalidates capture.
            self.error = str(exc)

    def require_valid(self):
        if self.error or not self.observations or time.monotonic() - self.last_success > 45:
            raise ValueError("capture fence failed or expired: " + str(self.error))

    def close(self):
        self.stop.set()
        self.thread.join(timeout=50)
        self.require_valid()


def prepare(parent, talosconfig, talosctl):
    os.umask(0o077)
    parent = private_destination(parent.expanduser())
    context = run(["kubectl", "config", "current-context"]).strip()
    server = run(["kubectl", "config", "view", "--minify", "-o", "jsonpath={.clusters[0].cluster.server}"]).strip()
    if server != "https://10.1.0.199:6443":
        raise ValueError("select the existing direct homelab Kubernetes context before preparation")
    if shutil.disk_usage(parent).free < 1024 ** 3:
        raise ValueError("at least1GiB free required; larger actual sources need additional room")
    run(["git", "diff", "--exit-code", "HEAD"], cwd=ROOT)
    revision = run(["git", "rev-parse", "HEAD"], cwd=ROOT).strip()
    if run(["git", "rev-parse", "origin/main"], cwd=ROOT).strip() != revision:
        raise ValueError("prepare from freshly fetched current main")
    bases = {}
    for app in phase.APPS:
        bases[app] = json.loads(run(["terragrunt", "--log-disable", "render", "--json", "--write=false"],
                                   cwd=ROOT / "IaC/live/argocd-apps" / app, timeout=60))["inputs"]["manifest"]
    live = phase.load_live()
    require_capture_ready(live, revision)
    pods, writers = source_pods(), {}
    for app, claim in CLAIMS.items():
        candidates = [p for p in pods if any(v.get("persistentVolumeClaim", {}).get("claimName") == claim for v in p["spec"]["volumes"])]
        if len(candidates) != 1 or not all(s.get("ready") for s in candidates[0]["status"]["containerStatuses"]):
            raise ValueError("exactly one healthy original writer required for each claim")
        writers[app] = pod_identity(candidates[0])
    nodes = node_metadata()
    check_nodes(nodes, nodes)
    session = {"id": uuid.uuid4().hex, "revision": revision, "prepared_at": now(),
               "talosconfig": str(talosconfig.expanduser().resolve(strict=True)), "bases": bases,
               "writers": writers, "nodes": nodes, "claims": claim_metadata(),
               "talosctl": str(talosctl.expanduser().resolve(strict=True)), "kube_context": context, "kube_server": server}
    version = run([session["talosctl"], "version", "--client"])
    if re.findall(r"^\s*Tag:\s*(\S+)\s*$", version, re.MULTILINE) != ["v1.11.3"]:
        raise ValueError("use the cluster-matching Talos client1.11.3")
    talos_fence(session, [{"name": name} for name in READERS])
    directory = Path(tempfile.mkdtemp(prefix="n8n-pair-", dir=parent))
    write_json(directory / "session.json", session)
    print(directory)


def require_session(live, session):
    if any(phase.markers(item)[phase.PHASE] != "normal" and phase.markers(item)[phase.SESSION] != session["id"]
           for item in live.values()):
        raise ValueError("another checkpoint session is active")
    observed = tuple(phase.markers(live[app])[phase.PHASE] for app in phase.APPS)
    supported = {("normal", "normal"), ("stopped", "normal"), ("stopped", "cold"),
                 ("stopped", "capture"), ("stopped", "recovery-cold"), ("stopped", "recovered"),
                 ("recovered", "recovered"), ("recovered", "normal")}
    if observed not in supported:
        raise ValueError("unsupported checkpoint phase pair: " + repr(observed))


def resume(directory, session):
    """Return service at the already-reviewed revision without a GitHub fetch."""
    live = phase.load_live()
    require_session(live, session)
    app_phase = phase.markers(live["n8n"])[phase.PHASE]
    pg_phase = phase.markers(live["n8n-postgres"])[phase.PHASE]
    if pg_phase == "capture":
        apply_phase(directory, session, "n8n-postgres", "recovery-cold")
        pg_phase = "recovery-cold"
    if pg_phase in ("cold", "recovery-cold"):
        wait_for(lambda: all(absent(name) for name in READERS), 120, "reader removal")
        wait_for(lambda: all(absent(x["name"]) for x in session["writers"].values()), 150, "old writer removal")
        fence(session, list(session["writers"].values()))
        talos_fence(session, [{"name": name} for name in READERS])
        apply_phase(directory, session, "n8n-postgres", "recovered")
    elif pg_phase == "normal" and app_phase == "stopped":
        # App-only stop failures still pin the original, running database first.
        apply_phase(directory, session, "n8n-postgres", "recovered")
    wait_for(lambda: ready("n8n-postgres", session), 300, "PostgreSQL SQL readiness")
    live = phase.load_live()
    if phase.markers(live["n8n"])[phase.PHASE] == "stopped":
        wait_for(lambda: absent(session["writers"]["n8n"]["name"]), 150, "old n8n writer removal")
        fence(session, [session["writers"]["n8n"]], check_survivors=False)
        apply_phase(directory, session, "n8n", "recovered")
    wait_for(lambda: ready("n8n", session), 300, "n8n database-aware readiness")
    write_json(directory / ("resumed-" + uuid.uuid4().hex + ".json"), {"at": now(), "session": session["id"],
               "revision": session["revision"], "next_step": "unpin after reachable main source verification"})


def unpin(directory, session):
    """After service recovery, verify main before removing temporary SHA pins."""
    live = phase.load_live()
    require_session(live, session)
    if all(phase.markers(item)[phase.PHASE] == "normal" for item in live.values()):
        write_json(directory / ("unpinned-" + uuid.uuid4().hex + ".json"), {"at": now(), "session": session["id"],
                   "already_normal": True})
        return
    if any(phase.markers(item)[phase.PHASE] not in ("normal", "recovered") for item in live.values()):
        raise ValueError("resume service before unpinning")
    if any(not ready(app, session) for app in phase.APPS):
        raise ValueError("both original workloads must be ready before unpinning")
    run(["git", "fetch", "origin", "main"], cwd=ROOT, timeout=60)
    run(["git", "diff", "--exit-code", session["revision"], "origin/main", "--",
         "clusters/homelab/apps/n8n", "clusters/homelab/apps/n8n-postgres",
         "clusters/homelab/apps/n8n-maintenance", "clusters/homelab/apps/n8n-postgres-cold",
         "clusters/homelab/apps/n8n-postgres-capture"], cwd=ROOT)
    main_revision = run(["git", "rev-parse", "origin/main"], cwd=ROOT).strip()
    for app in reversed(phase.APPS):
        if phase.markers(phase.load_live()[app])[phase.PHASE] == "recovered":
            apply_phase(directory, session, app, "normal", expected_main_revision=main_revision)
            wait_for(lambda app=app: ready(app, session), 300, app + " readiness after unpin")
    write_json(directory / ("unpinned-" + uuid.uuid4().hex + ".json"), {"at": now(), "session": session["id"],
               "main_revision": main_revision})


def capture(directory, session):
    watches, observer = [], None
    safe_to_resume = True
    live = phase.load_live()
    require_capture_ready(live, session["revision"])
    current = {p["metadata"]["name"]: p for p in source_pods()}
    for writer in session["writers"].values():
        pod = current.get(writer["name"])
        if not pod or pod_identity(pod)["uid"] != writer["uid"] or pod_identity(pod)["containers"] != writer["containers"] or pod_identity(pod)["mounts"] != writer["mounts"]:
            raise ValueError("prepared writer identity changed; prepare again")
    fence(session, [])
    try:
        for app in phase.APPS:
            watch = PodExitWatch(session["writers"][app])
            watches.append(watch)
            wait_for(lambda watch=watch: watch.observed or watch.error is not None, 10, "initial pod observation")
            if watch.error:
                raise ValueError("source pod watch failed before phase change")
            apply_phase(directory, session, app, "stopped" if app == "n8n" else "cold")
            wait_for(lambda app=app: absent(session["writers"][app]["name"]), 150, app + " shutdown")
            wait_for(lambda watch=watch: watch.error is not None or set(watch.terminal) == set(watch.writer["containers"]),
                     10, "terminal status delivery")
            watch.require_clean()
            stopped = [session["writers"][name] for name in phase.APPS[:len(watches)]]
            fence(session, stopped)
            write_json(directory / (app + "-shutdown.json"), watch.terminal)
        apply_phase(directory, session, "n8n-postgres", "capture")
        wait_for(lambda: all(any(p["metadata"]["name"] == name and p.get("status", {}).get("phase") == "Running"
                                for p in source_pods()) for name in READERS), 120, "readers")
        observer = CaptureFence(session)
        wait_for(lambda: observer.observations > 0 or observer.error is not None, 50, "first fence")
        observer.require_valid()
        archives = {}
        for kind in ("n8n", "postgres"):
            archives[kind] = stream_archive(directory, kind, assert_fence=observer.require_valid)
            observer.require_valid()
        apply_phase(directory, session, "n8n-postgres", "cold")
        wait_for(lambda: all(absent(name) for name in READERS), 120, "reader removal")
        fence(session, list(session["writers"].values()))
        talos_fence(session, [{"name": name} for name in READERS])
        observer.close()
        observer = None
        write_json(directory / "paired-capture.json", {"session": session["id"], "at": now(),
                   "revision": session["revision"], "archives": archives,
                   "proof": "cold pair captured; application restore unverified"})
    except CommandCleanupError:
        safe_to_resume = False
        raise
    finally:
        if observer:
            observer.stop.set()
            observer.thread.join(timeout=50)
        try:
            for watch in watches:
                watch.close()
        finally:
            if safe_to_resume:
                resume(directory, session)


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    sub = parser.add_subparsers(dest="command", required=True)
    prep = sub.add_parser("prepare")
    prep.add_argument("--destination", type=Path, required=True)
    prep.add_argument("--talosconfig", type=Path, required=True)
    prep.add_argument("--talosctl", type=Path, required=True)
    for command in ("capture", "resume", "unpin"):
        child = sub.add_parser(command)
        child.add_argument("--session-directory", type=Path, required=True)
    args = parser.parse_args()
    os.umask(0o077)
    if args.command == "prepare":
        prepare(args.destination, args.talosconfig, args.talosctl)
        return
    directory = private_destination(args.session_directory.expanduser())
    session = json.loads((directory / "session.json").read_text())
    if (run(["kubectl", "config", "current-context"]).strip() != session["kube_context"]
            or run(["kubectl", "config", "view", "--minify", "-o", "jsonpath={.clusters[0].cluster.server}"]).strip() != session["kube_server"]):
        raise ValueError("restore the prepared Kubernetes context before continuing")
    if run(["git", "rev-parse", "HEAD"], cwd=ROOT).strip() != session["revision"]:
        raise ValueError("use the exact prepared repository revision")
    run(["git", "diff", "--exit-code", "HEAD"], cwd=ROOT)
    if args.command == "capture":
        if any(directory.glob("*-shutdown.json")) or (directory / "paired-capture.json").exists():
            raise ValueError("session already started; resume it and prepare a new capture")
        capture(directory, session)
    elif args.command == "resume":
        resume(directory, session)
    else:
        unpin(directory, session)


if __name__ == "__main__":
    main()
