#!/usr/bin/env python3
"""Keep reviewed public/test values out of failures without hiding new findings."""
import collections
import json
import os
from pathlib import Path, PurePosixPath
import re
import subprocess
import sys
import tempfile

ROOT = Path(__file__).resolve().parents[2]
REVIEWS = ROOT / "scripts/config/checkov-reviewed-findings.json"
VERSIONS = ("3.2.495", "3.2.529")
FINGERPRINT = re.compile(r"[0-9a-f]{40}")
CHECK = re.compile(r"CKV_[A-Z0-9_]+")
MAX_FILE_SIZE = 5_000_000
FRAMEWORKS = {"terraform", "kubernetes", "dockerfile", "secrets", "github_actions",
              "cloudformation", "arm", "bicep", "helm", "kustomize", "serverless",
              "terraform_plan", "sca_package", "sca_image", "openapi", "gitlab_ci",
              "ansible", "bitbucket_pipelines", "circleci", "azure_pipelines", "sast"}


class ReviewError(Exception):
    """Only fixed, non-sensitive diagnostic messages may cross this boundary."""


def require(condition, message):
    if not condition:
        raise ReviewError(message)


def object_pairs(pairs):
    result = {}
    for key, value in pairs:
        require(key not in result, "Duplicate JSON key")
        result[key] = value
    return result


def decode(raw):
    try:
        return json.loads(raw, object_pairs_hook=object_pairs)
    except (ValueError, TypeError):
        raise ReviewError("Invalid scanner or review JSON") from None


def relative_path(value):
    require(isinstance(value, str) and bool(value), "Missing repository path")
    path = PurePosixPath(value)
    require(not path.is_absolute() and not value.startswith("-") and "\\" not in value and
            all(part not in ("", ".", "..") for part in value.split("/")) and
            not any(ord(char) < 32 for char in value), "Unsafe repository path")
    return str(path)


def selected_files(root, values):
    require(bool(values), "No files selected for scanning")
    selected = set()
    for value in values:
        path = relative_path(value)
        target = root / path
        require(target.is_file() and target.resolve() == target,
                "Selected input must be an existing repository file without symlinks")
        require(target.stat().st_mode & 0o444, "Selected file has no read permission")
        require(target.stat().st_size <= MAX_FILE_SIZE, "Selected file exceeds the scanner size limit")
        try:
            target.read_text(encoding="utf-8")
        except (OSError, UnicodeError):
            raise ReviewError("Selected file is unreadable or is not UTF-8 text") from None
        selected.add(path)
    return selected


def load_reviews(raw):
    data = decode(raw)
    require(isinstance(data, dict) and set(data) == {"version", "checkov_versions", "findings"}
            and type(data["version"]) is int and data["version"] == 1
            and data["checkov_versions"] == list(VERSIONS) and isinstance(data["findings"], list),
            "Invalid reviewed-finding document")
    reviews = {}
    for item in data["findings"]:
        require(isinstance(item, dict) and set(item) == {
            "path", "check_id", "fingerprint", "max_occurrences", "reason"},
            "Invalid reviewed-finding entry")
        path = relative_path(item["path"])
        require(item["check_id"] == "CKV_SECRET_6" and
                isinstance(item["fingerprint"], str) and FINGERPRINT.fullmatch(item["fingerprint"])
                and type(item["max_occurrences"]) is int and 1 <= item["max_occurrences"] <= 10
                and isinstance(item["reason"], str) and bool(item["reason"].strip()),
                "Invalid reviewed-finding identity or limit")
        key = (path, item["check_id"], item["fingerprint"])
        require(key not in reviews, "Duplicate reviewed-finding identity")
        reviews[key] = item["max_occurrences"]
    return reviews


def assess(raw, returncode, mode, root, selected, reviews):
    require(returncode in (0, 1), "Scanner process did not complete normally")
    data = decode(raw)
    # Pinned Checkov omits empty frameworks and emits this summary when all are empty.
    empty = {name: 0 for name in ("passed", "failed", "skipped", "parsing_errors", "resource_count")}
    empty["checkov_version"] = data.get("checkov_version") if isinstance(data, dict) else None
    if isinstance(data, dict) and set(data) == set(empty):
        require(data == empty and empty["checkov_version"] in VERSIONS
                and all(type(data[name]) is int for name in empty if name != "checkov_version")
                and returncode == 0, "Invalid empty scanner summary")
        return 0, []
    reports = data if isinstance(data, list) else [data]
    require(bool(reports), "Scanner returned no framework reports")
    seen = set()
    failures = 0
    reviewed = 0
    remaining = []
    occurrences = collections.Counter()
    for report in reports:
        require(isinstance(report, dict), "Invalid framework report")
        framework = report.get("check_type")
        require(isinstance(framework, str) and framework in FRAMEWORKS and framework not in seen,
                "Unknown or duplicate framework report")
        seen.add(framework)
        summary, results = report.get("summary"), report.get("results")
        require(isinstance(summary, dict) and isinstance(results, dict), "Missing scanner results")
        require(summary.get("checkov_version") in VERSIONS, "Scanner version differs from reviewed pin")
        for name in ("passed", "failed", "skipped", "parsing_errors", "resource_count"):
            require(type(summary.get(name)) is int and summary[name] >= 0, "Invalid scanner summary")
        require(summary["parsing_errors"] == 0, "Scanner reported parsing errors")
        failed = results.get("failed_checks")
        require(isinstance(failed, list) and len(failed) == summary["failed"],
                "Scanner failure count does not match records")
        failures += len(failed)
        for finding in failed:
            require(isinstance(finding, dict), "Invalid scanner finding")
            check = finding.get("check_id")
            require(isinstance(check, str) and CHECK.fullmatch(check), "Invalid scanner check ID")
            require(isinstance(finding.get("check_result"), dict) and
                    finding["check_result"].get("result") == "FAILED", "Invalid failure status")
            # Checkov emits slash-prefixed repository paths, plus their absolute path.
            value = finding.get("file_path")
            require(isinstance(value, str), "Missing finding path")
            path = relative_path(value[1:] if value.startswith("/") else value)
            require(path in selected and finding.get("file_abs_path") == str(root / path),
                    "Finding is outside the selected repository files")
            lines = finding.get("file_line_range")
            require(isinstance(lines, list) and len(lines) == 2 and
                    all(type(line) is int and line >= 1 for line in lines) and lines[1] >= lines[0],
                    "Invalid finding line range")
            fingerprint = finding.get("resource")
            key = (path, check, fingerprint) if isinstance(fingerprint, str) else None
            if framework == "secrets" and key in reviews:
                occurrences[key] += 1
                require(occurrences[key] <= reviews[key], "Reviewed finding occurrence limit exceeded")
                reviewed += 1
            else:
                remaining.append((check, path, lines[0]))
    require(mode != "secrets" or seen == {"secrets"}, "Unexpected secret scanner framework")
    require(returncode == (1 if failures else 0), "Scanner exit code contradicts findings")
    return reviewed, remaining


def main(arguments):
    require(len(arguments) >= 3 and arguments[0] in ("diff", "secrets") and arguments[1] == "-f",
            "Expected scan mode followed by -f and repository files")
    root = ROOT.resolve()
    selected = selected_files(root, arguments[2:])
    reviews = load_reviews(REVIEWS.read_text())
    command = ["checkov", "--enable-secret-scan-all-files", "--output", "json"]
    if arguments[0] == "secrets":
        command += ["--framework", "secrets"]
    command += ["-f", *sorted(selected)]
    environment = os.environ.copy()
    environment.pop("CHECKOV_MAX_FILE_SIZE", None)
    result = subprocess.run(command, cwd=root, capture_output=True, text=True, timeout=600, env=environment)
    # Scanner output may contain source snippets: retain it privately, never forward it.
    descriptor, log = tempfile.mkstemp(prefix="homelab-checkov-", suffix=".log")
    with os.fdopen(descriptor, "w") as output:
        output.write(result.stdout)
        output.write("\n--- scanner stderr ---\n")
        output.write(result.stderr)
    try:
        require(not result.stderr.strip(), "Scanner emitted diagnostics; inspect the private log")
        reviewed, remaining = assess(result.stdout, result.returncode, arguments[0], root, selected, reviews)
    except ReviewError:
        print(f"Private scanner diagnostics: {log}", file=sys.stderr)
        raise
    for check, path, line in remaining:
        print(f"{check}: {path}:{line}")
    print(f"Checkov: {len(selected)} selected files; {reviewed} reviewed findings; {len(remaining)} unreviewed findings")
    return bool(remaining)


if __name__ == "__main__":
    try:
        sys.exit(main(sys.argv[1:]))
    except ReviewError as error:
        sys.exit(str(error))
    except (OSError, subprocess.SubprocessError, UnicodeError):
        sys.exit("Checkov review scan could not complete; private details withheld")
