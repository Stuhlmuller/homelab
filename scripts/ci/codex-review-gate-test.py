#!/usr/bin/env python3
"""Only current, authenticated, completed reviews with zero findings pass."""

import json
from pathlib import Path
import runpy
import unittest


gate = runpy.run_path(str(Path(__file__).with_name("codex-review-gate.py")))
review_status = gate["review_status"]
HEAD = "a" * 40


def summary(comment_id=1, actor=199175422, app=1144995, **overrides):
    review = {
        "commit_sha": HEAD,
        "status": "completed",
        "has_any_findings": False,
        "has_unresolved_findings": False,
        **overrides,
    }
    receipt = json.dumps({"code_review": review})
    return {
        "id": comment_id,
        "user": {"id": actor},
        "performed_via_github_app": {"id": app},
        "body": f'{gate["SUMMARY"]}\n<!-- codex-review-state:v1 {receipt} -->',
    }


class ReviewStatus(unittest.TestCase):
    def test_clean_head_passes(self):
        self.assertEqual(review_status([summary()], HEAD)[0], "success")

    def test_findings_block_even_if_resolved(self):
        result = review_status([summary(has_any_findings=True)], HEAD)
        self.assertEqual(result[0], "failure")

    def test_missing_or_unusable_review_waits(self):
        malformed = summary()
        malformed["body"] = malformed["body"].replace('"code_review"', '!invalid')
        for comments in (
            [],
            [summary(actor=1)],
            [summary(app=1)],
            [summary(commit_sha="b" * 40)],
            [summary(status="running")],
            [summary(has_unresolved_findings=None)],
            [malformed],
            [summary(), summary(comment_id=2, status="running")],
        ):
            with self.subTest(comments=comments):
                self.assertEqual(review_status(comments, HEAD)[0], "pending")


if __name__ == "__main__":
    unittest.main()
