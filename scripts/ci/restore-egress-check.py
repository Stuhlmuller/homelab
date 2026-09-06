#!/usr/bin/env python3
"""Build and test the exact Linux image with real networking enabled; never publish."""
import json
import os
from pathlib import Path
import platform
import shutil
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


def main():
    if platform.system() != "Linux" or platform.machine() != "x86_64":
        raise SystemExit("Required image tests need native x86_64 Linux and Docker; not verified on this host")
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
            run("docker", "build", "--platform", "linux/amd64", "--build-arg",
                "SOURCE_DATE_EPOCH=1", "--tag", tag, str(context))
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
                    run(*common, "--entrypoint", "/tests/probe", tag, "positive", gateway,
                        str(tcp.server_address[1]), str(udp.server_address[1]))
                    assert (tcp.received, udp.received) == (1, 1)
                    for mode in ("denied", "inherit", "relax", "alternate-abi"):
                        run(*common, tag, "/tests/probe", mode)
                    for mode in ("inherited-fd", "socket-stdio", "anonymous-stdio"):
                        run(*common, "--entrypoint", "/tests/probe", tag, mode, LAUNCHER)
                    sql_test = ROOT / "scripts/ci/restore-egress/postgres.sh"
                    run(*common, "--mount", f"type=bind,src={sql_test},dst=/tests/postgres.sh,readonly",
                        tag, "/bin/sh", "/tests/postgres.sh")
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
                failed = subprocess.run([*common, "--security-opt", f"seccomp={fault}", tag,
                                         "/bin/echo", "UNSAFE_COMMAND_EXECUTED"], text=True,
                                        capture_output=True, timeout=60, check=False)
                assert failed.returncode == 1, failed.stderr
                assert message in failed.stderr
                assert "UNSAFE_COMMAND_EXECUTED" not in failed.stdout
            print("Linux image gates passed: real connectivity control, inherited EPERM, Unix restore, fail-closed exec")
        finally:
            subprocess.run(["docker", "image", "rm", tag], check=False, capture_output=True, timeout=60)


if __name__ == "__main__":
    main()
