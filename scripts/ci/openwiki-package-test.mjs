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

const correctBlock = [
    "# Homelab",
    "",
    "<!-- OPENWIKI:START -->",
    "No scheduled wiki workflow is installed. Update affected pages in the same PR.",
    "<!-- OPENWIKI:END -->",
    "",
].join("\n");
const repo = await mkdtemp(path.join(tmpdir(), "homelab-openwiki-"));
try {
  const agentsPath = path.join(repo, "AGENTS.md");
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
const {
  createRepositorySourceSnapshot,
  fingerprintRepositoryVisibleSourcePaths,
  getRepositoryChangedPaths,
  getRepositoryCoverageChangedPaths,
  getUpdateNoopStatus,
} = await import(pathToFileURL(path.join(
  packageRoot,
  "libexec/openwiki/node_modules/openwiki/dist/agent/utils.js",
)));
const { recordRepositoryPageCompletion } = await import(pathToFileURL(path.join(
  packageRoot,
  "libexec/openwiki/node_modules/openwiki/dist/generation/page-manifest.js",
)));
const { OpenWikiIgnore } = await import(pathToFileURL(path.join(
  packageRoot,
  "libexec/openwiki/node_modules/openwiki/dist/agent/openwiki-ignore.js",
)));
const realGit = process.env.PATH.split(path.delimiter)
  .map((dir) => path.join(dir, "git"))
  .find(existsSync);
assert.ok(realGit, "Git must be available for the package fixture");

// Fresh init installs repository instructions first. It must stop before any
// wiki state until an operator commits that generated source, then retry.
const initRepo = await mkdtemp(path.join(tmpdir(), "homelab-openwiki-init-"));
try {
  execFileSync("git", ["init", "-q"], { cwd: initRepo });
  await writeFile(path.join(initRepo, "README.md"), "# Init fixture\n");
  const commit = [
    "-c", "user.name=Fixture", "-c", "user.email=fixture@example.test",
    "-c", "commit.gpgsign=false", "commit", "-qm", "fixture: init setup",
  ];
  execFileSync("git", ["add", "."], { cwd: initRepo });
  execFileSync("git", commit, { cwd: initRepo });
  const session = HostSessionManager.create({ host: "codex", producerActor: "codex" });
  await assert.rejects(session.begin({ root: initRepo, mode: "init" }),
    (error) => error.code === "invalid_state" && /commit and retry/.test(error.message));
  await access(path.join(initRepo, "AGENTS.md"));
  await access(path.join(initRepo, ".github/workflows/openwiki-update.yml"));
  for (const state of [".run.json", ".page-manifest.json", ".last-update.json"]) {
    await assert.rejects(access(path.join(initRepo, "openwiki", state)), { code: "ENOENT" });
  }
  execFileSync("git", ["add", "."], { cwd: initRepo });
  execFileSync("git", commit, { cwd: initRepo });
  assert.equal((await session.begin({ root: initRepo, mode: "init" })).status, "active");
} finally {
  await rm(initRepo, { recursive: true, force: true });
}

async function createHistoryRepo(missingBaseline, visibleSource = false, protoSource = false) {
  const historyRepo = await mkdtemp(path.join(tmpdir(), "homelab-openwiki-history-"));
  execFileSync("git", ["init", "-q"], { cwd: historyRepo });
  await writeFile(path.join(historyRepo, "AGENTS.md"), correctBlock);
  if (protoSource) {
    await writeFile(path.join(historyRepo, "__proto__"), "A valid source path\n");
  }
  execFileSync("git", ["add", "."], { cwd: historyRepo });
  const commit = [
    "-c", "user.name=Fixture",
    "-c", "user.email=fixture@example.test",
    "-c", "commit.gpgsign=false",
    "commit", "-qm", "fixture: initial wiki state",
  ];
  execFileSync("git", commit, { cwd: historyRepo });
  const sourceSnapshot = await createRepositorySourceSnapshot(historyRepo, new OpenWikiIgnore([]));
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
          ...(visibleSource
            ? { visibleSourceFingerprint: sourceSnapshot.visibleSourceFingerprint }
            : {}),
        },
      },
      ...(visibleSource
        ? { visibleSources: {
          [sourceSnapshot.visibleSourceFingerprint]: sourceSnapshot.visibleSourcePaths,
        } }
        : {}),
    }),
  );
  execFileSync("git", ["add", "."], { cwd: historyRepo });
  execFileSync("git", commit, { cwd: historyRepo });
  return { historyRepo, manifestPath, page, baseline, sourceSnapshot };
}

async function assertCoverageBlocked(fixture) {
  const session = HostSessionManager.create({ host: "codex", producerActor: "codex" });
  await assert.rejects(
    session.begin({ root: fixture.historyRepo, mode: "update" }),
    (error) => error.code === "invalid_state" &&
      /Git changed-path query is unavailable|historical Git source is unavailable|visible-source or Git changed-path query is unavailable/.test(error.message),
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

// Squash can remove the old commit without changing the model-visible source.
// Its native source map proves reuse even when the old SHA is unavailable.
const sameSource = await createHistoryRepo(true, true, true);
try {
  assert.equal(Object.hasOwn(sameSource.sourceSnapshot.visibleSourcePaths, "__proto__"), true);
  await writeFile(path.join(sameSource.historyRepo, "openwiki/.last-update.json"), JSON.stringify({
    updatedAt: "2026-10-27T00:00:00.000Z",
    command: "update",
    gitHead: sameSource.baseline,
    visibleSourceFingerprint: sameSource.sourceSnapshot.visibleSourceFingerprint,
    model: "host-agent/codex",
    status: "complete",
    language: "en",
  }));
  execFileSync("git", ["add", "."], { cwd: sameSource.historyRepo });
  execFileSync("git", [
    "-c", "user.name=Fixture", "-c", "user.email=fixture@example.test",
    "-c", "commit.gpgsign=false", "commit", "-qm", "fixture: squash-equivalent source",
  ], { cwd: sameSource.historyRepo });
  const currentSource = await createRepositorySourceSnapshot(
    sameSource.historyRepo, new OpenWikiIgnore([]),
  );
  assert.notEqual(currentSource.gitHead, sameSource.sourceSnapshot.gitHead);
  assert.equal(currentSource.visibleSourceFingerprint, sameSource.sourceSnapshot.visibleSourceFingerprint);
  assert.notEqual(currentSource.fingerprint, sameSource.sourceSnapshot.fingerprint);
  const session = HostSessionManager.create({ host: "codex", producerActor: "codex" });
  const begun = await session.begin({ root: sameSource.historyRepo, mode: "update" });
  assert.equal(begun.status, "noop");
  const manifest = JSON.parse(await readFile(sameSource.manifestPath, "utf8"));
  assert.equal(manifest.pages[sameSource.page].gitHead, currentSource.gitHead);
  assert.equal(manifest.pages[sameSource.page].visibleSourceFingerprint, currentSource.visibleSourceFingerprint);
  assert.equal(Object.hasOwn(manifest.visibleSources[currentSource.visibleSourceFingerprint], "__proto__"), true);
  const metadataPath = path.join(sameSource.historyRepo, "openwiki/.last-update.json");
  const metadata = JSON.parse(await readFile(metadataPath, "utf8"));
  assert.equal(metadata.gitHead, currentSource.gitHead);
  assert.equal(metadata.visibleSourceFingerprint, currentSource.visibleSourceFingerprint);
  await writeFile(metadataPath, JSON.stringify({ ...metadata, status: "interrupted" }));
  assert.equal((await getUpdateNoopStatus(sameSource.historyRepo)).shouldSkip, false);
  await writeFile(metadataPath, JSON.stringify({ ...metadata, status: "complete" }));
  assert.equal((await getUpdateNoopStatus(sameSource.historyRepo, new OpenWikiIgnore([]), "fr")).shouldSkip, false);
  assert.equal((await session.begin({ root: sameSource.historyRepo, mode: "update", force: true })).status, "active");
} finally {
  await rm(sameSource.historyRepo, { recursive: true, force: true });
}

const changedSource = await createHistoryRepo(true, true);
try {
  await writeFile(path.join(changedSource.historyRepo, "AGENTS.md"),
    correctBlock.replace("# Homelab", "# Changed fixture"));
  execFileSync("git", ["add", "AGENTS.md"], { cwd: changedSource.historyRepo });
  execFileSync("git", [
    "-c", "user.name=Fixture", "-c", "user.email=fixture@example.test",
    "-c", "commit.gpgsign=false", "commit", "-qm", "fixture: source changed",
  ], { cwd: changedSource.historyRepo });
  const changedSnapshot = await createRepositorySourceSnapshot(
    changedSource.historyRepo, new OpenWikiIgnore([]),
  );
  await writeFile(path.join(changedSource.historyRepo, "openwiki/.last-update.json"), JSON.stringify({
    updatedAt: "2026-10-27T00:00:00.000Z",
    command: "update",
    gitHead: changedSnapshot.gitHead,
    visibleSourceFingerprint: changedSnapshot.visibleSourceFingerprint,
    model: "host-agent/codex",
    status: "complete",
    language: "en",
  }));
  execFileSync("git", ["add", "."], { cwd: changedSource.historyRepo });
  execFileSync("git", [
    "-c", "user.name=Fixture", "-c", "user.email=fixture@example.test",
    "-c", "commit.gpgsign=false", "commit", "-qm", "fixture: current run metadata",
  ], { cwd: changedSource.historyRepo });
  const session = HostSessionManager.create({ host: "codex", producerActor: "codex" });
  const begun = await session.begin({ root: changedSource.historyRepo, mode: "update" });
  assert.equal(begun.status, "active");
  assert.deepEqual(begun.pageUpdateWindows[0].changedPaths, ["AGENTS.md"]);
  assert.equal(JSON.parse(await readFile(changedSource.manifestPath, "utf8"))
    .pages[changedSource.page].gitHead, changedSource.baseline);
  await writeFile(path.join(changedSource.historyRepo, "AGENTS.md"),
    correctBlock.replace("# Homelab", "# Dirty fixture"));
  assert.equal((await createRepositorySourceSnapshot(
    changedSource.historyRepo, new OpenWikiIgnore([]),
  )).visibleSourceFingerprint, undefined);
} finally {
  await rm(changedSource.historyRepo, { recursive: true, force: true });
}

// A public page manifest must not publish per-path hashes for local untracked
// content. Native begin and completion both require committed visible source.
const untracked = await createHistoryRepo(false, true);
try {
  const root = untracked.historyRepo;
  await writeFile(path.join(root, "X.md"), "# Untracked source\n");
  const source = await createRepositorySourceSnapshot(root, new OpenWikiIgnore([]));
  assert.equal(source.visibleSourceFingerprint, undefined);
  const session = HostSessionManager.create({ host: "codex", producerActor: "codex" });
  await assert.rejects(session.begin({ root, mode: "update" }),
    (error) => error.code === "invalid_state" && /commit and retry/.test(error.message));
  await assert.rejects(recordRepositoryPageCompletion(root, untracked.page, {
    gitHead: source.gitHead,
    sourceFingerprint: source.fingerprint,
  }, "codex", randomUUID()),
  (error) => error.code === "invalid_state" && /committed, clean model-visible source/.test(error.message));
  assert.equal(Object.keys(JSON.parse(await readFile(untracked.manifestPath, "utf8")).visibleSources).length, 1);
} finally {
  await rm(untracked.historyRepo, { recursive: true, force: true });
}

// Git's assume-unchanged bit can hide a dirty tracked file from porcelain.
// Comparing the verified bytes with HEAD still prevents public map emission.
const hiddenEdit = await createHistoryRepo(false, true);
try {
  const root = hiddenEdit.historyRepo;
  execFileSync("git", ["update-index", "--assume-unchanged", "AGENTS.md"], { cwd: root });
  await writeFile(path.join(root, "AGENTS.md"),
    correctBlock.replace("# Homelab", "# Hidden local edit"));
  assert.equal((await createRepositorySourceSnapshot(root, new OpenWikiIgnore([]))).visibleSourceFingerprint, undefined);
  const session = HostSessionManager.create({ host: "codex", producerActor: "codex" });
  await assert.rejects(session.begin({ root, mode: "update" }),
    (error) => error.code === "invalid_state" && /commit and retry/.test(error.message));
} finally {
  await rm(hiddenEdit.historyRepo, { recursive: true, force: true });
}

const sparseMissing = await createHistoryRepo(false, true);
try {
  const root = sparseMissing.historyRepo;
  execFileSync("git", ["update-index", "--skip-worktree", "AGENTS.md"], { cwd: root });
  await rm(path.join(root, "AGENTS.md"));
  assert.equal((await createRepositorySourceSnapshot(root, new OpenWikiIgnore([]))).visibleSourceFingerprint, undefined);
} finally {
  await rm(sparseMissing.historyRepo, { recursive: true, force: true });
}

// Feature A's source commit is pruned after its wiki is squash-applied onto
// main with unrelated source B. The two pages retain distinct source maps:
// only the source paths changed after each page's own checkpoint need review.
const divergent = await createHistoryRepo(false, true);
try {
  const root = divergent.historyRepo;
  const commit = [
    "-c", "user.name=Fixture", "-c", "user.email=fixture@example.test",
    "-c", "commit.gpgsign=false", "commit", "-qm", "fixture: source history",
  ];
  const baseBranch = execFileSync("git", ["branch", "--show-current"], {
    cwd: root, encoding: "utf8",
  }).trim();
  const oldPage = divergent.page;
  const secondPage = "/openwiki/architecture/second.md";
  await writeFile(path.join(root, secondPage.slice(1)),
    await readFile(path.join(root, oldPage.slice(1))));
  await writeFile(path.join(root, "openwiki/.claims/architecture/second.json"),
    await readFile(path.join(root, "openwiki/.claims/architecture/fixture.json")));
  const initialManifest = JSON.parse(await readFile(divergent.manifestPath, "utf8"));
  initialManifest.pages[secondPage] = { ...initialManifest.pages[oldPage] };
  await writeFile(divergent.manifestPath, JSON.stringify(initialManifest));
  execFileSync("git", ["add", "."], { cwd: root });
  execFileSync("git", commit, { cwd: root });

  execFileSync("git", ["checkout", "-qb", "feature-a"], { cwd: root });
  await writeFile(path.join(root, "AGENTS.md"),
    correctBlock.replace("# Homelab", "# Feature A"));
  execFileSync("git", ["add", "AGENTS.md"], { cwd: root });
  execFileSync("git", commit, { cwd: root });
  const sourceA = await createRepositorySourceSnapshot(root, new OpenWikiIgnore([]));
  await recordRepositoryPageCompletion(root, oldPage, {
    gitHead: sourceA.gitHead,
    sourceFingerprint: sourceA.fingerprint,
    visibleSourceFingerprint: sourceA.visibleSourceFingerprint,
  }, "codex", randomUUID());
  const featureManifest = await readFile(divergent.manifestPath);
  execFileSync("git", ["add", "."], { cwd: root });
  execFileSync("git", commit, { cwd: root });

  execFileSync("git", ["checkout", "-q", baseBranch], { cwd: root });
  await writeFile(path.join(root, "B.md"), "# Unrelated source B\n");
  execFileSync("git", ["add", "B.md"], { cwd: root });
  execFileSync("git", commit, { cwd: root });
  await writeFile(path.join(root, "AGENTS.md"),
    correctBlock.replace("# Homelab", "# Feature A"));
  await writeFile(divergent.manifestPath, featureManifest);
  execFileSync("git", ["add", "."], { cwd: root });
  execFileSync("git", commit, { cwd: root });
  const sourceAB = await createRepositorySourceSnapshot(root, new OpenWikiIgnore([]));
  await writeFile(path.join(root, "openwiki/.last-update.json"), JSON.stringify({
    updatedAt: "2026-10-27T00:00:00.000Z",
    command: "update",
    gitHead: sourceAB.gitHead,
    visibleSourceFingerprint: sourceAB.visibleSourceFingerprint,
    model: "host-agent/codex",
    status: "complete",
    language: "en",
  }));
  execFileSync("git", ["add", "."], { cwd: root });
  execFileSync("git", commit, { cwd: root });
  execFileSync("git", ["branch", "-D", "feature-a"], { cwd: root, stdio: "ignore" });
  execFileSync("git", ["reflog", "expire", "--expire=now", "--expire-unreachable=now", "--all"], { cwd: root });
  execFileSync("git", ["gc", "--prune=now"], { cwd: root });
  assert.throws(() => execFileSync("git", ["cat-file", "-e", `${sourceA.gitHead}^{commit}`], {
    cwd: root, stdio: "ignore",
  }));
  assert.equal((await getUpdateNoopStatus(root)).shouldSkip, true);
  const session = HostSessionManager.create({ host: "codex", producerActor: "codex" });
  const begun = await session.begin({ root, mode: "update" });
  assert.equal(begun.status, "active");
  assert.deepEqual(begun.pageUpdateWindows.find(({ pages }) => pages.includes(oldPage)).changedPaths, ["B.md"]);
  assert.deepEqual(begun.pageUpdateWindows.find(({ pages }) => pages.includes(secondPage)).changedPaths,
    ["AGENTS.md", "B.md"]);
  const afterBegin = JSON.parse(await readFile(divergent.manifestPath, "utf8"));
  assert.equal(afterBegin.pages[oldPage].gitHead, sourceA.gitHead);
  assert.equal(afterBegin.pages[secondPage].visibleSourceFingerprint,
    divergent.sourceSnapshot.visibleSourceFingerprint);
  assert.equal(Object.keys(afterBegin.visibleSources).length, 2);

  await writeFile(path.join(root, "AGENTS.md"),
    correctBlock.replace("# Homelab", "# Feature A, later edit"));
  assert.deepEqual(await getRepositoryCoverageChangedPaths(root, new OpenWikiIgnore([]),
    afterBegin.visibleSources[sourceA.visibleSourceFingerprint], sourceA.visibleSourceFingerprint),
  ["AGENTS.md", "B.md"]);
} finally {
  await rm(divergent.historyRepo, { recursive: true, force: true });
}

const lostMap = await createHistoryRepo(true, true);
try {
  const manifest = JSON.parse(await readFile(lostMap.manifestPath, "utf8"));
  delete manifest.visibleSources[manifest.pages[lostMap.page].visibleSourceFingerprint];
  await writeFile(lostMap.manifestPath, JSON.stringify(manifest));
  const session = HostSessionManager.create({ host: "codex", producerActor: "codex" });
  await assert.rejects(session.begin({ root: lostMap.historyRepo, mode: "update" }),
    (error) => error.code === "invalid_state" && /visible source snapshot is missing or malformed/.test(error.message));
  manifest.visibleSources[lostMap.sourceSnapshot.visibleSourceFingerprint] = {
    ...lostMap.sourceSnapshot.visibleSourcePaths,
    "AGENTS.md": `sha256:${"1".repeat(64)}`,
  };
  await writeFile(lostMap.manifestPath, JSON.stringify(manifest));
  await assert.rejects(session.begin({ root: lostMap.historyRepo, mode: "update" }),
    (error) => error.code === "invalid_state" && /visible source snapshot is malformed/.test(error.message));
} finally {
  await rm(lostMap.historyRepo, { recursive: true, force: true });
}

assert.throws(() => fingerprintRepositoryVisibleSourcePaths({
  "../escape": `sha256:${"0".repeat(64)}`,
}), /malformed/);

const ignoreRepo = await mkdtemp(path.join(tmpdir(), "homelab-openwiki-ignore-"));
try {
  execFileSync("git", ["init", "-q"], { cwd: ignoreRepo });
  await writeFile(path.join(ignoreRepo, ".openwikiignore"), ".openwikiignore\n");
  await writeFile(path.join(ignoreRepo, "other.txt"), "Visible source\n");
  execFileSync("git", ["add", "."], { cwd: ignoreRepo });
  const commit = [
    "-c", "user.name=Fixture", "-c", "user.email=fixture@example.test",
    "-c", "commit.gpgsign=false", "commit", "-qm", "fixture: ignore rules",
  ];
  execFileSync("git", commit, { cwd: ignoreRepo });
  const initialIgnore = await OpenWikiIgnore.load(ignoreRepo);
  const initialSource = await createRepositorySourceSnapshot(ignoreRepo, initialIgnore);
  const baseline = execFileSync("git", ["rev-parse", "HEAD"], {
    cwd: ignoreRepo, encoding: "utf8",
  }).trim();
  await writeFile(path.join(ignoreRepo, ".openwikiignore"), ".openwikiignore\nother.txt\n");
  execFileSync("git", ["add", "."], { cwd: ignoreRepo });
  execFileSync("git", commit, { cwd: ignoreRepo });
  assert.deepEqual(
    await getRepositoryChangedPaths(ignoreRepo, await OpenWikiIgnore.load(ignoreRepo), baseline, true),
    [".openwikiignore"],
  );
  const tightIgnore = await OpenWikiIgnore.load(ignoreRepo);
  const tightSource = await createRepositorySourceSnapshot(ignoreRepo, tightIgnore);
  assert.deepEqual(await getRepositoryCoverageChangedPaths(ignoreRepo, tightIgnore,
    initialSource.visibleSourcePaths, initialSource.visibleSourceFingerprint),
  [".openwikiignore", "other.txt"]);
  await writeFile(path.join(ignoreRepo, ".openwikiignore"), ".openwikiignore\n");
  execFileSync("git", ["add", "."], { cwd: ignoreRepo });
  execFileSync("git", commit, { cwd: ignoreRepo });
  assert.deepEqual(await getRepositoryCoverageChangedPaths(ignoreRepo, await OpenWikiIgnore.load(ignoreRepo),
    tightSource.visibleSourcePaths, tightSource.visibleSourceFingerprint),
  [".openwikiignore", "other.txt"]);
} finally {
  await rm(ignoreRepo, { recursive: true, force: true });
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
