#!/usr/bin/env python3
"""Check the repository wiki's local links, navigation, and agent entrypoints."""

import html
import re
import sys
import tempfile
from os.path import relpath
from pathlib import Path
from urllib.parse import unquote, urlsplit

LINK = re.compile(r'\]\(\s*(?:<([^>]+)>|((?:\\.|[^\s()]|\([^()]*\))+))(?:\s+["\'][^\n]*?["\'])?\s*\)')
INLINE_CODE = re.compile(r'(`+)(.*?)\1', re.DOTALL)
FRONTMATTER = re.compile(r'\A---\n(.*?)\n---(?:\n|$)', re.DOTALL)
COMPATIBILITY = (
    "docs/knowledge-base/00-home.md",
    "docs/knowledge-base/architecture/cluster-topology.md",
    "docs/knowledge-base/operations/pvc-metrics-recovery.md",
)


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
    for name in COMPATIBILITY:
        path = root / name
        if path.is_file():
            documents[path] = path.read_text()
        else:
            errors.append(f"{name}: missing compatibility page")
    entry = wiki / "quickstart.md"
    if entry not in pages:
        errors.append("openwiki/quickstart.md: missing wiki entrypoint")

    for page, text in documents.items():
        relative = page.relative_to(root)
        if page in content and page.name != "index.md":
            frontmatter = FRONTMATTER.match(text)
            fields = dict(re.findall(r'^(\w+):[ \t]*(.*?)(?=^\w+:|\Z)', frontmatter[1], re.MULTILINE | re.DOTALL)) if frontmatter else {}
            missing = [field for field in ("type", "title", "description", "tags")
                       if not fields.get(field, "").strip().strip('"\'')]
            if missing:
                errors.append(f"{relative}: missing frontmatter {', '.join(missing)}")
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
    for path in sorted(skills.rglob("*")):
        if path.is_file() and "docs/knowledge-base" in path.read_text(errors="replace"):
            errors.append(f"{path.relative_to(root)}: stale docs/knowledge-base reference")
    return errors


def self_test():
    with tempfile.TemporaryDirectory(prefix="openwiki check ") as temporary:
        root = Path(temporary)
        wiki = root / "openwiki"
        wiki.mkdir()
        for name in COMPATIBILITY:
            stub = root / name
            stub.parent.mkdir(parents=True, exist_ok=True)
            stub.write_text(f"[Moved]({relpath(wiki / 'quickstart.md', stub.parent)})\n")
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
        skill = root / ".agents/skills/openwiki/SKILL.md"
        skill.write_text("[Missing](missing.md)\n")
        assert any("SKILL.md:1: broken link" in error for error in check(root))
        skill.write_text("# Skill\n")
        stub = root / COMPATIBILITY[0]
        saved = stub.read_text()
        stub.write_text("[Missing](missing.md)\n")
        assert any("00-home.md:1: broken link" in error for error in check(root))
        stub.unlink()
        assert any("missing compatibility page" in error for error in check(root))
        stub.write_text(saved)
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
        (root / ".agents/skills/openwiki/SKILL.md").write_text("docs/knowledge-base/00-home.md")
        assert any("stale docs/knowledge-base" in error for error in check(root))


if __name__ == "__main__":
    if sys.argv[1:] not in ([], ["--self-test"]):
        sys.exit("usage: openwiki-check.py [--self-test]")
    self_test()
    failures = [] if sys.argv[1:] else check(Path(__file__).resolve().parents[2])
    if failures:
        sys.exit("\n".join(failures))
    print("OpenWiki links, navigation, frontmatter, and agent entrypoints passed")
