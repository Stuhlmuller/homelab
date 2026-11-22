#!/usr/bin/env python3
"""Negative contracts for classified coverage and source-specific freshness."""

import copy
import importlib.util
import json
import shutil
import subprocess
import tempfile
from pathlib import Path
import unittest
from urllib.parse import parse_qs, urlencode

SPEC = importlib.util.spec_from_file_location("kuma_check", Path(__file__).with_name("uptime-kuma-check.py"))
CHECK = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(CHECK)


class CatalogTests(unittest.TestCase):
    def setUp(self):
        self.catalog = json.loads(CHECK.CATALOG.read_text())

    def rejects(self, mutate, pattern):
        mutate(self.catalog)
        with self.assertRaisesRegex(ValueError, pattern):
            CHECK.validate(self.catalog)

    def test_current_catalog_and_live_addition(self):
        self.assertEqual(CHECK.validate(self.catalog), (64, 57))
        with self.assertRaisesRegex(ValueError, "unclassified"):
            CHECK.validate(self.catalog, live_names=["newly-added-live-app"])

    def test_enabled_image_updater_has_exact_workload_coverage(self):
        app = next(a for a in self.catalog["apps"] if a["id"] == "argocd-image-updater")
        monitor = next(m for m in self.catalog["monitors"] if m["key"] == app["monitorIds"][0])
        self.assertEqual(app["lifecycle"], "active")
        self.assertEqual(monitor["workloads"], [
            {"kind": "deployment", "namespace": "argocd", "name": "argocd-image-updater"}])
        self.assertTrue(monitor["enabled"])
        app.update(lifecycle="suspended", reason="Controller replicaCount zero; paused.", monitorIds=[])
        with self.assertRaisesRegex(ValueError, "exclusion lacks"):
            CHECK.validate(self.catalog)

    def test_missing_source_app(self):
        self.rejects(lambda c: c["apps"].pop(0), "unclassified")

    def test_unknown_app(self):
        def change(c):
            a = copy.deepcopy(next(a for a in c["apps"] if a["lifecycle"] == "active"))
            a["id"] = "invented-app"
            c["apps"].append(a)

        self.rejects(change, "source does not own app|unknown application")

    def test_nofx_targets_declared_service(self):
        m = next(m for m in self.catalog["monitors"] if m["key"] == "nofx-http")
        self.assertEqual(m["target"]["url"], "http://nofx.nofx.svc:8080/api/health")

    def test_prowlarr_native_ping_contract(self):
        for change in [
            {"kind": "http"},
            {"target": {"url": "http://prowlarr.media.svc:9696/initialize.json"}},
            {"expected": {"statusCodes": [302], "jsonPath": "status", "value": "OK"}},
            {"expected": {"statusCodes": [200], "jsonPath": "status", "value": "Error"}},
            {"expected": {"statusCodes": [200]}},
        ]:
            with self.subTest(change=change):
                catalog = copy.deepcopy(self.catalog)
                next(m for m in catalog["monitors"] if m["key"] == "prowlarr-http").update(change)
                with self.assertRaises(ValueError):
                    CHECK.validate(catalog)
        other = next(m for m in self.catalog["monitors"] if m.get("sourceSignals"))
        other["expected"] = {"statusCodes": [200], "jsonPath": "status", "value": "OK"}
        with self.assertRaisesRegex(ValueError, "unsafe JSON"):
            CHECK.validate(self.catalog)

    def test_unjustified_retirement(self):
        def change(c):
            a = next(a for a in c["apps"] if a["id"] == "n8n")
            a.update(lifecycle="retired", reason="Retired without an owning source change.", monitorIds=[])

        self.rejects(change, "retirement lacks")

    def retirement_fixture(self, app_id="n8n", historical=False):
        directory = tempfile.TemporaryDirectory(prefix="kuma-retirement-")
        self.addCleanup(directory.cleanup)
        root = Path(directory.name)
        sources = {a["source"] for a in self.catalog["apps"]}
        sources.update(s["cadenceSource"] for m in self.catalog["monitors"] for s in m.get("sourceSignals", []))
        sources.add("specs/20261116-210437-uptime-kuma/inventory-evidence.md")
        for source in sources:
            destination = root / source
            destination.parent.mkdir(parents=True, exist_ok=True)
            shutil.copyfile(CHECK.ROOT / source, destination)
        evidence = root / "docs/retirements" / (app_id + ".md")
        evidence.parent.mkdir(parents=True, exist_ok=True)
        evidence.write_text(
            f"# {app_id} retirement\n\n<!-- uptime-kuma-retired: {app_id} -->\n\nThe former runtime is retired; retain its monitor history.\n"
        )
        if historical:
            app = {
                "id": app_id,
                "lifecycle": "retired",
                "source": str(evidence.relative_to(root)),
                "reason": "Retired runtime; retain the previous monitor and history.",
                "monitorIds": [app_id + "-http"],
            }
            monitor = copy.deepcopy(next(m for m in self.catalog["monitors"] if m["kind"] == "http"))
            monitor.update(key=app_id + "-http", ownerAppIds=[app_id], enabled=False)
            self.catalog["apps"].append(app)
            self.catalog["monitors"].append(monitor)
        else:
            app = next(a for a in self.catalog["apps"] if a["id"] == app_id)
            app.update(
                lifecycle="retired",
                source=str(evidence.relative_to(root)),
                reason="Retired runtime; retain the previous monitors and history.",
            )
            for monitor in self.catalog["monitors"]:
                if monitor["key"] in app["monitorIds"]:
                    monitor["enabled"] = False
        return root, app, evidence

    def test_retired_app_retains_disabled_owned_records(self):
        root, app, _ = self.retirement_fixture()
        self.assertTrue(app["monitorIds"])
        self.assertEqual(CHECK.validate(self.catalog, root=root), (64, 57))

    def test_historical_retirement_has_durable_identity_evidence(self):
        root, _, evidence = self.retirement_fixture("former-service", historical=True)
        self.assertEqual(CHECK.validate(self.catalog, root=root), (65, 58))
        evidence.write_text("An unrelated existing document does not prove retirement.\n")
        with self.assertRaisesRegex(ValueError, "retirement lacks"):
            CHECK.validate(self.catalog, root=root)

    def test_retirement_marker_for_other_identity_is_rejected(self):
        root, _, evidence = self.retirement_fixture("former-service", historical=True)
        evidence.write_text("<!-- uptime-kuma-retired: another-service -->\n")
        with self.assertRaisesRegex(ValueError, "retirement lacks"):
            CHECK.validate(self.catalog, root=root)

    def test_retirement_reason_is_required_even_with_evidence(self):
        root, app, _ = self.retirement_fixture()
        app["reason"] = "Runtime availability has not been investigated."
        with self.assertRaisesRegex(ValueError, "retirement lacks"):
            CHECK.validate(self.catalog, root=root)

    def test_retired_exclusive_monitor_cannot_remain_enabled(self):
        root, _, _ = self.retirement_fixture()
        next(m for m in self.catalog["monitors"] if m["key"] == "n8n-http")["enabled"] = True
        with self.assertRaisesRegex(ValueError, "inactive-only monitor"):
            CHECK.validate(self.catalog, root=root)

    def test_active_app_can_keep_disabled_old_monitor_with_enabled_coverage(self):
        next(m for m in self.catalog["monitors"] if m["key"] == "n8n-http")["enabled"] = False
        self.assertEqual(CHECK.validate(self.catalog), (64, 57))

    def test_active_app_cannot_have_only_disabled_monitors(self):
        for monitor in self.catalog["monitors"]:
            if monitor["ownerAppIds"] == ["n8n"]:
                monitor["enabled"] = False
        with self.assertRaisesRegex(ValueError, "active app lacks enabled"):
            CHECK.validate(self.catalog)

    def test_shared_monitor_survives_one_owner_retirement(self):
        root, _, _ = self.retirement_fixture()
        monitor = next(m for m in self.catalog["monitors"] if m["key"] == "n8n-http")
        monitor["ownerAppIds"].append("n8n-postgres")
        monitor["enabled"] = True
        next(a for a in self.catalog["apps"] if a["id"] == "n8n-postgres")["monitorIds"].append("n8n-http")
        self.assertEqual(CHECK.validate(self.catalog, root=root), (64, 57))
        monitor["enabled"] = False
        with self.assertRaisesRegex(ValueError, "shared monitor with active owner"):
            CHECK.validate(self.catalog, root=root)

    def test_disabled_record_still_requires_reciprocal_links(self):
        root, app, _ = self.retirement_fixture()
        app["monitorIds"].remove("n8n-http")
        with self.assertRaisesRegex(ValueError, "invalid ownership link"):
            CHECK.validate(self.catalog, root=root)

    def test_wrong_owning_source(self):
        self.rejects(
            lambda c: next(a for a in c["apps"] if a["id"] == "n8n").update(
                source="clusters/homelab/apps/affine/deployment.yaml"
            ),
            "source does not own",
        )

    def test_duplicate_app(self):
        self.rejects(lambda c: c["apps"].append(c["apps"][0]), "duplicate app")

    def test_duplicate_monitor(self):
        self.rejects(lambda c: c["monitors"].append(c["monitors"][0]), "duplicate/invalid")

    def test_missing_coverage(self):
        self.rejects(
            lambda c: next(a for a in c["apps"] if a["lifecycle"] == "active").update(monitorIds=[]),
            "missing app coverage",
        )

    def test_unknown_monitor_link(self):
        self.rejects(
            lambda c: next(a for a in c["apps"] if a["lifecycle"] == "active")["monitorIds"].append("unknown"),
            "missing reciprocal",
        )

    def test_invalid_owner(self):
        self.rejects(lambda c: c["monitors"][0].update(ownerAppIds=["invented-app"]), "invalid ownership")

    def test_exclusion_needs_source_evidence(self):
        def change(c):
            a = next(a for a in c["apps"] if a["id"] == "n8n")
            a.update(lifecycle="suspended", reason="Pretend application is paused with zero replicas.", monitorIds=[])

        self.rejects(change, "source evidence")

    def test_missing_cadence(self):
        self.rejects(lambda c: c["monitors"][0]["sourceSignals"][0].update(cadenceSource="missing"), "cadence evidence")

    def test_missing_source_signal_is_rejected(self):
        self.rejects(lambda c: c["monitors"][0]["sourceSignals"].pop(), "workload source cadence/identity")

    def test_unsafe_cadence_source_is_rejected(self):
        self.rejects(
            lambda c: c["monitors"][0]["sourceSignals"][0].update(cadenceSource="/etc/passwd"),
            "unsafe cadence evidence",
        )

    def test_claimed_period_must_match_committed_scrape_interval(self):
        def change(c):
            m = next(m for m in c["monitors"] if m["key"] == "deluge-daemon-vpn")
            for signal in m["sourceSignals"]:
                signal.update(periodSeconds=3600, maxAgeSeconds=7200)
            m["target"]["body"] = urlencode({"query": CHECK.health_query(m["sourceSignals"])})

        self.rejects(change, "source cadence differs")

    def test_removed_single_source_freshness_check_is_rejected(self):
        def change(c):
            m = c["monitors"][0]
            query = parse_qs(m["target"]["body"])["query"][0]
            source = CHECK.selector(m["sourceSignals"][0])
            clause = f"(time() - scalar(timestamp({source})) <= bool 60)"
            m["target"]["body"] = urlencode({"query": query.replace(clause, "1", 1)})

        self.rejects(change, "unsafe health/freshness")

    def test_credential_target(self):
        self.rejects(
            lambda c: c["monitors"][0]["target"].update(url="http://secret:password@example.com"), "unsafe target"
        )

    def test_external_target(self):
        self.rejects(lambda c: c["monitors"][0]["target"].update(url="http://example.com"), "explicit cluster service")

    def test_redirect_and_auth_are_not_health(self):
        for status in [302, 401, 403]:
            with self.subTest(status=status):
                c = copy.deepcopy(self.catalog)
                c["monitors"][-1]["expected"]["statusCodes"] = [status]
                with self.assertRaisesRegex(ValueError, "cannot prove health"):
                    CHECK.validate(c)

    def test_freshness_cannot_use_response_timestamp(self):
        def change(c):
            m = c["monitors"][0]
            q = parse_qs(m["target"]["body"])["query"][0]
            m["target"]["body"] = urlencode({"query": q.replace("timestamp(", "time(")})

        self.rejects(change, "unsafe health/freshness")

    def test_15_second_source_has_exact_30_second_bound(self):
        signal = CHECK.metric_signal("health", "test", "deployment", "fixture", period=15)
        query = CHECK.health_query([signal])
        self.assertIn("<= bool 30", query)
        self.assertNotIn("<= bool 120", query)
        self.assertIn("scalar(count(health{", query)
        self.assertIn("== bool 1", query)

    def test_fixed_120_seconds_is_rejected(self):
        self.rejects(lambda c: c["monitors"][0]["sourceSignals"][0].update(maxAgeSeconds=120), "two source periods")

    def test_zero_desired_and_partial_readiness_are_not_health(self):
        m = self.catalog["monitors"][0]
        q = parse_qs(m["target"]["body"])["query"][0]
        self.assertIn("> bool 0", q)
        self.assertIn(">= bool scalar(kube_deployment_spec_replicas", q)
        self.assertIn("status_observed_generation", q)

    def test_unexpected_query_headers_rejected(self):
        self.rejects(
            lambda c: c["monitors"][0]["target"]["headers"].update(Authorization="Bearer secret"),
            "unsafe query request",
        )

    def test_unknown_fields_rejected(self):
        self.rejects(lambda c: c["monitors"][0].update(secret="bad"), "unknown monitor fields")


@unittest.skipUnless(shutil.which("promtool"), "Run in repository nix develop for real Prometheus evaluator")
class PrometheusPredicateTests(unittest.TestCase):
    """Evaluate generated production PromQL, not a parallel Python predicate."""

    def test_raw_sample_freshness_and_workload_failure_cases(self):
        workload = {"kind": "deployment", "namespace": "test", "name": "fixture"}
        signals = CHECK.signals_for([workload])
        for signal in signals:
            signal.update(periodSeconds=15, maxAgeSeconds=30)
        query = CHECK.health_query(signals, [workload])
        # Compare the actual result with 1 just as JSONata does. Missing or
        # duplicate sources may yield NaN; these must never be accepted as up.
        expression = f"({query}) == bool 1"
        base = [{"series": CHECK.selector(signal), "values": "1 _x31"} for signal in signals]
        cases = []

        def add(name, series, at, up):
            cases.append(
                {
                    "name": name,
                    "interval": "1s",
                    "input_series": series,
                    "promql_expr_test": [
                        {"expr": expression, "eval_time": at, "exp_samples": [{"labels": "{}", "value": up}]}
                    ],
                }
            )

        add("15-second observation: exactly age30 is eligible", base, "30s", 1)
        add("15-second observation: age31 must be down", base, "31s", 0)
        add("missing all workload sources", [], "0s", 0)
        add("missing readiness source", base[:1] + base[2:], "0s", 0)
        for name, values in [
            ("zero desired replicas", [0, 0, 1, 1]),
            ("partial readiness", [2, 1, 1, 1]),
            ("unobserved generation", [1, 1, 2, 1]),
        ]:
            series = [dict(item, values=str(value)) for item, value in zip(base, values)]
            add(name, series, "0s", 0)
        duplicate = copy.deepcopy(base)
        duplicate[1]["series"] = duplicate[1]["series"][:-1] + ',instance="one"}'
        duplicate.append(dict(duplicate[1], series=duplicate[1]["series"].replace('"one"', '"two"')))
        add("duplicate readiness sources", duplicate, "0s", 0)
        one_stale = [dict(item, values="1+0x31") for item in base]
        one_stale[1]["values"] = "1 _x31"
        add("one stale input cannot hide behind fresh desired/generation", one_stale, "31s", 0)

        for kind in ["statefulset", "daemonset"]:
            w = dict(workload, kind=kind)
            sources = CHECK.signals_for([w])
            expr = f"({CHECK.health_query(sources, [w])}) == bool 1"
            for label, values, expected in [
                ("ready", [1, 1, 1], 1),
                ("zero", [0, 0, 0], 0),
                ("partial", [2, 1, 2], 0),
                ("old revision", [2, 2, 1], 0),
            ]:
                cases.append(
                    {
                        "name": kind + " " + label,
                        "interval": "1s",
                        "input_series": [
                            {"series": CHECK.selector(sig), "values": str(value)} for sig, value in zip(sources, values)
                        ],
                        "promql_expr_test": [
                            {"expr": expr, "eval_time": "0s", "exp_samples": [{"labels": "{}", "value": expected}]}
                        ],
                    }
                )
        fixture = {"rule_files": [], "evaluation_interval": "1s", "tests": cases}
        with tempfile.TemporaryDirectory(prefix="kuma-promql-") as directory:
            path = Path(directory) / "rules-test.json"
            path.write_text(json.dumps(fixture))
            result = subprocess.run(
                ["promtool", "test", "rules", str(path)], text=True, capture_output=True, check=False
            )
        self.assertEqual(result.returncode, 0, result.stdout + result.stderr)


if __name__ == "__main__":
    unittest.main()
