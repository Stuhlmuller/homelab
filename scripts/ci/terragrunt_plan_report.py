#!/usr/bin/env python3
from __future__ import annotations

import argparse
import json
import os
import re
import textwrap
import urllib.error
import urllib.request
from pathlib import Path

START_MARKER = "<!-- homelab-terragrunt-plan:start -->"
END_MARKER = "<!-- homelab-terragrunt-plan:end -->"
PLAN_LINE_RE = re.compile(
    r"Plan:\s+(?P<add>\d+)\s+to add,\s+(?P<change>\d+)\s+to change,\s+(?P<destroy>\d+)\s+to destroy\."
)
NO_CHANGES_RE = re.compile(r"^\s*No changes\.", re.MULTILINE)
ERROR_LINE_RE = re.compile(r"^\s*Error: .+$", re.MULTILINE)


def parse_plan_stats(log_text: str) -> dict[str, object]:
    totals = {"add": 0, "change": 0, "destroy": 0}
    plan_blocks = 0
    for match in PLAN_LINE_RE.finditer(log_text):
        plan_blocks += 1
        totals["add"] += int(match.group("add"))
        totals["change"] += int(match.group("change"))
        totals["destroy"] += int(match.group("destroy"))

    no_change_blocks = len(NO_CHANGES_RE.findall(log_text))
    error_lines = []
    seen_errors = set()
    for line in ERROR_LINE_RE.findall(log_text):
        stripped = line.strip()
        if stripped not in seen_errors:
            seen_errors.add(stripped)
            error_lines.append(stripped)

    if not error_lines:
        for line in [line.strip() for line in log_text.splitlines() if line.strip()]:
            if "exit status" in line.lower() or "unable to determine underlying exit code" in line.lower():
                if line not in seen_errors:
                    seen_errors.add(line)
                    error_lines.append(line)

    return {
        "plan_blocks": plan_blocks,
        "no_change_blocks": no_change_blocks,
        "totals": totals,
        "error_lines": error_lines,
    }


def build_plan_section(
    *,
    status: str,
    working_dir: str,
    run_url: str,
    artifact_name: str,
    commit_sha: str,
    log_text: str = "",
    exit_code: int = 0,
    summary_lines: list[str] | None = None,
) -> str:
    rendered_summary_lines = list(summary_lines or [])
    stats = parse_plan_stats(log_text)
    totals = stats["totals"]

    if not rendered_summary_lines:
        if stats["plan_blocks"]:
            rendered_summary_lines.append(
                f"- Aggregated {stats['plan_blocks']} Terraform plan summaries: "
                f"{totals['add']} to add, {totals['change']} to change, {totals['destroy']} to destroy."
            )
        if stats["no_change_blocks"]:
            rendered_summary_lines.append(f"- {stats['no_change_blocks']} unit(s) reported no changes.")
        if not rendered_summary_lines:
            if status == "success":
                rendered_summary_lines.append("- Plan completed successfully, but no Terraform summary line was detected in the captured log.")
            elif status == "skipped":
                rendered_summary_lines.append("- Plan was skipped.")
            else:
                rendered_summary_lines.append("- Plan failed before Terraform emitted a standard summary line.")

    section_lines = [
        START_MARKER,
        "## Homelab Terragrunt Plan",
        "",
        f"- Status: `{status}`",
        f"- Stack: `{working_dir}`",
        f"- Commit: `{commit_sha[:12]}`",
        f"- Run: [Workflow run]({run_url})",
        f"- Artifact: `{artifact_name}`",
        "",
        "### Summary",
        "",
        *rendered_summary_lines,
    ]

    error_lines = list(stats["error_lines"])
    if status == "failed" and exit_code != 0 and error_lines:
        excerpt = "\n".join(error_lines[:10])
        section_lines.extend(
            [
                "",
                "<details><summary>Relevant errors</summary>",
                "",
                "```text",
                excerpt,
                "```",
                "",
                "</details>",
            ]
        )

    section_lines.append(END_MARKER)
    return "\n".join(section_lines).strip() + "\n"


def merge_managed_section(body: str, section: str) -> str:
    body = body or ""
    start = body.find(START_MARKER)
    end = body.find(END_MARKER)
    if start != -1 and end != -1 and start < end:
        end += len(END_MARKER)
        replacement = section.strip()
        updated = f"{body[:start].rstrip()}\n\n{replacement}\n\n{body[end:].lstrip()}".strip()
        return updated + "\n"

    if not body.strip():
        return section.strip() + "\n"

    return f"{body.rstrip()}\n\n{section.strip()}\n"


def github_api_request(*, method: str, url: str, token: str, payload: dict[str, object] | None = None) -> dict[str, object]:
    data = None
    headers = {
        "Accept": "application/vnd.github+json",
        "Authorization": f"Bearer {token}",
        "User-Agent": "homelab-ci",
    }
    if payload is not None:
        data = json.dumps(payload).encode("utf-8")
        headers["Content-Type"] = "application/json"

    request = urllib.request.Request(url, data=data, headers=headers, method=method)
    try:
        with urllib.request.urlopen(request, timeout=30) as response:
            raw = response.read().decode("utf-8")
    except urllib.error.HTTPError as exc:
        detail = exc.read().decode("utf-8", errors="replace")
        raise SystemExit(f"GitHub API request failed ({exc.code}): {detail}") from exc

    return json.loads(raw) if raw else {}


def render_command(args: argparse.Namespace) -> int:
    log_text = Path(args.log_file).read_text() if Path(args.log_file).exists() else ""
    section = build_plan_section(
        status="success" if args.exit_code == 0 else "failed",
        log_text=log_text,
        exit_code=args.exit_code,
        working_dir=args.working_dir,
        run_url=args.run_url,
        artifact_name=args.artifact_name,
        commit_sha=args.commit_sha,
    )
    output_path = Path(args.output_file)
    output_path.parent.mkdir(parents=True, exist_ok=True)
    output_path.write_text(section)
    return 0


def render_static_command(args: argparse.Namespace) -> int:
    section = build_plan_section(
        status=args.status,
        working_dir=args.working_dir,
        run_url=args.run_url,
        artifact_name=args.artifact_name,
        commit_sha=args.commit_sha,
        summary_lines=args.summary_line,
    )
    output_path = Path(args.output_file)
    output_path.parent.mkdir(parents=True, exist_ok=True)
    output_path.write_text(section)
    return 0


def update_pr_body_command(args: argparse.Namespace) -> int:
    token = os.environ.get("GITHUB_TOKEN")
    if not token:
        raise SystemExit("GITHUB_TOKEN is required to update the pull request body")

    summary = Path(args.summary_file).read_text()
    pr_url = f"https://api.github.com/repos/{args.repo}/pulls/{args.pr_number}"
    pull_request = github_api_request(method="GET", url=pr_url, token=token)
    updated_body = merge_managed_section(str(pull_request.get("body") or ""), summary)
    if updated_body == str(pull_request.get("body") or ""):
        return 0

    github_api_request(
        method="PATCH",
        url=pr_url,
        token=token,
        payload={"body": updated_body},
    )
    return 0


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description="Render and maintain the managed Terragrunt plan section in PR descriptions.",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog=textwrap.dedent(
            """\
            Commands:
              render          Build the markdown section from a Terragrunt plan log.
              update-pr-body  Merge the rendered section into the current PR description.
            """
        ),
    )
    subparsers = parser.add_subparsers(dest="command", required=True)

    render = subparsers.add_parser("render")
    render.add_argument("--log-file", required=True)
    render.add_argument("--exit-code", required=True, type=int)
    render.add_argument("--working-dir", required=True)
    render.add_argument("--run-url", required=True)
    render.add_argument("--artifact-name", required=True)
    render.add_argument("--commit-sha", required=True)
    render.add_argument("--output-file", required=True)
    render.set_defaults(func=render_command)

    render_static = subparsers.add_parser("render-static")
    render_static.add_argument("--status", choices=("success", "failed", "skipped"), required=True)
    render_static.add_argument("--working-dir", required=True)
    render_static.add_argument("--run-url", required=True)
    render_static.add_argument("--artifact-name", required=True)
    render_static.add_argument("--commit-sha", required=True)
    render_static.add_argument("--summary-line", action="append", required=True)
    render_static.add_argument("--output-file", required=True)
    render_static.set_defaults(func=render_static_command)

    update_pr_body = subparsers.add_parser("update-pr-body")
    update_pr_body.add_argument("--repo", required=True)
    update_pr_body.add_argument("--pr-number", required=True, type=int)
    update_pr_body.add_argument("--summary-file", required=True)
    update_pr_body.set_defaults(func=update_pr_body_command)

    return parser


def main() -> int:
    parser = build_parser()
    args = parser.parse_args()
    return args.func(args)


if __name__ == "__main__":
    raise SystemExit(main())
