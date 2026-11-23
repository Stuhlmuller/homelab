"""Check that Deluge can reply from the receiving transit address on both paths."""

import argparse
import json
import re
import socket
import sys
from pathlib import Path


MINIMUM_LIBTORRENT_VERSION = (1, 2, 1)
TRANSIT_CLIENT_ADDRESSES = ("172.31.61.2", "172.31.62.2")
LISTEN_PORT = 5983


def check_version(version):
    match = re.fullmatch(r"(\d+)\.(\d+)\.(\d+)(?:[.\-+][\w.\-+]+)?", version)
    if not match or tuple(map(int, match.groups())) < MINIMUM_LIBTORRENT_VERSION:
        raise RuntimeError("Active-active VPN requires libtorrent 1.2.1 or newer for per-address UDP listeners")


def check_config(path):
    try:
        text = path.read_text().lstrip()
    except FileNotFoundError:
        # Deluge uses wildcard defaults when a new installation has no configuration yet.
        return
    decoder = json.JSONDecoder()
    values, end = decoder.raw_decode(text)
    remainder = text[end:].strip()
    if remainder:
        # Deluge writes a format/version document before the settings document.
        values = json.loads(remainder)
    if not isinstance(values, dict):
        raise ValueError
    if values.get("listen_interface", "") not in ("", "0.0.0.0"):
        raise RuntimeError("Active-active VPN requires the wildcard Deluge listen_interface setting")
    if values.get("outgoing_interface", "") != "":
        raise RuntimeError("Active-active VPN requires an unset Deluge outgoing_interface setting")


def check_listeners(tcp_table, udp_table):
    expected = {
        f"{int.from_bytes(socket.inet_aton(address), sys.byteorder):08X}:{LISTEN_PORT:04X}"
        for address in TRANSIT_CLIENT_ADDRESSES
    }
    # TCP state 0A listens; UDP state 07 is an unconnected socket.
    for table, state in ((tcp_table, "0A"), (udp_table, "07")):
        lines = table.read_text().splitlines()
        actual = {fields[1] for line in lines[1:] if len(fields := line.split()) >= 4 and fields[3] == state}
        if not expected <= actual:
            raise RuntimeError("Waiting for dedicated Deluge TCP and UDP listeners on both transit addresses")


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--listeners", action="store_true")
    args = parser.parse_args()
    try:
        if args.listeners:
            check_listeners(Path("/proc/net/tcp"), Path("/proc/net/udp"))
        else:
            import libtorrent

            check_version(getattr(libtorrent, "version", ""))
            check_config(Path("/config/core.conf"))
    except RuntimeError as error:
        print(error, file=sys.stderr)
        return 1
    except (ImportError, OSError, TypeError, ValueError):
        print("Could not verify Deluge VPN compatibility", file=sys.stderr)
        return 1
    return 0


if __name__ == "__main__":
    sys.exit(main())
