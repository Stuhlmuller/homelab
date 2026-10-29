#!/usr/bin/env python3
"""Exercise playback eligibility, preservation, and the guarded API apply path."""
import copy
import importlib.util
import json
from pathlib import Path
import re
import tempfile
import unittest
from unittest.mock import patch

ROOT = Path(__file__).resolve().parents[2]
SPEC = importlib.util.spec_from_file_location("playback", ROOT / "scripts/arr-playback-policy.py")
MODULE = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(MODULE)
POLICY = json.loads(MODULE.POLICY.read_text())


def quality(identifier, name, resolution, allowed=True):
    return {"quality": {"id": identifier, "name": name, "resolution": resolution},
            "items": [], "allowed": allowed}


def state():
    items = [quality(1, "SDTV", 480),
             {"id": 1001, "name": "WEB 720p", "allowed": True,
              "items": [quality(5, "WEBDL-720p", 720), quality(14, "WEBRip-720p", 720)]},
             quality(7, "Bluray-1080p", 1080), quality(30, "Remux-1080p", 1080),
             quality(19, "Bluray-2160p", 2160), quality(0, "Unknown", 0)]
    return {"customformat": [{"id": 9, "name": "Unrelated", "specifications": []}],
            "qualityprofile": [{"id": 1, "name": "Any", "items": items,
                                "cutoff": 1001, "upgradeAllowed": True,
                                "minFormatScore": 0, "cutoffFormatScore": 0,
                                "minUpgradeFormatScore": 1, "language": {"id": 1, "name": "English"},
                                "formatItems": [{"format": 9, "name": "Unrelated", "score": 0}]}],
            "qualitydefinition": [{"id": 12, "quality": items[1]["items"][0]["quality"],
                                   "minSize": 3, "preferredSize": 95, "maxSize": 130},
                                  {"id": 16, "quality": items[2]["quality"], "minSize": 4}]}


class PolicyTests(unittest.TestCase):
    def test_title_eligibility(self):
        wanted = MODULE.desired_format(POLICY)
        self.assertTrue(all(spec["required"] for spec in wanted["specifications"]))
        def matches(title):
            return all(bool(re.search(spec["fields"][0]["value"], title, re.I)) != spec["negate"]
                       for spec in wanted["specifications"])
        for title in ("Show.S04E02.720p.WEB.H264", "Movie_1080p_x264", "Show.1080p.AVC",
                      "Movie.1080p.h.264.8bit", "Movie.720p.H.264.DVDRip"):
            self.assertTrue(matches(title), title)
        for title in ("Show.S04E02.1080p.WEB.H265", "Show.1080p.WEB", "Movie.720p.x2640",
                      "Movie_1080p_HEVC_x264", "Movie.1080p.x264.HDR", "Movie.H264.HDR10+",
                      "Movie.H264.Dolby.Vision", "Movie.H264.DV", "Movie.H264.Dovi",
                      "Movie.H264.HLG", "Movie.H264.10bit", "Movie.H264.Hi10P",
                      "Movie.H264.12-bit", "Movie.H264.High422", "Movie.H264.Hi444P",
                      "Movie.H264.High10", "Movie.H264.Hi10", "Movie.H264.High444P",
                      "Movie.H264.AV1", "Movie.H264.VP9", "Movie.H264.REMUX",
                      "Movie.H264.Raw-HD", "Movie.H264.BR-DISK", "Movie.H264.BDMV"):
            self.assertFalse(matches(title), title)

    def test_profile_preserves_identity_order_language_upgrades_and_foreign_zero_score(self):
        before = state()["qualityprofile"][0]
        result = MODULE.profile_policy(before, POLICY, 10)
        self.assertEqual([entry["allowed"] for entry in result["items"]], [True, True, True, False, False, False])
        for key in ("id", "name", "cutoff", "language", "upgradeAllowed", "minUpgradeFormatScore"):
            self.assertEqual(result[key], before[key])
        self.assertEqual(result["formatItems"][0], before["formatItems"][0])
        self.assertEqual(result["minFormatScore"], 1)
        self.assertEqual(MODULE.profile_policy(result, POLICY, 10), result)
        self.assertTrue(before["items"][-1]["allowed"])

    def test_disabled_groups_stay_disabled_and_allowed_child_cutoff_stays(self):
        before = state()["qualityprofile"][0]
        before["cutoff"] = 5
        self.assertEqual(MODULE.profile_policy(before, POLICY, 10)["cutoff"], 5)
        before["items"][1]["allowed"] = False
        result = MODULE.profile_policy(before, POLICY, 10)
        self.assertFalse(result["items"][1]["allowed"])
        self.assertFalse(any(child["allowed"] for child in result["items"][1]["items"]))
        self.assertEqual(result["cutoff"], 7)

    def test_ultra_hd_falls_back_without_changing_id(self):
        before = state()["qualityprofile"][0]
        before.update(name="Ultra-HD", cutoff=19)
        for item in before["items"]:
            item["allowed"] = item.get("quality", {}).get("resolution") == 2160
        result = MODULE.profile_policy(before, POLICY, 10)
        self.assertEqual(result["name"], POLICY["fallbackName"])
        self.assertEqual(result["id"], before["id"])
        self.assertEqual(result["cutoff"], 7)
        self.assertEqual([item["allowed"] for item in result["items"]], [False, True, True, False, False, False])

    def test_foreign_scores_or_stricter_score_requirements_fail_closed(self):
        for score in (-1, 1, 100):
            before = state()["qualityprofile"][0]
            before["formatItems"][0]["score"] = score
            with self.assertRaises(ValueError):
                MODULE.profile_policy(before, POLICY, 10)
        before = state()["qualityprofile"][0]
        before["minFormatScore"] = 10
        with self.assertRaises(ValueError):
            MODULE.profile_policy(before, POLICY, 10)

    def test_size_caps_preserve_stricter_limits_and_valid_minimum(self):
        standard, unlimited = state()["qualitydefinition"]
        self.assertEqual(MODULE.definition_policy(standard, POLICY) | {"quality": None},
                         standard | {"quality": None, "maxSize": 30, "preferredSize": 20})
        self.assertEqual(MODULE.definition_policy(unlimited, POLICY)["maxSize"], 60)
        standard.update(maxSize=12, preferredSize=8)
        self.assertEqual(MODULE.definition_policy(standard, POLICY), standard)
        standard.update(minSize=25, maxSize=130, preferredSize=95)
        self.assertEqual(MODULE.definition_policy(standard, POLICY)["preferredSize"], 25)
        standard["minSize"] = 31
        with self.assertRaises(ValueError):
            MODULE.definition_policy(standard, POLICY)
        standard.update(minSize=0, maxSize=0, preferredSize=0)
        self.assertEqual(MODULE.definition_policy(standard, POLICY), standard | {"maxSize": 30})

    def test_apply_readback_and_repeat_are_idempotent(self):
        current = state()
        writes = []
        def api(app, endpoint, body=None, method="GET"):
            kind, _, identifier = endpoint.partition("/")
            if method == "GET":
                return copy.deepcopy(next(item for item in current[kind] if item["id"] == int(identifier))
                                     if identifier else current[kind])
            writes.append((endpoint, method))
            if method == "POST":
                new = copy.deepcopy(body) | {"id": 10}
                current[kind].append(new)
                for profile in current["qualityprofile"]:
                    profile["formatItems"].append({"format": 10, "name": new["name"], "score": 0})
            else:
                current[kind] = [copy.deepcopy(body) if item["id"] == body["id"] else item for item in current[kind]]
        with patch.object(MODULE, "api", side_effect=api):
            MODULE.apply("sonarr", copy.deepcopy(current), POLICY)
            first_writes = len(writes)
            MODULE.apply("sonarr", copy.deepcopy(current), POLICY)
        self.assertEqual(len(writes), first_writes)
        self.assertEqual(first_writes, 4)
        self.assertEqual(current["customformat"][0]["name"], "Unrelated")
        self.assertFalse(any(MODULE.changes(MODULE.plan(current, POLICY)).values()))

    def test_changed_snapshot_aborts_without_writes(self):
        with patch.object(MODULE, "read_state", return_value={}), patch.object(MODULE, "api") as api:
            with self.assertRaises(RuntimeError):
                MODULE.apply("sonarr", state(), POLICY)
            api.assert_not_called()

    def test_execution_requires_guard_and_snapshot_before_mutation(self):
        with patch.object(MODULE, "reviewed_main", side_effect=ValueError), patch.object(MODULE, "api") as api:
            with self.assertRaises(ValueError):
                MODULE.main(["--execute", "--expected-sha", "bad", "--snapshot", "/tmp/unused"])
            api.assert_not_called()
        with patch.object(MODULE, "read_state", return_value=state()), patch.object(MODULE, "apply") as apply, \
                patch.object(MODULE, "reviewed_main"), patch.object(MODULE, "snapshot", side_effect=OSError):
            with self.assertRaises(OSError):
                MODULE.main(["--execute", "--snapshot", "/tmp/unused"])
            apply.assert_not_called()

    def test_private_snapshot_does_not_overwrite_or_follow_symlinks(self):
        with tempfile.TemporaryDirectory() as directory:
            target = Path(directory) / "state.json"
            MODULE.snapshot(target, state())
            self.assertEqual(target.stat().st_mode & 0o777, 0o600)
            with self.assertRaises(FileExistsError):
                MODULE.snapshot(target, {})
            link = Path(directory) / "link"
            link.symlink_to(target)
            with self.assertRaises(FileExistsError):
                MODULE.snapshot(link, {})
        with self.assertRaises(ValueError):
            MODULE.snapshot(ROOT / "snapshot.json", {})

    def test_reviewed_main_rejects_dirty_checkout_or_mismatched_head(self):
        sha = "a" * 40
        for outputs in ([b" M tracked\n"], [b"", b"b" * 40, sha.encode() + b" refs/heads/main\n"],
                        [b"", sha.encode(), b"b" * 40 + b" refs/heads/main\n"]):
            with patch.object(MODULE, "run", side_effect=outputs), self.assertRaises(ValueError):
                MODULE.reviewed_main(sha)
        with patch.object(MODULE, "run", side_effect=[b"", sha.encode(), sha.encode() + b" refs/heads/main\n"]):
            MODULE.reviewed_main(sha)


if __name__ == "__main__":
    unittest.main()
