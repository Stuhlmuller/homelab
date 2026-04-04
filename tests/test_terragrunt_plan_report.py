from __future__ import annotations

import importlib.util
import unittest
from pathlib import Path


MODULE_PATH = Path(__file__).resolve().parents[1] / "scripts" / "ci" / "terragrunt_plan_report.py"
SPEC = importlib.util.spec_from_file_location("terragrunt_plan_report", MODULE_PATH)
MODULE = importlib.util.module_from_spec(SPEC)
assert SPEC.loader is not None
SPEC.loader.exec_module(MODULE)


class TerragruntPlanReportTests(unittest.TestCase):
    def test_parse_plan_stats_aggregates_multiple_plan_blocks(self) -> None:
        log_text = """
        random prelude
        Plan: 1 to add, 2 to change, 3 to destroy.
        No changes. Your infrastructure matches the configuration.
        Plan: 4 to add, 5 to change, 6 to destroy.
        Error: one thing broke
        Error: one thing broke
        """

        stats = MODULE.parse_plan_stats(log_text)

        self.assertEqual(stats["plan_blocks"], 2)
        self.assertEqual(stats["no_change_blocks"], 1)
        self.assertEqual(stats["totals"], {"add": 5, "change": 7, "destroy": 9})
        self.assertEqual(stats["error_lines"], ["Error: one thing broke"])

    def test_merge_managed_section_appends_to_existing_body(self) -> None:
        body = "## Context\n\nUser-authored notes live here."
        section = f"{MODULE.START_MARKER}\nmanaged block\n{MODULE.END_MARKER}\n"

        merged = MODULE.merge_managed_section(body, section)

        self.assertIn("User-authored notes live here.", merged)
        self.assertIn("managed block", merged)
        self.assertTrue(merged.endswith("\n"))

    def test_merge_managed_section_replaces_existing_block_only(self) -> None:
        body = (
            "Intro paragraph.\n\n"
            f"{MODULE.START_MARKER}\nold block\n{MODULE.END_MARKER}\n\n"
            "Closing paragraph.\n"
        )
        section = f"{MODULE.START_MARKER}\nnew block\n{MODULE.END_MARKER}\n"

        merged = MODULE.merge_managed_section(body, section)

        self.assertIn("Intro paragraph.", merged)
        self.assertIn("Closing paragraph.", merged)
        self.assertIn("new block", merged)
        self.assertNotIn("old block", merged)

    def test_build_plan_section_includes_failure_excerpt(self) -> None:
        section = MODULE.build_plan_section(
            log_text="Error: failure\nexit status 1\n",
            exit_code=1,
            working_dir="terraform/live/homelab",
            run_url="https://example.invalid/run",
            artifact_name="artifact-name",
            commit_sha="1234567890abcdef",
        )

        self.assertIn("## Homelab Terragrunt Plan", section)
        self.assertIn("`failed`", section)
        self.assertIn("Relevant errors", section)
        self.assertIn("artifact-name", section)


if __name__ == "__main__":
    unittest.main()
