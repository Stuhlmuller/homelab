#!/usr/bin/env python3
"""Build XERJ text cards from public, Git-tracked hidden source files."""

from pathlib import Path
from re import finditer
from subprocess import check_output


root = Path(__file__).resolve().parents[1]
output = Path.home() / ".xerj-code/local-source"
output.mkdir(mode=0o700, parents=True, exist_ok=True)
output.chmod(0o700)


def write_card(source: Path, target: Path) -> None:
    body = source.read_bytes()
    body.decode("utf-8")
    longest = max((len(match.group()) for match in finditer(rb"`+", body)), default=0)
    fence = b"`" * max(4, longest + 1)
    relative = source.relative_to(root).as_posix().encode()
    target.write_bytes(
        b"# " + relative + b"\n\n" + fence + b"\n" + body
        + (b"\n" if not body.endswith(b"\n") else b"") + fence + b"\n"
    )


expected = set()
for raw in check_output(["git", "ls-files", "-z"], cwd=root).split(b"\0"):
    if not raw:
        continue
    relative = Path(raw.decode())
    source = root / relative
    if not any(part.startswith(".") for part in relative.parts):
        continue
    if source.is_symlink() or not source.is_file():
        continue
    name = "dotfile-" + relative.as_posix().replace("/", "__").replace(".", "_") + ".md"
    assert name not in expected, relative
    expected.add(name)
    write_card(source, output / name)

for stale in output.glob("dotfile-*.md"):
    if stale.name not in expected:
        stale.unlink()

# Release rc.104 indexes this manifest alongside the rest of the visible tree.
(output / "octelium-enterprise-resources.md").unlink(missing_ok=True)
assert {path.name for path in output.glob("dotfile-*.md")} == expected
print(f"XERJ text cards: {len(expected)} tracked hidden files")
