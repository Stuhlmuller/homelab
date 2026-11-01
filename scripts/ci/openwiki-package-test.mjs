import assert from "node:assert/strict";
import { createHash, randomUUID } from "node:crypto";
import { execFileSync } from "node:child_process";
import { existsSync } from "node:fs";
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

// Neither a missing baseline nor a later Git query failure may advance page
// coverage. Exercise the installed package through its host API.
const sessionModulePath = path.join(
  packageRoot,
  "libexec/openwiki/node_modules/openwiki/dist/integrations/core/session-manager.js",
);
const { HostSessionManager } = await import(pathToFileURL(sessionModulePath));
const realGit = process.env.PATH.split(path.delimiter)
  .map((dir) => path.join(dir, "git"))
  .find(existsSync);
assert.ok(realGit, "Git must be available for the package fixture");

async function createHistoryRepo(missingBaseline) {
  const historyRepo = await mkdtemp(path.join(tmpdir(), "homelab-openwiki-history-"));
  execFileSync("git", ["init", "-q"], { cwd: historyRepo });
  await writeFile(path.join(historyRepo, "AGENTS.md"), "# Fixture\n");
  execFileSync("git", ["add", "."], { cwd: historyRepo });
  const commit = [
    "-c", "user.name=Fixture",
    "-c", "user.email=fixture@example.test",
    "-c", "commit.gpgsign=false",
    "commit", "-qm", "fixture: initial wiki state",
  ];
  execFileSync("git", commit, { cwd: historyRepo });
  const baseline = missingBaseline
    ? "f".repeat(40)
    : execFileSync("git", ["rev-parse", "HEAD"], { cwd: historyRepo, encoding: "utf8" }).trim();
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
  const manifestPath = path.join(historyRepo, "openwiki/.page-manifest.json");
  await mkdir(path.join(historyRepo, "openwiki/architecture"), { recursive: true });
  await mkdir(path.join(historyRepo, "openwiki/.claims/architecture"), { recursive: true });
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
          gitHead: baseline,
          sourceFingerprint: `sha256:${"0".repeat(64)}`,
        },
      },
    }),
  );
  execFileSync("git", ["add", "."], { cwd: historyRepo });
  execFileSync("git", commit, { cwd: historyRepo });
  return { historyRepo, manifestPath, page, baseline };
}

async function assertCoverageBlocked(fixture) {
  const session = HostSessionManager.create({ host: "codex", producerActor: "codex" });
  await assert.rejects(
    session.begin({ root: fixture.historyRepo, mode: "update" }),
    (error) => error.code === "invalid_state" &&
      /Git changed-path query is unavailable/.test(error.message),
  );
  const manifest = JSON.parse(await readFile(fixture.manifestPath, "utf8"));
  assert.equal(manifest.pages[fixture.page].gitHead, fixture.baseline);
}

const missingHistory = await createHistoryRepo(true);
try {
  await assertCoverageBlocked(missingHistory);
} finally {
  await rm(missingHistory.historyRepo, { recursive: true, force: true });
}

const failedSecondQuery = await createHistoryRepo(false);
const wrapperDir = await mkdtemp(path.join(tmpdir(), "homelab-openwiki-git-"));
const markerPath = path.join(wrapperDir, "second-query-blocked");
const wrapperPath = path.join(wrapperDir, "git");
const originalPath = process.env.PATH;
try {
  // Linux Nix sandboxes do not provide /usr/bin/env.
  await writeFile(wrapperPath, [
    `#!${process.execPath}`,
    'const { spawnSync } = require("node:child_process");',
    'const { writeFileSync } = require("node:fs");',
    "const args = process.argv.slice(2);",
    'if (args.join("\\0") === ["--no-pager", "diff", "--name-only", "HEAD"].join("\\0")) {',
    `  writeFileSync(${JSON.stringify(markerPath)}, "blocked");`,
    "  process.exit(42);",
    "}",
    `const result = spawnSync(${JSON.stringify(realGit)}, args, { stdio: "inherit" });`,
    "process.exit(result.status ?? 1);",
    "",
  ].join("\n"), { mode: 0o755 });
  process.env.PATH = `${wrapperDir}${path.delimiter}${originalPath}`;
  await assertCoverageBlocked(failedSecondQuery);
  assert.equal(await readFile(markerPath, "utf8"), "blocked");
} finally {
  process.env.PATH = originalPath;
  await rm(wrapperDir, { recursive: true, force: true });
  await rm(failedSecondQuery.historyRepo, { recursive: true, force: true });
}
