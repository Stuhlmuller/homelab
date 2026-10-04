#!/usr/bin/env python3
"""Verify Lua fragmentation preserves JSON values and bounds Wazuh messages."""
import json
from pathlib import Path
import shutil
import subprocess
import unittest

ROOT = Path(__file__).resolve().parents[2]
LUA = ROOT / "clusters/homelab/apps/wazuh/collector-size.lua"


def lua_string(value):
    return '"' + "".join(f"\\{byte:03d}" for byte in value.encode("utf-8")) + '"'


def lua_value(value):
    if value is None:
        return "flb_null"
    if isinstance(value, bool):
        return "true" if value else "false"
    if isinstance(value, str):
        return lua_string(value)
    if isinstance(value, (int, float)):
        return repr(value)
    if isinstance(value, list):
        return "setmetatable({" + ",".join(lua_value(item) for item in value) + "},{type=1})"
    return "setmetatable({" + ",".join("[" + lua_string(key) + "]=" + lua_value(item)
                                      for key, item in value.items()) + "},{type=2})"


def run_filter(record, twice=False):
    script = f"""
flb_null = {{}}
local codec = dofile({lua_string(str(LUA))})
local original = {lua_value(record)}
local timestamp = {{sec=1791072000,nsec=123456789}}
local code, returned_time, returned = wazuh_size('fixture',timestamp,original)
assert(timestamp == returned_time)
if code == 0 then assert(returned == original) end
io.write(codec.encode({{code=code,records=returned}}),'\\n')
"""
    if twice:
        script += "local _, _, second = wazuh_size('fixture',timestamp,original)\nio.write(codec.encode(second),'\\n')\n"
    result = subprocess.run([shutil.which("lua") or "lua", "-"], input=script,
                            text=True, capture_output=True, check=True, timeout=20)
    return [json.loads(line) for line in result.stdout.splitlines()]


class CollectorTest(unittest.TestCase):
    def assert_round_trip(self, record):
        result, second = run_filter(record, twice=True)
        self.assertEqual(result["code"], 2)
        fragments = result["records"]
        self.assertGreater(len(fragments), 1)
        self.assertEqual(len({item["fragment_event_id"] for item in fragments}), 1)
        self.assertNotEqual(fragments[0]["fragment_event_id"], second[0]["fragment_event_id"])
        for index, item in enumerate(fragments, 1):
            self.assertEqual(item["fragment_index"], index)
            self.assertEqual(item["fragment_count"], len(fragments))
            self.assertEqual(item["fragment_encoding"], "json")
            self.assertEqual(item["original_timestamp_seconds"], 1791072000)
            self.assertEqual(item["original_timestamp_nanoseconds"], 123456789)
            # ensure_ascii=True conservatively exercises six-byte JSON escaping.
            encoded = json.dumps({**item, "collected_at": "2026-10-04T00:00:00.123456789Z"}, ensure_ascii=True).encode()
            self.assertLess(len(encoded), 32766)
            self.assertLessEqual(len(item["fragment_payload"].encode()), 8192)
        serialized = "".join(item["fragment_payload"] for item in fragments)
        self.assertEqual(len(serialized.encode()), fragments[0]["original_json_bytes"])
        self.assertEqual(json.loads(serialized), record)

    def test_ordinary_records_are_returned_unmodified(self):
        record = {"homelab_source": "kubernetes.audit", "message": "ordinary event", "status": 403,
                  "fields": {"empty_array": [], "empty_map": {}, "null": None, "bool": True}}
        result = run_filter(record)[0]
        self.assertEqual(result, {"code": 0, "records": record})

    def test_fragmentation_preserves_controls_unicode_nulls_arrays_and_maps(self):
        record = {"homelab_source": "kubernetes.container", "kubernetes": {"host": "acer"},
                  "log": ('a"\\\n\t\r\x00\x1f雪🙂é' * 12000),
                  "array": [None, False, [], {}, {"number": 42, "fraction": 1.125}], "empty": {}}
        self.assert_round_trip(record)

    def test_large_metadata_and_utf8_boundaries_cannot_make_oversize_envelopes(self):
        self.assert_round_trip({"homelab_source": "雪" * 25000, "source_address": "🙂" * 20000,
                                "log": "a" * 49151 + "🙂雪" * 25000})

    def test_one_mebibyte_log_can_be_reconstructed(self):
        self.assert_round_trip({"homelab_source": "talos", "source_address": "10.1.0.200",
                                "log": "s" * (1024 * 1024)})

    def test_logs_below_tcp_limit_still_respect_opensearch_keyword_limit(self):
        for log in ("x" * (40 * 1024), "雪" * (14 * 1024), "🙂" * (10 * 1024)):
            with self.subTest(size=len(log.encode())):
                self.assert_round_trip({"homelab_source": "kubernetes.container", "log": log})


if __name__ == "__main__":
    unittest.main()
