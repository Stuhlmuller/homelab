# Documentation Validation

Run from the repository root. No cluster credentials or live mutation are required.

1. Search all tracked authored Markdown, including hidden local skill paths, for enrollment instructions outside the current documentation model and irrelevant dedicated guide links. Review contextual matches rather than deleting unrelated commit or webhook signatures.
2. Check every removed guide and heading for inbound references. Inspect mixed-purpose documents for coherent grammar and useful authentication, policy and reachability guidance.
3. Run the existing authored wiki gate:

```sh
python3 -I scripts/ci/openwiki-check.py
```

Expected: wiki links, navigation, frontmatter and agent entrypoints pass. Use the project Nix shell if dependencies are missing.

4. Run the existing Markdown lint command on affected remaining documents and `git diff --check`. Preserve complete failure output and distinguish pre-existing findings from regressions.
5. Inspect `git diff HEAD --name-only`, `git ls-files --others --exclude-standard` and the complete `git diff HEAD`. Expected: documentation and feature tracking only, no generated wiki state, credential, executable or runtime configuration changes.
6. Hand the verified diff to the existing delivery owner for normal protected PR publication and checks. A documentation-only source update does not claim live service acceptance.
