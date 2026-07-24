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
def verify_one(torrent_id, deadline):
    saw_checking = False

    yield client.core.pause_torrent([torrent_id])
    yield client.core.force_recheck([torrent_id])
    yield client.core.resume_torrent([torrent_id])
    while True:
        statuses = yield client.core.get_torrents_status({}, STATUS_FIELDS)
        if torrent_id not in statuses:
            raise RuntimeError("a selected torrent disappeared during its hash check")
        status = statuses[torrent_id]

        if status["is_finished"]:
            yield client.core.resume_torrent([torrent_id])
            return True
        if status["state"] == "Checking":
            saw_checking = True
        elif status["state"] in ("Downloading", "Error") or saw_checking:
            yield client.core.pause_torrent([torrent_id])
            return False
        if time.monotonic() >= deadline:
            yield client.core.pause_torrent([torrent_id])
            raise TimeoutError("timed out waiting for Deluge hash checks")
        yield task.deferLater(reactor, 1, lambda: None)


@defer.inlineCallbacks
def reconcile(apply, prune_skipped, timeout):
    username, password = local_auth()
    yield client.connect("127.0.0.1", 58846, username, password)
    try:
        statuses = yield client.core.get_torrents_status({}, STATUS_FIELDS)
        candidates = []
        total_bytes = 0
        skipped = []
        for torrent_id, status in statuses.items():
            if status["is_finished"]:
                continue
            complete, torrent_bytes = files_complete(torrent_id)
            if complete:
                candidates.append(torrent_id)
                total_bytes += torrent_bytes
            else:
                skipped.append(torrent_id)

        print(
            f"Found {len(candidates)} incomplete entries with "
            f"{total_bytes} exact-size bytes under /downloads/complete; "
            f"skipped {len(skipped)}"
        )
        if prune_skipped:
            unsafe = [
                torrent_id
                for torrent_id in skipped
                if statuses[torrent_id]["state"] != "Paused"
                or os.path.realpath(statuses[torrent_id]["save_path"]) != COMPLETE_DIR
            ]
            if unsafe:
                raise RuntimeError(
                    "refusing to prune skipped entries unless all are paused "
                    "under /downloads/complete"
                )
            errors = yield client.core.remove_torrents(skipped, False)
            if errors:
                raise RuntimeError(
                    f"failed to remove {len(errors)} of {len(skipped)} entries"
                )
            print(
                f"Removed {len(skipped)} skipped catalog entries "
                "without deleting data"
            )
            return

        if not apply or not candidates:
            if candidates:
                print("Dry run only; rerun with --apply to adopt and hash-check them")
            return

        deadline = time.monotonic() + timeout
        yield client.core.pause_torrent(candidates)
        move_ids = [
            torrent_id
            for torrent_id in candidates
            if os.path.realpath(statuses[torrent_id]["save_path"]) != COMPLETE_DIR
        ]
        if move_ids:
            yield client.core.move_storage(move_ids, COMPLETE_DIR)
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

        verified = 0
        incomplete = 0
        for index, torrent_id in enumerate(candidates, start=1):
            print(
                f"Hash-checking entry {index} of {len(candidates)}",
                flush=True,
            )
            if (yield verify_one(torrent_id, deadline)):
                verified += 1
            else:
                incomplete += 1
        print(
            f"Hash checks complete: verified {verified} entries; "
            f"paused {incomplete} incomplete entries"
        )
    finally:
        client.disconnect()


def main():
    parser = argparse.ArgumentParser()
    mode = parser.add_mutually_exclusive_group()
    mode.add_argument("--apply", action="store_true")
    mode.add_argument("--prune-skipped", action="store_true")
    parser.add_argument("--timeout", type=int, default=7200)
    args = parser.parse_args()

    exit_code = [0]
    result = reconcile(args.apply, args.prune_skipped, args.timeout)

    def failed(failure):
        print(failure.value, file=sys.stderr)
        exit_code[0] = 1

    result.addErrback(failed)
    result.addBoth(lambda _: reactor.stop())
    reactor.run()
    raise SystemExit(exit_code[0])


if __name__ == "__main__":
    main()
