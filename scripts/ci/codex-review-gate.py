"""Publish a status for the head evaluated by Codex Code Review."""

import json
import os
import re
import subprocess


SUMMARY = "<!-- codex-pull-request-review-summary -->"
RECEIPT = re.compile(r"^<!-- codex-review-state:v1 (.+) -->$", re.MULTILINE)
CONTEXT = "Codex Code Review"


def review_status(comments, head):
    summaries = [
        comment for comment in comments
        if (comment.get("user") or {}).get("id") == 199175422
        and (comment.get("performed_via_github_app") or {}).get("id") == 1144995
        and (comment.get("body") or "").startswith(SUMMARY + "\n")
    ]
    if summaries:
        latest = max(summaries, key=lambda comment: comment["id"])
        receipts = RECEIPT.findall(latest["body"])
        if len(receipts) == 1:
            try:
                review = json.loads(receipts[0])["code_review"]
            except (ValueError, KeyError, TypeError):
                review = None
            if (
                isinstance(review, dict)
                and review.get("commit_sha") == head
                and review.get("status") == "completed"
            ):
                if review.get("has_any_findings") is True:
                    return "failure", "Codex code review reported findings"
                if (
                    review.get("has_any_findings") is False
                    and review.get("has_unresolved_findings") is False
                ):
                    return "success", "Codex code review completed with zero findings"
    return "pending", "Waiting for a clean Codex code review of this commit"


def api(*args):
    return json.loads(
        subprocess.check_output(["gh", "api", *args], text=True)
    )


def main():
    repository = os.environ["GITHUB_REPOSITORY"]
    number = os.environ["PR_NUMBER"]
    if not re.fullmatch(r"[1-9][0-9]*", number):
        raise ValueError("Expected a positive pull request number")
    repo = f"repos/{repository}"
    pull = api(f"{repo}/pulls/{number}")
    if pull["state"] != "open" or pull["base"]["ref"] != "main":
        return
    head = pull["head"]["sha"]
    if not re.fullmatch(r"[0-9a-f]{40}", head):
        raise ValueError("Expected a full pull request head SHA")

    pages = api("--paginate", "--slurp", f"{repo}/issues/{number}/comments?per_page=100")
    state, description = review_status(
        (comment for page in pages for comment in page), head
    )
    api(
        "--method", "POST", f"{repo}/statuses/{head}",
        "-f", f"context={CONTEXT}",
        "-f", f"state={state}",
        "-f", f"description={description}",
        "-f", f"target_url=https://github.com/{repository}/pull/{number}",
    )
    print(f"{CONTEXT} for PR #{number} at {head}: {state}")


if __name__ == "__main__":
    main()
