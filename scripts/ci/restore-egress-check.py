#!/usr/bin/env python3
"""Build and test the exact Linux image with real networking enabled; never publish."""
import array
from contextlib import contextmanager
from dataclasses import dataclass
import json
import os
from pathlib import Path
import platform
import re
import select
import shutil
import socket
import socketserver
import subprocess
import tempfile
import threading

ROOT = Path(__file__).resolve().parents[2]
LAUNCHER = "/usr/local/bin/restore-no-network"


def run(*command, **kwargs):
    return subprocess.run(command, check=True, text=True, timeout=600, **kwargs)


class TCP(socketserver.BaseRequestHandler):
    def handle(self):
        data = self.request.recv(1)
        self.server.received += 1
        self.request.sendall(data)


class UDP(socketserver.BaseRequestHandler):
    def handle(self):
        data, connection = self.request
        self.server.received += 1
        connection.sendto(data, self.client_address)


def rights_case(common, tag, scratch, method, expected, state):
    """A real unfiltered Unix peer offers an INET FD after receiver startup."""
    path = scratch / "broker.sock"
    errors = []
    delivered = []
    with socket.socket(socket.AF_UNIX, socket.SOCK_STREAM) as broker, \
            socket.socket(socket.AF_INET, socket.SOCK_STREAM) as listener, \
            socket.socket(socket.AF_INET, socket.SOCK_STREAM) as donor:
        broker.bind(str(path))
        path.chmod(0o666)  # The synthetic container client runs as UID65534.
        broker.listen(1)
        broker.settimeout(10)
        listener.bind(("127.0.0.1", 0))
        listener.listen(1)
        listener.settimeout(5)
        if state == "connected":
            donor.connect(listener.getsockname())

        def offer():
            try:
                connection, _ = broker.accept()
                with connection:
                    connection.settimeout(5)
                    assert connection.recv(1) == b"R", "receiver did not finish startup"
                    rights = array.array("i", [donor.fileno()])
                    assert connection.sendmsg([b"x"], [(socket.SOL_SOCKET, socket.SCM_RIGHTS, rights)]) == 1
                    delivered.append(True)
            except Exception as error:
                errors.append(error)

        thread = threading.Thread(target=offer, daemon=True)
        thread.start()
        try:
            container = [*common, "--mount", f"type=bind,src={path},dst=/tests/broker.sock,readonly"]
            receiver = ["rights-receiver", method, expected, state, str(listener.getsockname()[1])]
            if expected == "allow":
                run(*container, "--entrypoint", "/tests/probe", tag, *receiver)
            else:
                run(*container, tag, "/tests/probe", *receiver)
            thread.join(10)
            assert not thread.is_alive() and not errors and delivered == [True], "broker delivery failed"
            if expected == "allow" or state == "connected":
                peer, _ = listener.accept()
                with peer:
                    if expected == "allow":
                        peer.settimeout(5)
                        assert peer.recv(1) == b"n", "imported positive-control socket was unusable"
                    else:
                        assert not select.select([peer], [], [], 0)[0], "filtered receiver used offered INET socket"
            else:
                assert not select.select([listener], [], [], 0)[0], "filtered receiver connected offered INET socket"
        finally:
            thread.join(10)
            path.unlink(missing_ok=True)


@dataclass(frozen=True)
class TestedImage:
    tag: str
    image_id: str
    source_sha: str


@contextmanager
def verified_image():
    if platform.system() != "Linux" or platform.machine() != "x86_64":
        raise SystemExit("Required image tests need native x86_64 Linux and Docker; not verified on this host")
    source = run("git", "rev-parse", "HEAD", cwd=ROOT, capture_output=True).stdout.strip()
    if not re.fullmatch(r"[0-9a-f]{40}", source):
        raise RuntimeError("Invalid source commit")
    run("docker", "info", stdout=subprocess.DEVNULL)
    built = run("nix", "build", ".#restore-egress-tools", "--no-link", "--print-out-paths",
                cwd=ROOT, capture_output=True).stdout.strip()
    tools = Path(built) / "bin"
    with tempfile.TemporaryDirectory(prefix="restore-egress-") as directory:
        scratch = Path(directory)
        context = scratch / "image"
        context.mkdir()
        shutil.copy2(ROOT / "images/postgres-restore-egress/Dockerfile", context / "Dockerfile")
        shutil.copy2(tools / "restore-no-network", context / "restore-no-network")
        # File modes/times and locked compiler/base inputs are deterministic.
        os.utime(context / "Dockerfile", (1, 1))
        os.utime(context / "restore-no-network", (1, 1))
        tag = f"homelab-restore-egress-test:{os.getpid()}"
        try:
            iid_file = scratch / "image-id"
            run("docker", "build", "--no-cache", "--platform", "linux/amd64", "--build-arg",
                "SOURCE_DATE_EPOCH=1", "--label", f"org.opencontainers.image.revision={source}",
                "--label", "org.opencontainers.image.source=https://github.com/Stuhlmuller/homelab",
                "--iidfile", str(iid_file), "--tag", tag, str(context))
            image_id = iid_file.read_text().strip()
            if not re.fullmatch(r"sha256:[0-9a-f]{64}", image_id):
                raise RuntimeError("Docker build did not return an immutable image ID")
            info = json.loads(run("docker", "image", "inspect", image_id, capture_output=True).stdout)[0]
            labels = info["Config"]["Labels"]
            if (info["Id"] != image_id
                    or info["Architecture"] != "amd64" or info["Os"] != "linux"
                    or labels.get("org.opencontainers.image.revision") != source
                    or labels.get("org.opencontainers.image.source") != "https://github.com/Stuhlmuller/homelab"):
                raise RuntimeError("Tested image/source binding failed")
            probe = scratch / "probe"
            shutil.copy2(tools / "restore-network-probe", probe)
            # Docker bind mounts must be traversable by UID65534.
            scratch.chmod(0o755)
            probe.chmod(0o555)
            common = ["docker", "run", "--rm", "--network", "bridge", "--user", "65534:65534",
                      "--cap-drop", "ALL", "--security-opt", "no-new-privileges:true",
                      "--read-only", "--pids-limit", "64", "--memory", "512m", "--cpus", "1",
                      "--tmpfs", "/work:rw,nosuid,nodev,size=128m,uid=65534,gid=65534,mode=0700",
                      "--mount", f"type=bind,src={probe},dst=/tests/probe,readonly"]
            # No seccomp override in successful cases: Docker's RuntimeDefault remains in force.
            gateway = run("docker", "network", "inspect", "bridge", "--format",
                          "{{(index .IPAM.Config 0).Gateway}}", capture_output=True).stdout.strip()
            with socketserver.TCPServer(("0.0.0.0", 0), TCP) as tcp, \
                    socketserver.UDPServer(("0.0.0.0", 0), UDP) as udp:
                for server in (tcp, udp):
                    server.received = 0
                    threading.Thread(target=server.serve_forever, daemon=True).start()
                try:
                    # Positive control uses only synthetic probes, no backup data.
                    run(*common, "--entrypoint", "/tests/probe", image_id, "positive", gateway,
                        str(tcp.server_address[1]), str(udp.server_address[1]))
                    assert (tcp.received, udp.received) == (1, 1)
                    for mode in ("denied", "inherit", "relax", "alternate-abi"):
                        run(*common, image_id, "/tests/probe", mode)
                    for mode in ("inherited-fd", "socket-stdio", "anonymous-stdio"):
                        run(*common, "--entrypoint", "/tests/probe", image_id, mode, LAUNCHER)
                    for state in ("unconnected", "connected"):
                        for method in ("recvmsg", "recvmmsg"):
                            rights_case(common, image_id, scratch, method, "allow", state)
                            rights_case(common, image_id, scratch, method, "deny", state)
                        for method in ("read", "recvfrom"):
                            rights_case(common, image_id, scratch, method, "discard", state)
                    sql_test = ROOT / "scripts/ci/restore-egress/postgres.sh"
                    run(*common, "--mount", f"type=bind,src={sql_test},dst=/tests/postgres.sh,readonly",
                        image_id, "/bin/sh", "/tests/postgres.sh")
                    assert (tcp.received, udp.received) == (1, 1), "filtered tests sent network data"
                finally:
                    tcp.shutdown()
                    udp.shutdown()
            # Fault injection: deny filter loading; the command sentinel must never run.
            for denied_call, message in (("seccomp", "cannot install filter"),
                                         ("socketpair", "Unix socket self-test failed")):
                fault = scratch / "fault.json"
                fault.write_text(json.dumps({"defaultAction": "SCMP_ACT_ALLOW", "syscalls": [
                    {"names": [denied_call], "action": "SCMP_ACT_ERRNO", "errnoRet": 1}
                ]}))
                failed = subprocess.run([*common, "--security-opt", f"seccomp={fault}", image_id,
                                         "/bin/echo", "UNSAFE_COMMAND_EXECUTED"], text=True,
                                        capture_output=True, timeout=60, check=False)
                assert failed.returncode == 1, failed.stderr
                assert message in failed.stderr
                assert "UNSAFE_COMMAND_EXECUTED" not in failed.stdout
            print("Linux image gates passed: real connectivity, inherited EPERM, broker FD denial, Unix restore, fail-closed exec")
            yield TestedImage(tag, image_id, source)
        finally:
            subprocess.run(["docker", "image", "rm", tag], check=False, capture_output=True, timeout=60)


if __name__ == "__main__":
    with verified_image():
        pass
