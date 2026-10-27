import assert from "node:assert/strict";
import { createHash, randomUUID } from "node:crypto";
import { execFileSync } from "node:child_process";
import { access, mkdir, mkdtemp, readFile, rm, writeFile } from "node:fs/promises";
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

// A missing historical Git object must never advance a verified page baseline.
// This invokes the installed package through its host API, not patch internals.
const historyRepo = await mkdtemp(path.join(tmpdir(), "homelab-openwiki-history-"));
try {
  const page = "/openwiki/architecture/fixture.md";
  const pageText = [
    "---",
    "type: architecture",
    'title: "Fixture"',
    'description: "Historical coverage regression fixture."',
    'tags: ["fixture"]',
    "sources: []",
    'generated: { by: "codex", at: "2026-10-27T00:00:00.000Z" }',
    "verified:",
    "  - by: openwiki/0.7.0",
    "    at: 2026-10-27T00:00:00.000Z",
    "---",
    "",
    "# Fixture",
    "",
  ].join("\n");
  const pageVersion = `sha256:${createHash("sha256").update(pageText).digest("hex")}`;
  const missingGitHead = "f".repeat(40);
  const manifestPath = path.join(historyRepo, "openwiki/.page-manifest.json");
  await mkdir(path.join(historyRepo, "openwiki/architecture"), { recursive: true });
  await mkdir(path.join(historyRepo, "openwiki/.claims/architecture"), { recursive: true });
  await writeFile(path.join(historyRepo, "AGENTS.md"), "# Fixture\n");
  await writeFile(path.join(historyRepo, page.slice(1)), pageText);
  await writeFile(
    path.join(historyRepo, "openwiki/.claims/architecture/fixture.json"),
    JSON.stringify({
      schemaVersion: 1,
      pageVersion,
      claims: [],
      verification: { by: "openwiki/0.7.0", at: "2026-10-27T00:00:00.000Z" },
    }),
  );
  await writeFile(
    manifestPath,
    JSON.stringify({
      schemaVersion: 1,
      pages: {
        [page]: {
          pageVersion,
          completedBy: "codex",
          completedRunId: randomUUID(),
          gitHead: missingGitHead,
          sourceFingerprint: `sha256:${"0".repeat(64)}`,
        },
      },
    }),
  );
  execFileSync("git", ["init", "-q"], { cwd: historyRepo });
  execFileSync("git", ["add", "."], { cwd: historyRepo });
  execFileSync("git", [
    "-c", "user.name=Fixture",
    "-c", "user.email=fixture@example.test",
    "-c", "commit.gpgsign=false",
    "commit", "-qm", "fixture: initial wiki state",
  ], { cwd: historyRepo });

  const sessionModulePath = path.join(
    packageRoot,
    "libexec/openwiki/node_modules/openwiki/dist/integrations/core/session-manager.js",
  );
  const { HostSessionManager } = await import(pathToFileURL(sessionModulePath));
  const session = HostSessionManager.create({ host: "codex", producerActor: "codex" });
  await assert.rejects(
    session.begin({ root: historyRepo, mode: "update" }),
    (error) => error.code === "invalid_state" &&
      /historical Git diff is unavailable/.test(error.message),
  );
  const manifest = JSON.parse(await readFile(manifestPath, "utf8"));
  assert.equal(manifest.pages[page].gitHead, missingGitHead);
} finally {
  await rm(historyRepo, { recursive: true, force: true });
}
