#!/usr/bin/env python3
"""Adopt already-complete Deluge files and force a hash recheck."""

import argparse
import os
import sys
import time

import libtorrent as lt
from deluge.ui.client import client
from twisted.internet import defer, reactor, task


CONFIG_DIR = "/config"
STATE_DIR = os.path.join(CONFIG_DIR, "state")
COMPLETE_DIR = os.path.realpath("/downloads/complete")
STATUS_FIELDS = ["is_finished", "save_path", "state"]


def files_complete(torrent_id):
    metadata_path = os.path.join(STATE_DIR, torrent_id + ".torrent")
    with open(metadata_path, "rb") as metadata_file:
        files = lt.torrent_info(lt.bdecode(metadata_file.read())).files()

    total_bytes = 0
    for index in range(files.num_files()):
        relative_path = files.file_path(index)
        expected_size = files.file_size(index)
        target_path = os.path.realpath(os.path.join(COMPLETE_DIR, relative_path))
        if os.path.commonpath((COMPLETE_DIR, target_path)) != COMPLETE_DIR:
            raise ValueError("torrent metadata resolves outside /downloads/complete")
        if not os.path.isfile(target_path) or os.path.getsize(target_path) != expected_size:
            return False, 0
        total_bytes += expected_size
    return True, total_bytes


def local_auth():
    with open(os.path.join(CONFIG_DIR, "auth"), encoding="utf-8") as auth_file:
        line = next(
            line for line in auth_file if line.strip() and not line.startswith("#")
        )
    username, password, _ = line.rstrip().split(":", 2)
    return username, password


@defer.inlineCallbacks
def monitor_rechecks(candidates, timeout):
    deadline = time.monotonic() + timeout
    saw_checking = False
    quiet_polls = 0

    while True:
        statuses = yield client.core.get_torrents_status({}, STATUS_FIELDS)
        missing = [
            torrent_id for torrent_id in candidates if torrent_id not in statuses
        ]
        if missing:
            raise RuntimeError("a selected torrent disappeared during its hash check")

        downloading = [
            torrent_id
            for torrent_id in candidates
            if not statuses[torrent_id]["is_finished"]
            and statuses[torrent_id]["state"] == "Downloading"
        ]
        if downloading:
            yield client.core.pause_torrent(downloading)

        checking = [
            torrent_id
            for torrent_id in candidates
            if statuses[torrent_id]["state"] == "Checking"
        ]
        if checking:
            saw_checking = True
            quiet_polls = 0
        elif saw_checking:
            quiet_polls += 1

        if saw_checking and quiet_polls >= 3:
            break
        if time.monotonic() >= deadline:
            raise TimeoutError("timed out waiting for Deluge hash checks")
        yield task.deferLater(reactor, 5, lambda: None)

    statuses = yield client.core.get_torrents_status({}, STATUS_FIELDS)
    verified = [
        torrent_id
        for torrent_id in candidates
        if statuses[torrent_id]["is_finished"]
    ]
    incomplete = [
        torrent_id
        for torrent_id in candidates
        if not statuses[torrent_id]["is_finished"]
    ]
    if incomplete:
        yield client.core.pause_torrent(incomplete)
    if verified:
        yield client.core.resume_torrent(verified)
    print(
        f"Hash checks complete: verified {len(verified)} entries; "
        f"paused {len(incomplete)} incomplete entries"
    )


@defer.inlineCallbacks
def reconcile(mode, timeout):
    username, password = local_auth()
    yield client.connect("127.0.0.1", 58846, username, password)
    try:
        statuses = yield client.core.get_torrents_status({}, STATUS_FIELDS)
        if mode == "monitor":
            candidates = [
                torrent_id
                for torrent_id, status in statuses.items()
                if not status["is_finished"]
                and os.path.realpath(status["save_path"]) == COMPLETE_DIR
            ]
            print(f"Guarding {len(candidates)} incomplete complete-root entries")
            if candidates:
                yield monitor_rechecks(candidates, timeout)
            return

        candidates = []
        total_bytes = 0
        skipped = 0
        for torrent_id, status in statuses.items():
            if status["is_finished"]:
                continue
            complete, torrent_bytes = files_complete(torrent_id)
            if complete:
                candidates.append(torrent_id)
                total_bytes += torrent_bytes
            else:
                skipped += 1

        print(
            f"Found {len(candidates)} incomplete entries with "
            f"{total_bytes} exact-size bytes under /downloads/complete; "
            f"skipped {skipped}"
        )
        if mode == "dry-run" or not candidates:
            if candidates:
                print("Dry run only; rerun with --apply to adopt and hash-check them")
            return

        yield client.core.pause_torrent(candidates)
        move_ids = [
            torrent_id
            for torrent_id in candidates
            if os.path.realpath(statuses[torrent_id]["save_path"]) != COMPLETE_DIR
        ]
        if move_ids:
            yield client.core.move_storage(move_ids, COMPLETE_DIR)
            deadline = time.monotonic() + timeout
            while True:
                current = yield client.core.get_torrents_status({}, ["save_path"])
                pending = [
                    torrent_id
                    for torrent_id in move_ids
                    if os.path.realpath(current[torrent_id]["save_path"]) != COMPLETE_DIR
                ]
                if not pending:
                    break
                if time.monotonic() >= deadline:
                    raise TimeoutError("timed out waiting for Deluge storage moves")
                yield task.deferLater(reactor, 2, lambda: None)

        yield client.core.force_recheck(candidates)
        yield client.core.resume_torrent(candidates)
        print(f"Started guarded hash recheck for {len(candidates)} entries")
        yield monitor_rechecks(candidates, timeout)
    finally:
        client.disconnect()


def main():
    parser = argparse.ArgumentParser()
    mode = parser.add_mutually_exclusive_group()
    mode.add_argument("--apply", action="store_true")
    mode.add_argument("--monitor", action="store_true")
    parser.add_argument("--timeout", type=int, default=7200)
    args = parser.parse_args()
    selected_mode = (
        "apply" if args.apply else "monitor" if args.monitor else "dry-run"
    )

    exit_code = [0]
    result = reconcile(selected_mode, args.timeout)

    def failed(failure):
        print(failure.value, file=sys.stderr)
        exit_code[0] = 1

    result.addErrback(failed)
    result.addBoth(lambda _: reactor.stop())
    reactor.run()
    raise SystemExit(exit_code[0])


if __name__ == "__main__":
    main()
