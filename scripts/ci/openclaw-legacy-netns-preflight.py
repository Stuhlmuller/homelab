#!/usr/bin/env python3
"""Prove a disposable rootless network namespace has loopback and no egress."""

import errno
import fcntl
import os
from pathlib import Path
import re
import socket
import struct
import sys


MARKER = "LEGACY_NETNS_CAPABILITY_OK"
PROBES = (
    (socket.AF_INET, "10.1.0.199", 6443),
    (socket.AF_INET, "10.1.0.2", 2049),
    (socket.AF_INET, "169.254.169.254", 80),
    (socket.AF_INET, "1.1.1.1", 443),
    (socket.AF_INET6, "2001:4860:4860::8888", 443),
)


class Blocked(Exception):
    pass


def verify_namespace(parent, current, expected_uid, actual_uid, uid_map,
                     interfaces, ipv4_routes, ipv6_routes):
    if (not re.fullmatch(r"net:\[[0-9]+\]", parent) or
            not re.fullmatch(r"net:\[[0-9]+\]", current) or
            current == parent or actual_uid != expected_uid):
        raise Blocked()
    try:
        mappings = [[int(part) for part in line.split()] for line in uid_map.splitlines()]
    except ValueError as error:
        raise Blocked() from error
    if mappings != [[expected_uid, expected_uid, 1]] or interfaces != ["lo"]:
        raise Blocked()
    ipv4 = ipv4_routes.splitlines()
    if not ipv4 or not ipv4[0].startswith("Iface"):
        raise Blocked()
    if any(len(fields := line.split()) < 11 or fields[0] != "lo" for line in ipv4[1:]):
        raise Blocked()
    if any(len(fields := line.split()) < 10 or fields[-1] != "lo"
           for line in ipv6_routes.splitlines()):
        raise Blocked()


def bring_up_loopback():
    # This ioctl can change only the new namespace's loopback interface.
    interface = bytearray(40)
    interface[:3] = b"lo\0"
    with socket.socket(socket.AF_INET, socket.SOCK_DGRAM) as connection:
        fcntl.ioctl(connection.fileno(), 0x8913, interface, True)  # SIOCGIFFLAGS
        flags = struct.unpack_from("H", interface, 16)[0]
        if not flags & 0x8:  # IFF_LOOPBACK
            raise Blocked()
        struct.pack_into("H", interface, 16, flags | 0x1)  # IFF_UP
        fcntl.ioctl(connection.fileno(), 0x8914, interface, True)  # SIOCSIFFLAGS


def probe_egress(open_socket=socket.socket):
    for family, host, port in PROBES:
        try:
            with open_socket(family, socket.SOCK_STREAM) as connection:
                connection.settimeout(1)
                result = connection.connect_ex((host, port))
        except OSError as error:
            if family == socket.AF_INET6 and error.errno in (errno.EAFNOSUPPORT,
                                                            errno.EPROTONOSUPPORT):
                continue
            raise Blocked() from error
        if result != errno.ENETUNREACH:
            raise Blocked()


def probe_loopback():
    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as listener:
        listener.settimeout(2)
        listener.bind(("127.0.0.1", 0))
        listener.listen(1)
        with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as client:
            client.settimeout(2)
            client.connect(listener.getsockname())
            with listener.accept()[0]:
                pass


def snapshot(parent, expected_uid):
    verify_namespace(
        parent, os.readlink("/proc/self/ns/net"), expected_uid, os.getuid(),
        Path("/proc/self/uid_map").read_text(),
        sorted(name for _, name in socket.if_nameindex()),
        Path("/proc/net/route").read_text(),
        Path("/proc/net/ipv6_route").read_text(),
    )


def main():
    try:
        parent = os.environ["PARENT_NETNS"]
        expected_uid = int(os.environ["PARENT_UID"])
        if expected_uid != 1000:
            raise Blocked()
        snapshot(parent, expected_uid)
        bring_up_loopback()
        snapshot(parent, expected_uid)
        probe_loopback()
        probe_egress()
        snapshot(parent, expected_uid)
    except (Blocked, OSError, ValueError, KeyError):
        print("Rootless network namespace capability blocked", file=sys.stderr)
        return 1
    print(MARKER)
    return 0


if __name__ == "__main__":
    sys.exit(main())
