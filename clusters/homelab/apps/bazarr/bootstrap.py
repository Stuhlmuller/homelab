#!/usr/bin/env python3
"""Configure Bazarr from mounted files; reconcile its API; back up SQLite safely."""

import argparse
from contextlib import closing
import copy
import hashlib
import json
import os
from pathlib import Path
import secrets
import sqlite3
import sys
import tarfile
import tempfile
import time
import urllib.error
import urllib.parse
import urllib.request
import xml.etree.ElementTree as ET


CONFIG = Path("/config")
PROFILE = Path("/bootstrap/profile.json")
API = "http://bazarr.media.svc.cluster.local:6767/api/"
PROVIDERS = ["gestdown", "yifysubtitles", "supersubtitles"]
# Bazarr vendors PyYAML here; its image venv installs only native dependencies.
sys.path.append("/app/bazarr/bin/libs")


def load_yaml(path):
    # PyYAML ships with the pinned Bazarr image; no runtime package installation.
    import yaml

    return yaml.safe_load(path.read_text()) or {}


def arr_key(path):
    keys = ET.parse(path).getroot().findall("ApiKey")
    if len(keys) != 1 or not keys[0].text or not keys[0].text.strip():
        raise ValueError("Expected exactly one nonempty Arr API key")
    return keys[0].text.strip()


def desired_config(current, keys):
    result = copy.deepcopy(current)
    general = result.setdefault("general", {})
    general.update({
        "ip": "0.0.0.0", "port": 6767, "base_url": "", "auto_update": False,
        "debug": False, "use_embedded_subs": True, "utf8_encode": True,
        "enabled_providers": PROVIDERS, "multithreading": False,
        "path_mappings": [], "path_mappings_movie": [],
        "wanted_search_frequency": 6, "wanted_search_frequency_movie": 6,
        "hi_extension": "sdh", "minimum_score": 90, "minimum_score_movie": 70,
    })
    # Fresh installations stay idle until the PostSync hook creates the profile.
    # Preserve API-persisted enablement across ordinary pod restarts.
    for app, port in (("sonarr", 8989), ("radarr", 7878)):
        general.setdefault(f"use_{app}", False)
        result.setdefault(app, {}).update({
            "ip": f"{app}.media.svc.cluster.local", "port": port,
            "base_url": "/", "ssl": False, "apikey": keys[app],
            "only_monitored": False,
        })
    auth = result.setdefault("auth", {})
    auth.setdefault("apikey", secrets.token_hex(32))
    # Human access is authenticated by the private Octelium Service.
    auth["type"] = None
    general.setdefault("flask_secret_key", secrets.token_hex(32))
    return result


def configure():
    import yaml

    path = CONFIG / "config/config.yaml"
    path.parent.mkdir(parents=True, exist_ok=True)
    current = load_yaml(path) if path.exists() else {}
    keys = {app: arr_key(Path(f"/arr/{app}/config.xml")) for app in ("sonarr", "radarr")}
    result = desired_config(current, keys)
    temporary = path.with_suffix(".partial")
    temporary.write_text(yaml.safe_dump(result, sort_keys=False))
    temporary.chmod(0o600)
    temporary.replace(path)
    print("Bazarr configuration prepared from mounted Arr credentials")


def request(url, key, fields=None):
    data = urllib.parse.urlencode(fields, doseq=True).encode() if fields is not None else None
    req = urllib.request.Request(url, data=data, headers={"X-API-KEY": key})
    try:
        with urllib.request.urlopen(req, timeout=90) as response:
            payload = response.read()
            return json.loads(payload) if payload else None
    except urllib.error.HTTPError as error:
        # Never print response bodies, request headers, URLs, or configuration.
        raise RuntimeError(f"Application API returned HTTP {error.code}") from None
    except (urllib.error.URLError, TimeoutError):
        raise RuntimeError("Application API unavailable") from None


def merged_profiles(existing, desired):
    for profile in existing:
        if profile["profileId"] == desired["profileId"] and profile["name"] != desired["name"]:
            raise ValueError("Managed language profile ID already belongs to another profile")
    # Bazarr deletes omitted profiles, so always include every unrelated profile.
    return [profile for profile in existing if profile["profileId"] != desired["profileId"]] + [desired]


def api_config():
    return load_yaml(CONFIG / "config/config.yaml")


def library(config):
    libraries = {}
    for app, endpoint in (("sonarr", "series"), ("radarr", "movie")):
        settings = config[app]
        url = f"http://{settings['ip']}:{settings['port']}/api/v3/{endpoint}"
        libraries[app] = request(url, settings["apikey"])
    return libraries


def search_missing(key, timeout=900):
    """Require actual queue completion; scheduling a task alone returns HTTP 204."""
    if timeout <= 0:
        raise RuntimeError("Initial subtitle search deadline expired")
    deadline = time.monotonic() + timeout
    jobs = request(API + "system/jobs", key)["data"]
    old_ids = {job["job_id"] for job in jobs if job["status"] not in ("pending", "running")}
    pending = {"series", "movies"}
    for kind in sorted(pending):
        name = f"Searching for missing {kind} subtitles"
        if not any(job["job_name"] == name and job["status"] in ("pending", "running") for job in jobs):
            request(API + "system/tasks", key, {"taskid": f"wanted_search_missing_subtitles_{kind}"})
    while pending:
        for job in request(API + "system/jobs", key)["data"]:
            if job["job_id"] in old_ids:
                continue
            for kind in tuple(pending):
                names = (f"Searching for missing {kind} subtitles", f"Searched for missing {kind} subtitles")
                if job["job_name"] not in names:
                    continue
                if job["status"] == "failed" or job.get("progress_message") == "All providers throttled":
                    raise RuntimeError("Initial subtitle search failed or all providers were throttled")
                if job["status"] == "completed":
                    pending.remove(kind)
        if not pending:
            return
        if time.monotonic() >= deadline:
            raise RuntimeError("Initial subtitle search did not complete before the deadline")
        time.sleep(2)


def reconcile():
    """Keep Argo's PostSync hook independent of library/provider processing time."""
    config = api_config()
    key = config["auth"]["apikey"]
    profile = json.loads(PROFILE.read_text())
    existing = request(API + "system/languages/profiles", key)
    profiles = merged_profiles(existing, profile)
    fields = [
        ("languages-enabled", "en"), ("languages-profiles", json.dumps(profiles)),
        ("settings-general-use_sonarr", "true"), ("settings-general-use_radarr", "true"),
        ("settings-general-serie_default_enabled", "true"),
        ("settings-general-movie_default_enabled", "true"),
        ("settings-general-serie_default_profile", str(profile["profileId"])),
        ("settings-general-movie_default_profile", str(profile["profileId"])),
    ]
    # Preserve enabled languages used by profiles the operator created separately.
    for language in sorted({item["language"] for entry in profiles for item in entry["items"]} - {"en"}):
        fields.append(("languages-enabled", language))
    request(API + "system/settings", key, fields)
    for task in ("update_series", "update_movies"):
        request(API + "system/tasks", key, {"taskid": task})
    print("Bazarr profile/defaults configured; library imports scheduled; run finish-setup for acceptance")


def finish_setup(timeout=1800):
    """Finish import and first searches outside Argo's bounded sync operation."""
    if timeout <= 0:
        raise ValueError("Setup timeout must be positive")
    deadline = time.monotonic() + timeout
    config = api_config()
    key = config["auth"]["apikey"]
    profile_bytes = PROFILE.read_bytes()
    profile = json.loads(profile_bytes)
    revision = hashlib.sha256(profile_bytes).hexdigest()
    profiles = request(API + "system/languages/profiles", key)
    current = next((item for item in profiles if item["profileId"] == profile["profileId"]), {})
    if any(current.get(field) != value for field, value in profile.items()):
        raise RuntimeError("Managed profile is not reconciled; complete the PostSync hook first")
    expected = library(config)
    series_ids = {item["id"] for item in expected["sonarr"]}
    movie_ids = {item["id"] for item in expected["radarr"] if item.get("hasFile")}
    episode_count = sum(item.get("statistics", {}).get("episodeFileCount", 0) for item in expected["sonarr"])
    import_names = {f"{state} {kind} with {app}" for state in ("Syncing", "Synced")
                    for kind, app in (("series", "Sonarr"), ("movies", "Radarr"))}
    while True:
        series = request(API + "series", key)["data"]
        movies = request(API + "movies", key)["data"]
        jobs = request(API + "system/jobs", key)["data"]
        importing = any(job["job_name"] in import_names and job["status"] in ("pending", "running")
                        for job in jobs)
        if (not importing and series_ids <= {item["sonarrSeriesId"] for item in series}
                and movie_ids <= {item["radarrId"] for item in movies}
                and sum(item["episodeFileCount"] for item in series) >= episode_count):
            break
        if time.monotonic() >= deadline:
            raise RuntimeError("Bazarr library import did not complete before the deadline")
        time.sleep(5)
    assigned = False
    for endpoint, items, id_key, form_key in (
        ("series", series, "sonarrSeriesId", "seriesid"),
        ("movies", movies, "radarrId", "radarrid"),
    ):
        missing = [item for item in items if item["profileId"] is None]
        if missing:
            assignments = [(form_key, item[id_key]) for item in missing]
            assignments += [("profileid", profile["profileId"]) for _ in missing]
            request(API + endpoint, key, assignments)
            assigned = True
            if any(item["profileId"] is None for item in request(API + endpoint, key)["data"]):
                raise RuntimeError("Bazarr profile assignment did not converge")
    # Run the initial missing-subtitle searches once per requested profile.
    marker = CONFIG / ".homelab-profile"
    if assigned or not marker.exists() or marker.read_text().strip() != revision:
        search_missing(key, timeout=deadline - time.monotonic())
        temporary = marker.with_suffix(".partial")
        temporary.write_text(revision + "\n")
        temporary.replace(marker)
    print(json.dumps({"series": len(series), "episodes": episode_count, "movies": len(movies),
                      "profile": profile["name"], "providers": PROVIDERS}))


def backup(config=CONFIG, destination=Path("/backup")):
    """Use SQLite's online backup API; never archive a changing SQLite/WAL pair."""
    destination.mkdir(parents=True, exist_ok=True)
    stamp = time.strftime("%Y%m%dT%H%M%SZ", time.gmtime())
    final = destination / f"{stamp}.tar.gz"
    partial = final.with_suffix(".partial")
    with tempfile.TemporaryDirectory(prefix=".bazarr-", dir=destination) as directory:
        snapshot = Path(directory) / "bazarr.db"
        source_path = config / "db/bazarr.db"
        # SQLite transaction contexts do not close files before NFS cleanup.
        with closing(sqlite3.connect(f"file:{source_path}?mode=ro", uri=True, timeout=30)) as source:
            with closing(sqlite3.connect(snapshot)) as target:
                source.backup(target, pages=256, sleep=0.1)
                if target.execute("PRAGMA integrity_check").fetchone() != ("ok",):
                    raise RuntimeError("Bazarr backup database integrity check failed")
        with tarfile.open(partial, "w:gz") as archive:
            archive.add(snapshot, arcname="db/bazarr.db")
            archive.add(config / "config/config.yaml", arcname="config/config.yaml")
            marker = config / ".homelab-profile"
            if marker.exists():
                archive.add(marker, arcname=".homelab-profile")
        with tarfile.open(partial) as archive:
            if not {"db/bazarr.db", "config/config.yaml"} <= set(archive.getnames()):
                raise RuntimeError("Bazarr backup archive is incomplete")
        partial.replace(final)
    for path in destination.glob("20??????T??????Z.tar.gz"):
        if path.stat().st_mtime < time.time() - 14 * 86400:
            path.unlink()
    print(f"Verified Bazarr database/config backup: {final.name}")


def verify():
    key = api_config()["auth"]["apikey"]
    series = request(API + "series", key)["data"]
    movies = request(API + "movies", key)["data"]
    print(json.dumps({
        "series": len(series), "episodes": sum(item["episodeFileCount"] for item in series),
        "movies": len(movies), "unassigned": sum(item["profileId"] is None for item in series + movies),
        "profiles": request(API + "system/languages/profiles", key),
        "health": request(API + "system/health", key),
        "providers": request(API + "providers", key),
    }))


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("command", choices=("configure", "reconcile", "finish-setup", "backup", "verify"))
    parser.add_argument("--timeout", type=int, default=1800,
                        help="Maximum import/search wait for finish-setup, in seconds (default: 1800)")
    args = parser.parse_args()
    os.umask(0o077)
    try:
        if args.command == "finish-setup":
            finish_setup(args.timeout)
        else:
            {"configure": configure, "reconcile": reconcile, "backup": backup, "verify": verify}[args.command]()
    except Exception as error:
        # Runtime errors can contain private media paths or provider/API credentials.
        print(f"Bazarr {args.command} failed ({type(error).__name__}); inspect the private runtime", flush=True)
        raise SystemExit(1) from None


if __name__ == "__main__":
    main()
