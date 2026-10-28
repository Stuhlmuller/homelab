import assert from "node:assert/strict";
import { execFileSync } from "node:child_process";
import { createHash, randomUUID } from "node:crypto";
import { mkdir, mkdtemp, readFile, rm, writeFile } from "node:fs/promises";
import { tmpdir } from "node:os";
import path from "node:path";
import { pathToFileURL } from "node:url";

const packageRoot = process.argv[2];
assert.ok(packageRoot, "pass the built OpenWiki package path");
const packagePath = path.join(packageRoot, "libexec/openwiki/node_modules/openwiki/dist");
const { HostSessionManager } = await import(pathToFileURL(path.join(
  packagePath, "integrations/core/session-manager.js",
)));
const { createRepositoryPlan } = await import(pathToFileURL(path.join(
  packagePath, "generation/page-jobs.js",
)));
const { SubmitPlanInput } = await import(pathToFileURL(path.join(
  packagePath, "integrations/core/protocol.js",
)));
const { OpenWikiLocalShellBackend } = await import(pathToFileURL(path.join(
  packagePath, "agent/docs-only-backend.js",
)));

const selected = "/openwiki/architecture/selected.md";
const deferred = "/openwiki/architecture/deferred.md";
const proposed = [{ path: selected, title: "Selected", purpose: "Refresh selected page" }];
const issues = [{ page: selected, resources: [] }, { page: deferred, resources: [] }];
assert.equal(createRepositoryPlan("update", { pages: proposed }, issues).pages.length, 2);
const focused = createRepositoryPlan("update", {
  pages: proposed, deferUnplannedClaimIssues: true,
}, issues);
assert.deepEqual(focused.pages.map(({ path: page }) => page), [selected]);
assert.deepEqual(focused.deferredClaimPages, [deferred]);
assert.throws(() => createRepositoryPlan("init", {
  pages: [{ path: "/openwiki/quickstart.md", title: "Start", purpose: "Start" }],
  deferUnplannedClaimIssues: true,
}, []), /Init cannot defer Claim issues/);
assert.equal(SubmitPlanInput.parse({
  runId: randomUUID(), pages: proposed, deferUnplannedClaimIssues: true,
}).deferUnplannedClaimIssues, true);

const root = await mkdtemp(path.join(tmpdir(), "homelab-openwiki-focused-"));
const commit = (message) => {
  execFileSync("git", ["add", "."], { cwd: root });
  execFileSync("git", [
    "-c", "user.name=Fixture", "-c", "user.email=fixture@example.invalid",
    "-c", "commit.gpgsign=false", "commit", "-qm", message,
  ], { cwd: root });
  return execFileSync("git", ["rev-parse", "HEAD"], { cwd: root, encoding: "utf8" }).trim();
};
const hash = (content) => `sha256:${createHash("sha256").update(content).digest("hex")}`;
const markdown = (name) => [
  "---", "type: architecture", `title: "${name}"`,
  `description: "${name} fixture."`, 'tags: ["fixture"]',
  "sources: []", 'generated: { by: "codex", at: "2026-10-27T00:00:00.000Z" }',
  "verified:", "  - by: openwiki/0.7.0", "    at: 2026-10-27T00:00:00.000Z",
  "---", "", `# ${name}`, "", "The repository has a README.", "",
].join("\n");

try {
  execFileSync("git", ["init", "-q"], { cwd: root });
  const originalReadme = "# Repository\n";
  await writeFile(path.join(root, "README.md"), originalReadme);
  await writeFile(path.join(root, "AGENTS.md"), [
    "# Fixture", "", "<!-- OPENWIKI:START -->",
    "Update affected pages in the same PR.", "<!-- OPENWIKI:END -->", "",
  ].join("\n"));
  const sourceHead = commit("fixture: source");
  await mkdir(path.join(root, "openwiki/architecture"), { recursive: true });
  await mkdir(path.join(root, "openwiki/.claims/architecture"), { recursive: true });
  const manifest = { schemaVersion: 1, pages: {} };
  for (const [page, name] of [[selected, "Selected"], [deferred, "Deferred"]]) {
    const body = name === "Deferred"
      ? markdown("Deferred Display")
        .replace("type: architecture\n", "")
        .replace('title: "Deferred Display"\n', "")
        .replace('description: "Deferred Display fixture."\n', "")
      : markdown(name);
    const pageVersion = hash(body);
    await writeFile(path.join(root, page.slice(1)), body);
    await writeFile(path.join(root, "openwiki/.claims/architecture", `${name.toLowerCase()}.json`), JSON.stringify({
      schemaVersion: 1,
      pageVersion,
      claims: [{
        id: `claim_${name.toLowerCase()}`,
        statement: "The repository has a README.",
        evidence: [{ resource: "repo://README.md", version: `repo-file-v1:${hash(originalReadme)}` }],
      }],
      verification: { by: "openwiki/0.7.0", at: "2026-10-27T00:00:00.000Z" },
    }));
    manifest.pages[page] = {
      pageVersion, gitHead: sourceHead, sourceFingerprint: hash(originalReadme),
      completedBy: "fixture", completedRunId: randomUUID(),
    };
  }
  const manifestPath = path.join(root, "openwiki/.page-manifest.json");
  await writeFile(manifestPath, JSON.stringify(manifest));
  commit("fixture: wiki");
  await writeFile(path.join(root, "README.md"), "# Repository\n\nA changed source line.\n");
  commit("fixture: source change");

  const deferredMarkdownPath = path.join(root, deferred.slice(1));
  const deferredSidecarPath = path.join(root, "openwiki/.claims/architecture/deferred.json");
  const deferredBefore = await Promise.all([
    readFile(deferredMarkdownPath), readFile(deferredSidecarPath), readFile(manifestPath),
  ]);
  // Simulate a concurrent edit during preparation's provenance read. The
  // operator must fail without restoring over that user change.
  const originalReadRaw = OpenWikiLocalShellBackend.prototype.readRaw;
  const concurrentEdit = Buffer.concat([deferredBefore[0], Buffer.from("\nConcurrent edit.\n")]);
  let injected = false;
  OpenWikiLocalShellBackend.prototype.readRaw = async function (filePath) {
    const result = await originalReadRaw.call(this, filePath);
    if (!injected && filePath === deferred) {
      await writeFile(deferredMarkdownPath, concurrentEdit);
      injected = true;
    }
    return result;
  };
  try {
    const raced = HostSessionManager.create({ host: "codex", producerActor: "codex" });
    await assert.rejects(raced.begin({ root, mode: "update" }),
      /Claim issue page changed during preparation/);
    assert.equal(injected, true);
    assert.deepEqual(await readFile(deferredMarkdownPath), concurrentEdit);
  } finally {
    OpenWikiLocalShellBackend.prototype.readRaw = originalReadRaw;
  }
  await writeFile(deferredMarkdownPath, deferredBefore[0]);
  const session = HostSessionManager.create({ host: "codex", producerActor: "codex" });
  const begun = await session.begin({ root, mode: "update" });
  assert.equal(begun.status, "active");
  assert.deepEqual(begun.requiredBaselineRecoveryPages, []);
  assert.deepEqual(new Set(begun.claimIssues.map(({ page }) => page)), new Set([selected, deferred]));
  assert.deepEqual(await readFile(deferredMarkdownPath), deferredBefore[0]);
  assert.deepEqual(JSON.parse(await readFile(manifestPath, "utf8")).pages[deferred], manifest.pages[deferred]);
  assert.equal((await session.submitPlan({
    runId: begun.runId, pages: proposed, deferUnplannedClaimIssues: true,
  })).totalPages, 1);

  const resumed = HostSessionManager.create({ host: "codex", producerActor: "codex" });
  const active = await resumed.begin({ root, mode: "update" });
  assert.equal(active.runId, begun.runId);
  const next = await resumed.nextPage({ runId: active.runId });
  assert.equal(next.job.path, selected);
  const inspected = await resumed.inspectPageClaims({ runId: active.runId, jobId: next.job.id });
  assert.deepEqual(inspected.claims.map(({ id }) => id), ["claim_selected"]);
  await resumed.submitPage({
    runId: active.runId, jobId: next.job.id, confirmedClaimIds: ["claim_selected"],
  });
  const editedDeferred = Buffer.concat([deferredBefore[0], Buffer.from("\nUser edit.\n")]);
  await writeFile(deferredMarkdownPath, editedDeferred);
  await assert.rejects(resumed.finish({ runId: active.runId }), /Deferred Claim page|do not match/);
  assert.deepEqual(await readFile(deferredMarkdownPath), editedDeferred);
  await writeFile(deferredMarkdownPath, deferredBefore[0]);
  const editedSidecar = JSON.parse(deferredBefore[1]);
  editedSidecar.claims[0].evidence[0].version = `repo-file-v1:sha256:${"1".repeat(64)}`;
  await writeFile(deferredSidecarPath, JSON.stringify(editedSidecar));
  await assert.rejects(resumed.finish({ runId: active.runId }), /Deferred Claim page/);
  assert.deepEqual(await readFile(deferredSidecarPath), Buffer.from(JSON.stringify(editedSidecar)));
  await writeFile(deferredSidecarPath, deferredBefore[1]);
  const manifestBeforeEdit = await readFile(manifestPath);
  const changedManifest = JSON.parse(manifestBeforeEdit);
  changedManifest.pages[deferred].sourceFingerprint = `sha256:${"2".repeat(64)}`;
  await writeFile(manifestPath, JSON.stringify(changedManifest));
  await assert.rejects(resumed.finish({ runId: active.runId }), /Deferred Claim page/);
  await writeFile(manifestPath, manifestBeforeEdit);
  assert.equal((await resumed.finish({ runId: active.runId })).status, "complete");
  const deferredAfter = await Promise.all([
    readFile(deferredMarkdownPath), readFile(deferredSidecarPath), readFile(manifestPath),
  ]);
  assert.deepEqual(deferredAfter[0], deferredBefore[0]);
  assert.deepEqual(deferredAfter[1], deferredBefore[1]);
  assert.deepEqual(JSON.parse(deferredAfter[2]).pages[deferred], manifest.pages[deferred]);
  const updatedManifest = JSON.parse(deferredAfter[2]);
  assert.equal(updatedManifest.pages[selected].completedRunId, begun.runId);
  assert.match(await readFile(path.join(root, "openwiki/architecture/index.md"), "utf8"),
    /\[deferred\]\(deferred\.md\)/);
  assert.equal(JSON.parse(await readFile(path.join(root, "openwiki/.last-update.json"), "utf8")).status, "interrupted");

  // A wiki-only sidecar change can make a Claim stale while source paths have
  // no net diff from the deferred page's old source baseline. Begin must not
  // fast-forward that unresolved page before a focused plan exists.
  await writeFile(path.join(root, "README.md"), originalReadme);
  commit("fixture: return source bytes");
  const staleSidecar = JSON.parse(await readFile(deferredSidecarPath, "utf8"));
  staleSidecar.claims[0].evidence[0].version = `repo-file-v1:sha256:${"0".repeat(64)}`;
  await writeFile(deferredSidecarPath, JSON.stringify(staleSidecar));
  commit("fixture: stale wiki Claim evidence");
  const oldDeferredEntry = JSON.parse(await readFile(manifestPath, "utf8")).pages[deferred];
  const second = HostSessionManager.create({ host: "codex", producerActor: "codex" });
  const secondBegin = await second.begin({ root, mode: "update" });
  assert.equal(secondBegin.status, "active");
  assert.ok(secondBegin.claimIssues.some(({ page }) => page === deferred));
  assert.deepEqual(JSON.parse(await readFile(manifestPath, "utf8")).pages[deferred], oldDeferredEntry);
} finally {
  await rm(root, { recursive: true, force: true });
}
