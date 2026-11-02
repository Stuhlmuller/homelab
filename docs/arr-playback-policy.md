# QNAP Playback Policy

The TS-451+ runs Plex on an Intel Celeron J1900. Prefer files the playback
client can decode directly: H.264/AVC, SDR, at most 1080p. A small HEVC file
can be harder to play than a larger H.264 file because conversion costs CPU.

On October 28, 2026, read-only Plex logs showed a local Roku client rejecting
HEVC Main 10 video. Plex decoded it in software and encoded H.264 with
`libx264`, producing only 0.39–0.57 seconds of video per elapsed second.
Playback repeatedly buffered; audio was copied and no subtitle conversion was
recorded. A previous release was also labeled HEVC with Dolby Vision/HDR,
but its exact playback failure was not present in the retained logs. Do not
attribute that earlier failure specifically to tone mapping without evidence.

The live Sonarr/Radarr profiles had no codec custom formats. Resolution-only
profiles admitted both releases. Separately, Sonarr reported a completed
H.264 download as `importPending` because it contained an archive. That is an
extraction/import problem, not evidence of a QNAP decoding limit. There is no
declared media archive extraction service; retain the download and resolve
that separately through a reviewed code path.

Diagnostic hygiene finding: an October 28 agent inspection printed a history
download URL containing a Prowlarr API key. No credential is recorded here.
That key needs coordinated rotation with its Sonarr/Radarr integrations through
a reviewed code path. History and queue responses must be reduced to an
allowlist of safe fields before display; never print download URLs or raw logs.

## Desired Settings

[`arr-playback-policy.json`](../scripts/config/arr-playback-policy.json) owns
the shared Sonarr/Radarr selection policy:

- Require an explicit `x264`, `H.264`, or `AVC` release label.
- Reject HEVC/x265, AV1, VP9, HDR/Dolby Vision/HLG, high bit depth, remux,
  raw and disc labels; disable unsupported quality types and resolutions.
- Retain each profile's existing safe qualities and ID. Convert a profile
  with no safe choices, such as Ultra-HD, to a clearly named HD fallback.
- Limit allowed quality definitions to 30 MiB/min through 720p and
  60 MiB/min at 1080p; preferred sizes are at most 20 and 40 MiB/min.
  Preserve stricter existing limits.

Those maximum sizes approximate 4.2 and 8.4 Mbps averaged across the entire
file, including audio. They are conservative selection limits, not measured
hardware maxima or peak bitrate guarantees. Sonarr/Radarr use indexer metadata
and runtime; unknown sizes and Sonarr specials can bypass size checks. The
codec filter trusts release labels and rejects unlabeled releases. Manual
overrides and profiles created after reconciliation can bypass the policy.
Reconcile again after adding profiles. Client quality limits, subtitles,
unexpected codec profiles, and network conditions can still force conversion.

See [QNAP hardware specifications](https://www.qnap.com/en-ph/product/ts-451%2B/specs/hardware),
[Plex NAS compatibility](https://support.plex.tv/articles/201373803-nas-compatibility-list/),
and [Servarr settings](https://wiki.servarr.com/sonarr/settings).

## Apply And Verify

The repository-owned helper uses each app's API through its existing Pod.
API keys remain inside the container. It updates settings only; it does not
delete, replace, search for, or download media, or alter queued downloads.
Foreign nonzero custom-format scores fail validation rather than weaken
eligibility. Keep the snapshot private and outside this public repository.

```sh
python3 -I scripts/ci/arr-playback-policy-test.py
python3 -I scripts/arr-playback-policy.py
```

Review the preview, merge the protected PR, and use a clean checkout of the
exact current `main`:

```sh
python3 -I scripts/arr-playback-policy.py --execute \
  --expected-sha "$(git rev-parse HEAD)" \
  --snapshot /private/tmp/arr-playback-before.json
python3 -I scripts/arr-playback-policy.py
```

Execution requires a new snapshot file, records the previous settings before
the first write, and reads back both applications. A second preview must show
no remaining changes. This is an operator-applied application setting change;
an Argo sync or Pod restart is not its delivery mechanism.

Then verify a newly imported eligible file on the original client. Plex's
playback dashboard should show direct video playback or stream copy, without
slow software video conversion. Start and seek must work. API convergence
alone does not establish playback acceptance or repair existing incompatible
media. An already queued download retains its earlier selection.

## Rollback

Keep the private snapshot until playback is accepted. This helper only tightens
size limits: relaxing the JSON does not undo existing settings. Exact rollback
requires a reviewed restore using the snapshot, including profile scores and
the managed custom format. Do not upload the snapshot to git or restore
settings through ad hoc API calls. The snapshot contains settings, not media
files, database backups, or API keys.
