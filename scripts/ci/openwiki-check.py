#!/usr/bin/env python3
"""Check the repository wiki's local links, navigation, and agent entrypoints."""

import html
import json
import re
import subprocess
import sys
import tempfile
from pathlib import Path
from urllib.parse import unquote, urlsplit

LINK = re.compile(r'\]\(\s*(?:<([^>]+)>|((?:\\.|[^\s()]|\([^()]*\))+))(?:\s+["\'][^\n]*?["\'])?\s*\)')
REFERENCE_LINK = re.compile(r'\[(?:\\.|[^\]\\\r\n])+\]:[ \t]*(?:\r?\n[ \t]*)?(?:<([^<>\r\n]+)>|(\S+))')
ANGLE_LINK = re.compile(r"<([^<>\r\n]+)>")
URL = re.compile(r'''(?:[A-Za-z][A-Za-z0-9+.-]*:)?//[^\s<>"'`]+''')
INLINE_CODE = re.compile(r'(`+)(.*?)\1', re.DOTALL)
FRONTMATTER = re.compile(r'\A---\n(.*?)\n---(?:\n|$)', re.DOTALL)


def unique_keys(pairs):
    fields = dict(pairs)
    if len(fields) != len(pairs):
        raise ValueError("YAML frontmatter keys must be unique")
    return fields


def validate_frontmatter(text):
    frontmatter = FRONTMATTER.match(text)
    if not frontmatter:
        raise ValueError("missing frontmatter")
    try:
        result = subprocess.run(
            ["yq", "eval", "-o=json", ".", "-"], input=frontmatter[1],
            capture_output=True, check=True, text=True,
        )
        fields = json.loads(result.stdout, object_pairs_hook=unique_keys)
    except FileNotFoundError:
        sys.exit("OpenWiki check requires yq; run nix develop --command python3 -I scripts/ci/openwiki-check.py")
    except subprocess.CalledProcessError as error:
        raise ValueError(f"invalid YAML frontmatter: {error.stderr.strip()}") from error
    except json.JSONDecodeError as error:
        raise ValueError(f"invalid YAML frontmatter: {error}") from error
    if not isinstance(fields, dict):
        raise TypeError("frontmatter must be a mapping")
    invalid = [name for name in ("type", "title", "description")
               if not isinstance(fields.get(name), str) or not fields[name].strip()]
    tags = fields.get("tags")
    if not isinstance(tags, list) or any(not isinstance(tag, str) or not tag.strip() for tag in tags):
        invalid.append("tags")
    if invalid:
        raise ValueError(f"invalid frontmatter fields: {', '.join(invalid)}")


def prose(text):
    """Ignore fenced examples, comments, and frontmatter; preserve line numbers."""
    text = FRONTMATTER.sub(lambda match: "\n" * match[0].count("\n"), text)
    text = re.sub(r'<!--.*?-->', lambda match: "\n" * match[0].count("\n"), text, flags=re.DOTALL)
    lines = []
    fence = None
    for line in text.splitlines(keepends=True):
        marker = re.match(r'^ {0,3}(`{3,}|~{3,})', line)
        if marker and fence is None:
            fence = marker[1]
            lines.append("\n")
        elif fence is not None:
            if re.fullmatch(r' {0,3}' + re.escape(fence[0]) + r'{' + str(len(fence)) + r',}\s*', line):
                fence = None
            lines.append("\n")
        else:
            lines.append(line)
    return "".join(lines)


def anchors(text):
    text = prose(text)
    result = set(re.findall(r'<a\s+[^>]*?(?:id|name)=["\']([^"\']+)["\']', text))
    for match in re.finditer(r'^ {0,3}#{1,6}\s+(.+?)\s*#*\s*$', text, re.MULTILINE):
        heading = re.sub(r'!?\[([^]]+)\]\([^)]*\)', r'\1', match[1])
        heading = INLINE_CODE.sub(r'\2', heading)
        heading = html.unescape(re.sub(r'<[^>]+>', '', heading))
        base = re.sub(r'[^\w\-\s]', '', heading.lower())
        base = re.sub(r'\s', '-', base)
        slug, number = base, 0
        while slug in result:
            number += 1
            slug = f"{base}-{number}"
        result.add(slug)
    return result


def check(root):
    root = root.resolve()
    wiki = root / "openwiki"
    pages = {path: path.read_text() for path in sorted(wiki.rglob("*.md"))}
    content = set(pages) - {wiki / "INSTRUCTIONS.md"}
    edges = {page: set() for page in pages}
    errors = []
    heading_cache = {}
    skills = root / ".agents/skills"
    documents = pages | {path: path.read_text() for path in sorted(skills.rglob("*.md"))}
    entry = wiki / "quickstart.md"
    if entry not in pages:
        errors.append("openwiki/quickstart.md: missing wiki entrypoint")

    for page, text in documents.items():
        relative = page.relative_to(root)
        if page in content and page.name != "index.md":
            try:
                validate_frontmatter(text)
            except (TypeError, ValueError) as error:
                errors.append(f"{relative}: {error}")
        body = INLINE_CODE.sub(lambda match: "\n" * match[0].count("\n"), prose(text))
        if page in pages and re.search(r'\[\[[^\]\n]+\]\]', body):
            errors.append(f"{relative}: leftover Obsidian wikilink; use a relative Markdown link")
        for match in LINK.finditer(body):
            href = match[1] or match[2]
            link = urlsplit(href)
            if link.scheme or link.netloc or link.path.startswith("/"):
                continue
            path = unquote(link.path)
            if any(char in path for char in "*?[]{}"):
                continue
            target = (page.parent / path).resolve() if path else page
            location = f"{relative}:{body.count(chr(10), 0, match.start()) + 1}"
            if not target.is_relative_to(root) or not target.exists():
                errors.append(f"{location}: broken link {href}")
                continue
            if page in pages and target in pages:
                edges[page].add(target)
            if link.fragment and target.is_file() and target.suffix.lower() == ".md":
                if target not in heading_cache:
                    heading_cache[target] = anchors(target.read_text())
                if unquote(link.fragment) not in heading_cache[target]:
                    errors.append(f"{location}: broken heading anchor {href}")

    reached, pending = set(), [entry] if entry in pages else []
    while pending:
        page = pending.pop()
        if page not in reached:
            reached.add(page)
            pending.extend(edges[page] - reached)
    for page in sorted(content - reached):
        errors.append(f"{page.relative_to(root)}: unreachable from openwiki/quickstart.md")

    for name in ("openwiki", "homelab-knowledge-base"):
        if not (skills / name / "SKILL.md").is_file():
            errors.append(f".agents/skills/{name}/SKILL.md: missing agent entrypoint")
    retired = root / "docs/knowledge-base"
    sources = subprocess.run(
        ["git", "-C", str(root), "ls-files", "--cached", "--others", "--exclude-standard", "-z"],
        capture_output=True, check=True, text=True,
    ).stdout.split("\0")
    # This checker contains deliberate stale-reference fixtures.
    for name in sorted(set(sources) - {"", "scripts/ci/openwiki-check.py"}):
        path = root / name
        if path.is_symlink() or not path.is_file():
            continue
        data = path.read_bytes()
        if b"\0" in data:
            continue
        text = data.decode(errors="replace")
        targets = []
        plain = text
        for pattern in (LINK, REFERENCE_LINK):
            targets.extend(match[1] or match[2] for match in pattern.finditer(plain))
            plain = pattern.sub(" ", plain)
        for pattern in (ANGLE_LINK, URL):
            targets.extend(pattern.findall(plain))
            plain = pattern.sub(" ", plain)
        targets.extend(re.findall(r'''[^\s<>"'`()\[\]{},;=:]+/[^\s<>"'`()\[\]{},;=:]*''', plain))
        stale = re.search(r"(?<![\w./\\-])docs/knowledge-base(?=$|[^\w.-])", plain) or re.search(
            r"(?m)^docs/\r?\n(?:[ │]*[├└]── [^\r\n]*\r?\n)*[├└]── knowledge-base/", text,
        )
        for target in targets:
            try:
                link = urlsplit(target)
            except ValueError:
                # Source literals also include URL templates and regular expressions.
                continue
            if link.scheme == "repo":
                candidate = root / unquote(link.netloc + link.path).lstrip("/")
            elif link.scheme in ("", "http", "https") and link.netloc.lower() in (
                "github.com", "raw.githubusercontent.com",
            ):
                view = r"(?:blob|tree|raw)/" if link.netloc.lower() == "github.com" else ""
                github = re.fullmatch(r"/Stuhlmuller/homelab/" + view + r"[^/]+/(.+)",
                                      unquote(link.path), re.IGNORECASE)
                if not github:
                    continue
                candidate = root / github[1]
            elif link.scheme or link.netloc or link.path.startswith("/"):
                continue
            else:
                candidate = path.parent / unquote(link.path)
            if candidate.resolve().is_relative_to(retired):
                stale = True
                break
        if stale:
            errors.append(f"{name}: stale docs/knowledge-base reference")
    return errors


def self_test():
    with tempfile.TemporaryDirectory(prefix="openwiki check ") as temporary:
        root = Path(temporary)
        subprocess.run(["git", "init", "--quiet", str(root)], check=True)
        wiki = root / "openwiki"
        wiki.mkdir()
        header = "---\ntype: reference\ntitle: Test\ndescription: A fixture.\ntags:\n  - test\n---\n"
        for name in ("openwiki", "homelab-knowledge-base"):
            skill = root / ".agents/skills" / name / "SKILL.md"
            skill.parent.mkdir(parents=True)
            skill.write_text("# Skill\n")
        (root / "README.md").write_text("# Source `config` & recovery\n")
        (wiki / "topic.md").write_text(header + "# Topic\n## Repeated\n## Repeated\n")
        (wiki / "INSTRUCTIONS.md").write_text("# Instructions\n")
        quickstart = wiki / "quickstart.md"
        valid = header + """# Start
[topic](topic.md#repeated-1) [source](../README.md#source-config--recovery)
[external](https://example.com/missing) [glob](../missing/*.yaml)
`[inline example](missing.md) [[inline wikilink example]]`
~~~md
[fenced example](missing.md) [[fenced wikilink example]]
~~~
<!-- [comment](missing.md) -->
"""
        quickstart.write_text(valid)
        assert not check(root), check(root)
        for old, new, expected in (
            ("tags:\n  - test", "tags: [", "invalid YAML frontmatter"),
            ("title: Test", "title: []\ntitle: Test", "YAML frontmatter keys must be unique"),
            (header, "---\n- reference\n---\n", "frontmatter must be a mapping"),
            ("title: Test", "title: [Test]", "invalid frontmatter fields: title"),
            ("tags:\n  - test", "tags: test", "invalid frontmatter fields: tags"),
            ("tags:\n  - test", "tags: [1]", "invalid frontmatter fields: tags"),
        ):
            quickstart.write_text(valid.replace(old, new))
            assert any(expected in error for error in check(root)), expected
        quickstart.write_text(valid)
        skill = root / ".agents/skills/openwiki/SKILL.md"
        skill.write_text("[Missing](missing.md)\n")
        assert any("SKILL.md:1: broken link" in error for error in check(root))
        skill.write_text("# Skill\n")
        for link, expected in (("[bad](missing.md)", "broken link"),
                               ("[bad](topic.md#missing)", "broken heading anchor"),
                               ("[[topic|Old link]]", "leftover Obsidian wikilink")):
            quickstart.write_text(valid + link)
            assert any(expected in error for error in check(root)), expected
        quickstart.write_text(valid.replace("[topic](topic.md#repeated-1)", ""))
        assert any("unreachable" in error for error in check(root))
        quickstart.write_text(valid)
        (wiki / "topic.md").write_text("# Topic\n## Repeated\n## Repeated\n")
        assert any("missing frontmatter" in error for error in check(root))
        (wiki / "topic.md").write_text(header + "# Topic\n## Repeated\n## Repeated\n")
        subprocess.run(["git", "-C", str(root), "add", "README.md"], check=True)
        for name in (".agents/skills/openwiki/SKILL.md", "clusters/app/values.yaml",
                     "docs/runbook.md", "README.md", "AGENTS.md", "specs/feature/spec.md",
                     "IaC/stack.hcl", "scripts/operator.sh", ".github/workflows/check.yml"):
            source = root / name
            source.parent.mkdir(parents=True, exist_ok=True)
            saved = source.read_text() if source.exists() else ""
            source.write_text("docs/knowledge-base/00-home.md")
            assert f"{name}: stale docs/knowledge-base reference" in check(root)
            source.write_text(saved)
        plan = root / "specs/feature/plan.md"
        for tree in ("docs/\n\u2514\u2500\u2500 knowledge-base/\n",
                     "docs/\n\u251c\u2500\u2500 one.md\n\u251c\u2500\u2500 two.md\n\u2514\u2500\u2500 knowledge-base/\n"):
            plan.write_text(tree)
            assert "specs/feature/plan.md: stale docs/knowledge-base reference" in check(root)
        plan.write_text(".agents/skills/\n\u2514\u2500\u2500 homelab-knowledge-base/\nopenwiki/\n")
        runbook = root / "docs/runbook.md"
        for target in ("knowledge-base/00-home.md", "./knowledge-base/00-home.md",
                       "%6bnowledge-base/00-home.md"):
            runbook.write_text(f"[old page]({target})\n")
            assert "docs/runbook.md: stale docs/knowledge-base reference" in check(root)
        for text in ("[legacy]: knowledge-base/00-home.md",
                     '[legacy]: <./knowledge-base/00-home.md> "Old page"',
                     "[legacy]:\n    %6bnowledge-base/00-home.md 'Old page'",
                     "[old page](<knowledge-base/00-home.md>)", "<knowledge-base/00-home.md>"):
            runbook.write_text(text)
            assert "docs/runbook.md: stale docs/knowledge-base reference" in check(root), text
        for text in ("[vendor](https://vendor.example/knowledge-base/article)",
                     "[other](../other/knowledge-base/article.md)", "other/knowledge-base/article.md",
                     '[vendor]: <https://vendor.example/knowledge-base/article> "Vendor"',
                     "[other]:\n    ../other/knowledge-base/article.md",
                     "<https://vendor.example/knowledge-base/article>", "<../other/knowledge-base/article.md>",
                     "[current skill](../.agents/skills/homelab-knowledge-base/SKILL.md)"):
            runbook.write_text(text)
            assert not check(root), check(root)
        for target, rejected in (
            ("https://vendor.example/docs/knowledge-base/article", False),
            ("https://vendor.example/?path=docs/knowledge-base/article", False),
            ("//vendor.example/docs/knowledge-base/article", False),
            ("https://github.com/other/repo/blob/main/docs/knowledge-base/article", False),
            ("https://github.com/Stuhlmuller/homelab/blob/main/other/docs/knowledge-base/article", False),
            ("https://raw.githubusercontent.com/other/repo/main/docs/knowledge-base/article", False),
            ("https://raw.githubusercontent.com/Stuhlmuller/homelab/main/other/docs/knowledge-base/article", False),
            ("other/docs/knowledge-base/article.md", False),
            ("docs/knowledge-base-backup/article.md", False),
            ("repo://other/docs/knowledge-base/article.md", False),
            ("https://github.com/Stuhlmuller/homelab/blob/main/docs/knowledge-base/article.md", True),
            ("//github.com/Stuhlmuller/homelab/blob/main/docs/knowledge-base/article.md", True),
            ("https://raw.githubusercontent.com/Stuhlmuller/homelab/main/docs/knowledge-base/article.md", True),
            ("repo://docs/knowledge-base/article.md", True),
        ):
            for template in ("{}", "[reference]({})", "[reference]: {}", "<{}>"):
                runbook.write_text(template.format(target))
                errors = check(root)
                expected = ["docs/runbook.md: stale docs/knowledge-base reference"] if rejected else []
                assert errors == expected, (target, template, errors)
        for text in ('path = "docs/knowledge-base/article.md"', "# See docs/knowledge-base/article.md"):
            runbook.write_text(text)
            assert "docs/runbook.md: stale docs/knowledge-base reference" in check(root), text
        runbook.write_text('[nested docs](docs/knowledge-base/article.md)\npattern = "^https://[^/]+"\n')
        assert not check(root), check(root)
        for name, target, rejected in (
            ("scripts/foo.sh", "../docs/knowledge-base/00-home.md", True),
            ("scripts/nested/foo.sh", "../../docs/knowledge-base/00-home.md", True),
            ("scripts/foo.sh", "../other/../docs/knowledge-base/00-home.md", True),
            ("scripts/foo.sh", "../other/docs/knowledge-base/00-home.md", False),
            ("scripts/foo.sh", "./docs/knowledge-base/00-home.md", False),
            ("operator.sh", "./docs/knowledge-base/00-home.md", True),
            ("operator.sh", "other/../docs/knowledge-base/00-home.md", True),
            ("docs/consumer.txt", "knowledge-base/00-home.md", True),
        ):
            source = root / name
            source.parent.mkdir(parents=True, exist_ok=True)
            source.write_text(f'cat "{target}"\n')
            errors = check(root)
            expected = [f"{name}: stale docs/knowledge-base reference"] if rejected else []
            assert errors == expected, (name, target, errors)
            source.write_text("")
        for tree in ("other/\n\u2514\u2500\u2500 knowledge-base/\n",
                     "docs/\n\u2514\u2500\u2500 runbook.md\nother/\n\u2514\u2500\u2500 knowledge-base/\n",
                     "docs/\n\u2514\u2500\u2500 other/\n    \u2514\u2500\u2500 knowledge-base/\n"):
            plan.write_text(tree)
            assert not check(root), check(root)
        (root / ".gitignore").write_text("ignored-secret\n")
        (root / "ignored-secret").write_text("docs/knowledge-base/private.md")
        (root / "secret-link").symlink_to(root / "ignored-secret")
        (root / "binary").write_bytes(b"\0docs/knowledge-base")
        guard = root / "scripts/ci/openwiki-check.py"
        guard.parent.mkdir(parents=True)
        guard.write_text("docs/knowledge-base")
        assert not check(root), check(root)


if __name__ == "__main__":
    if sys.argv[1:] not in ([], ["--self-test"]):
        sys.exit("usage: openwiki-check.py [--self-test]")
    self_test()
    failures = [] if sys.argv[1:] else check(Path(__file__).resolve().parents[2])
    if failures:
        sys.exit("\n".join(failures))
    print("OpenWiki links, navigation, frontmatter, and agent entrypoints passed")
