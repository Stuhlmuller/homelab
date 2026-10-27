import assert from "node:assert/strict";
import { access, mkdtemp, readFile, rm, writeFile } from "node:fs/promises";
import { tmpdir } from "node:os";
import path from "node:path";
import { pathToFileURL } from "node:url";

const packageRoot = process.argv[2];
assert.ok(packageRoot, "pass the built OpenWiki package path");
const modulePath = path.join(
  packageRoot,
  "libexec/openwiki/node_modules/openwiki/dist/ingestion/code-mode.js",
);
const { ensureCodeModeRepoSetup } = await import(pathToFileURL(modulePath));

const repo = await mkdtemp(path.join(tmpdir(), "homelab-openwiki-"));
try {
  const agentsPath = path.join(repo, "AGENTS.md");
  const correctBlock = [
    "# Homelab",
    "",
    "<!-- OPENWIKI:START -->",
    "No scheduled wiki workflow is installed. Update affected pages in the same PR.",
    "<!-- OPENWIKI:END -->",
    "",
  ].join("\n");
  await writeFile(agentsPath, correctBlock);

  await ensureCodeModeRepoSetup(repo, { createWorkflow: false });
  assert.equal(await readFile(agentsPath, "utf8"), correctBlock);
  await assert.rejects(
    access(path.join(repo, ".github/workflows/openwiki-update.yml")),
    { code: "ENOENT" },
  );

  await ensureCodeModeRepoSetup(repo, { createWorkflow: true });
  assert.match(await readFile(agentsPath, "utf8"), /scheduled OpenWiki GitHub Actions workflow/);
  await access(path.join(repo, ".github/workflows/openwiki-update.yml"));
} finally {
  await rm(repo, { recursive: true, force: true });
}
