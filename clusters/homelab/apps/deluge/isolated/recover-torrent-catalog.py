#!/usr/bin/env python3
"""Recover Deluge's torrent catalog from intact metadata and fast-resume data."""

import datetime
import os
import pickle
import shutil
import tarfile
from pathlib import Path, PurePosixPath

import libtorrent as lt
from deluge.core.torrentmanager import TorrentManagerState, TorrentState


STATE_DIR = Path(os.environ.get("DELUGE_STATE_DIR", "/config/state"))
ARCHIVE_DIR = Path(os.environ.get("DELUGE_ARCHIVE_DIR", "/config/archive"))
CATALOG = STATE_DIR / "torrents.state"
CATALOG_BACKUP = STATE_DIR / "torrents.state.bak"
FASTRESUME = STATE_DIR / "torrents.fastresume"


def read_catalog(path):
    with path.open("rb") as state_file:
        state = pickle.load(state_file)
    torrents = list(state.torrents)
    torrent_ids = [torrent.torrent_id for torrent in torrents]
    if len(torrent_ids) != len(set(torrent_ids)):
        raise ValueError(f"{path} contains duplicate torrent IDs")
    metadata_ids = {torrent_file.stem for torrent_file in STATE_DIR.glob("*.torrent")}
    if set(torrent_ids) != metadata_ids:
        raise ValueError(
            f"{path} has {len(torrent_ids)} entries for "
            f"{len(metadata_ids)} torrent metadata files"
        )
    return state


def inspect_catalog(path):
    if not path.is_file():
        return None
    try:
        return read_catalog(path)
    except Exception as error:
        print(f"Torrent catalog {path} is invalid: {error}")
        return None


def atomic_write(source, destination):
    temporary = destination.with_name(f".{destination.name}.recovery.tmp")
    with temporary.open("wb") as output:
        if isinstance(source, Path):
            with source.open("rb") as input_file:
                shutil.copyfileobj(input_file, output)
        elif isinstance(source, bytes):
            output.write(source)
        else:
            pickle.dump(source, output, protocol=2)
        output.flush()
        os.fsync(output.fileno())
    os.replace(temporary, destination)
    directory = os.open(str(destination.parent), os.O_DIRECTORY)
    try:
        os.fsync(directory)
    finally:
        os.close(directory)


def archive_catalogs():
    timestamp = datetime.datetime.now(datetime.timezone.utc).strftime(
        "%Y%m%dT%H%M%SZ"
    )
    archive = ARCHIVE_DIR / f"torrent-catalog-recovery-{timestamp}"
    archive.mkdir(parents=True, exist_ok=True)
    for path in (CATALOG, CATALOG_BACKUP, FASTRESUME):
        if path.is_file():
            shutil.copy2(path, archive / path.name)
    print(f"Archived pre-recovery torrent catalogs at {archive}")


def decode_text(value, field):
    if isinstance(value, bytes):
        value = value.decode("utf-8")
    if not isinstance(value, str) or not value:
        raise ValueError(f"resume data has an invalid {field}")
    return value


def validated_download_path(value):
    path = PurePosixPath(decode_text(value, "save_path"))
    downloads = PurePosixPath("/downloads")
    if not path.is_absolute() or (path != downloads and downloads not in path.parents):
        raise ValueError(f"resume data save_path is outside /downloads: {path}")
    return str(path)


def decode_resume_data(data):
    encoded_resume = lt.bdecode(data)
    if not isinstance(encoded_resume, dict):
        raise ValueError("torrents.fastresume is not a dictionary")

    return {
        key.decode("ascii") if isinstance(key, bytes) else str(key): value
        for key, value in encoded_resume.items()
    }


def load_complete_resume_data(torrent_ids):
    candidates = []
    if FASTRESUME.is_file():
        candidates.append((str(FASTRESUME), FASTRESUME.read_bytes()))

    archives = sorted(
        ARCHIVE_DIR.glob("*.tar.xz"), key=lambda path: path.stat().st_mtime, reverse=True
    )
    for archive_path in archives:
        try:
            with tarfile.open(archive_path, "r:xz") as archive:
                member = next(
                    (
                        item
                        for item in archive.getmembers()
                        if Path(item.name).name == "torrents.fastresume"
                    ),
                    None,
                )
                if member is not None:
                    candidates.append(
                        (str(archive_path), archive.extractfile(member).read())
                    )
        except (OSError, tarfile.TarError) as error:
            print(f"Skipping unreadable recovery archive {archive_path}: {error}")

    for source, data in candidates:
        try:
            resume_by_id = decode_resume_data(data)
        except Exception as error:
            print(f"Skipping invalid fast-resume source {source}: {error}")
            continue
        if set(resume_by_id) == torrent_ids:
            print(f"Using complete fast-resume data from {source}")
            return resume_by_id, data

    raise ValueError(
        "torrent metadata has no complete fast-resume source; refusing partial recovery"
    )


def rebuild_catalog(torrent_files):
    torrent_ids = {path.stem for path in torrent_files}
    resume_by_id, resume_data = load_complete_resume_data(torrent_ids)

    recovered = []
    for queue, torrent_file in enumerate(torrent_files):
        torrent_id = torrent_file.stem
        metadata = lt.torrent_info(lt.bdecode(torrent_file.read_bytes()))
        if str(metadata.info_hash()) != torrent_id:
            raise ValueError(f"{torrent_file} does not match its info hash")

        resume = lt.bdecode(resume_by_id[torrent_id])
        resume_hash = resume.get(b"info-hash")
        if not isinstance(resume_hash, bytes) or resume_hash.hex() != torrent_id:
            raise ValueError(f"fast-resume data does not match {torrent_file}")

        recovered.append(
            TorrentState(
                torrent_id=torrent_id,
                filename=torrent_file.name,
                paused=bool(resume.get(b"paused", 0)),
                save_path=validated_download_path(resume.get(b"save_path")),
                sequential_download=bool(resume.get(b"sequential_download", 0)),
                file_priorities=[
                    int(priority) for priority in resume.get(b"file_priority", [])
                ],
                queue=queue,
                auto_managed=bool(resume.get(b"auto_managed", 1)),
                is_finished=bool(resume.get(b"completed_time", 0)),
                super_seeding=bool(resume.get(b"super_seeding", 0)),
            )
        )

    state = TorrentManagerState()
    state.torrents = recovered
    return state, resume_data


def main():
    current = inspect_catalog(CATALOG)
    if current is not None and current.torrents:
        print(f"Validated torrent catalog with {len(current.torrents)} entries")
        return

    torrent_files = sorted(STATE_DIR.glob("*.torrent"))
    if not torrent_files:
        if CATALOG.is_file() and current is None:
            raise ValueError("torrent catalog is invalid without recoverable metadata")
        print("No torrent metadata found; allowing Deluge to initialize its catalog")
        return

    backup = inspect_catalog(CATALOG_BACKUP)
    if backup is not None and backup.torrents:
        archive_catalogs()
        atomic_write(CATALOG_BACKUP, CATALOG)
        print(f"Restored torrent catalog backup with {len(backup.torrents)} entries")
        return

    rebuilt, resume_data = rebuild_catalog(torrent_files)
    archive_catalogs()
    atomic_write(resume_data, FASTRESUME)
    atomic_write(rebuilt, CATALOG)
    print(f"Rebuilt torrent catalog with {len(rebuilt.torrents)} entries")


if __name__ == "__main__":
    main()
