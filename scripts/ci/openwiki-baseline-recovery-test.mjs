import assert from "node:assert/strict";
import { execFileSync } from "node:child_process";
import { createHash, randomUUID } from "node:crypto";
import { mkdir, mkdtemp, readFile, rm, writeFile } from "node:fs/promises";
import { tmpdir } from "node:os";
import path from "node:path";
import { pathToFileURL } from "node:url";

const packageRoot = process.argv[2];
assert.ok(packageRoot, "pass the built OpenWiki package path");
const { HostSessionManager } = await import(pathToFileURL(path.join(
  packageRoot,
  "libexec/openwiki/node_modules/openwiki/dist/integrations/core/session-manager.js",
)));

const root = await mkdtemp(path.join(tmpdir(), "homelab-openwiki-recovery-"));
const page = "/openwiki/architecture/fixture.md";
const unavailable = "f".repeat(40);
const manifestPath = path.join(root, "openwiki/.page-manifest.json");
const sidecarPath = path.join(root, "openwiki/.claims/architecture/fixture.json");
const commit = [
  "-c", "user.name=Fixture",
  "-c", "user.email=fixture@example.test",
  "-c", "commit.gpgsign=false",
  "commit", "-qm", "fixture: initial wiki state",
];

try {
  execFileSync("git", ["init", "-q"], { cwd: root });
  await mkdir(path.join(root, "openwiki/architecture"), { recursive: true });
  await mkdir(path.join(root, "openwiki/.claims/architecture"), { recursive: true });
  const readme = "# Repository\n";
  await writeFile(path.join(root, "README.md"), readme);
  await writeFile(path.join(root, "AGENTS.md"), "# Fixture\n");
  const markdown = [
    "---",
    "type: architecture",
    'title: "Fixture"',
    'description: "Native baseline recovery fixture."',
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
    "The repository has a README.",
    "",
  ].join("\n");
  await writeFile(path.join(root, page.slice(1)), markdown);
  const pageVersion = `sha256:${createHash("sha256").update(markdown).digest("hex")}`;
  await writeFile(sidecarPath, JSON.stringify({
    schemaVersion: 1,
    pageVersion,
    claims: [{
      id: "claim_fixture",
      statement: "The repository has a README.",
      evidence: [{
        resource: "repo://README.md",
        version: `repo-file-v1:sha256:${createHash("sha256").update(readme).digest("hex")}`,
      }],
    }],
    verification: { by: "openwiki/0.7.0", at: "2026-10-27T00:00:00.000Z" },
  }));
  await writeFile(manifestPath, JSON.stringify({
    schemaVersion: 1,
    pages: {
      [page]: {
        pageVersion,
        gitHead: unavailable,
        sourceFingerprint: `sha256:${"0".repeat(64)}`,
        completedBy: "old-producer",
        completedRunId: randomUUID(),
      },
    },
  }));
  execFileSync("git", ["add", "."], { cwd: root });
  execFileSync("git", commit, { cwd: root });
  const targetHead = execFileSync("git", ["rev-parse", "HEAD"], {
    cwd: root, encoding: "utf8",
  }).trim();

  const session = HostSessionManager.create({ host: "codex", producerActor: "codex" });
  await assert.rejects(
    session.begin({ root, mode: "update" }),
    (error) => error.code === "invalid_state" && /Git changed-path query is unavailable/.test(error.message),
  );
  await assert.rejects(
    session.begin({
      root,
      mode: "update",
      recoverPageBaselines: [{ page, gitHead: "e".repeat(40) }],
    }),
    (error) => error.code === "invalid_state" && /does not match the manifest/.test(error.message),
  );
  assert.equal(JSON.parse(await readFile(manifestPath, "utf8")).pages[page].gitHead, unavailable);

  const begun = await session.begin({
    root,
    mode: "update",
    recoverPageBaselines: [{ page, gitHead: unavailable }],
  });
  assert.equal(begun.status, "active");
  assert.deepEqual(begun.requiredBaselineRecoveryPages, [page]);
  assert.deepEqual(begun.pageUpdateWindows, [{ pages: [page], changedPaths: [], fullReview: true }]);
  await assert.rejects(
    session.submitPlan({ runId: begun.runId, pages: [], deletePages: [page] }),
    (error) => error.code === "invalid_input" && /cannot be deleted/.test(error.message),
  );
  const accepted = await session.submitPlan({ runId: begun.runId, pages: [] });
  assert.equal(accepted.totalPages, 1);
  const next = await session.nextPage({ runId: begun.runId });
  assert.equal(next.status, "pending");
  assert.equal(next.job.path, page);
  await assert.rejects(session.finish({ runId: begun.runId }), /cannot finish with pending or skipped/);
  await assert.rejects(
    session.submitPage({ runId: begun.runId, jobId: next.job.id, claims: [] }),
    /requires openwiki_inspect_page_claims/,
  );
  const inspected = await session.inspectPageClaims({ runId: begun.runId, jobId: next.job.id });
  assert.deepEqual(inspected.claims.map(({ id }) => id), ["claim_fixture"]);
  await assert.rejects(
    session.submitPage({ runId: begun.runId, jobId: next.job.id, claims: [] }),
    /explicit decision for every existing Claim ID/,
  );
  await session.submitPage({
    runId: begun.runId,
    jobId: next.job.id,
    confirmedClaimIds: ["claim_fixture"],
  });
  const secondHost = HostSessionManager.create({ host: "codex", producerActor: "second-host" });
  const resumed = await secondHost.begin({ root, mode: "update" });
  assert.equal(resumed.status, "active");
  assert.equal(resumed.resumed, true);
  assert.equal(resumed.runId, begun.runId);
  await writeFile(path.join(root, "README.md"), "# Drifted repository\n");
  await assert.rejects(secondHost.finish({ runId: resumed.runId }), /source changed/);
  await writeFile(path.join(root, "README.md"), readme);
  const completed = await secondHost.finish({ runId: resumed.runId });
  assert.equal(completed.status, "complete");
  const manifest = JSON.parse(await readFile(manifestPath, "utf8"));
  assert.equal(manifest.pages[page].gitHead, targetHead);
  assert.equal(manifest.pages[page].completedRunId, begun.runId);
  assert.equal(manifest.pages[page].completedBy, "codex");
  const sidecar = JSON.parse(await readFile(sidecarPath, "utf8"));
  const currentPage = await readFile(path.join(root, page.slice(1)));
  assert.equal(sidecar.pageVersion, `sha256:${createHash("sha256").update(currentPage).digest("hex")}`);

  // Real stale-page shape: committed Markdown has changed, while both the
  // sidecar and manifest still name the older page bytes and unavailable SHA.
  execFileSync("git", ["add", "."], { cwd: root });
  execFileSync("git", commit, { cwd: root });
  const staleBaseline = "e".repeat(40);
  const oldVersion = sidecar.pageVersion;
  manifest.pages[page].gitHead = staleBaseline;
  await writeFile(manifestPath, JSON.stringify(manifest));
  await writeFile(path.join(root, page.slice(1)), `${currentPage.toString()}\nAdditional fixture note.\n`);
  execFileSync("git", ["add", "."], { cwd: root });
  execFileSync("git", commit, { cwd: root });
  assert.equal(JSON.parse(await readFile(sidecarPath, "utf8")).pageVersion, oldVersion);
  assert.equal(JSON.parse(await readFile(manifestPath, "utf8")).pages[page].pageVersion, oldVersion);
  assert.notEqual(`sha256:${createHash("sha256").update(await readFile(path.join(root, page.slice(1)))).digest("hex")}`, oldVersion);

  const mismatchSession = HostSessionManager.create({ host: "codex", producerActor: "codex" });
  const mismatch = await mismatchSession.begin({
    root,
    mode: "update",
    recoverPageBaselines: [{ page, gitHead: staleBaseline }],
  });
  assert.equal(mismatch.status, "active");
  assert.deepEqual(mismatch.requiredBaselineRecoveryPages, [page]);
  assert.equal((await mismatchSession.submitPlan({ runId: mismatch.runId, pages: [] })).totalPages, 1);
  const mismatchJob = await mismatchSession.nextPage({ runId: mismatch.runId });
  assert.equal(mismatchJob.status, "pending");
  assert.deepEqual(
    (await mismatchSession.inspectPageClaims({ runId: mismatch.runId, jobId: mismatchJob.job.id }))
      .claims.map(({ id }) => id),
    ["claim_fixture"],
  );
  await rm(path.join(root, "README.md"));
  await assert.rejects(
    mismatchSession.submitPage({
      runId: mismatch.runId,
      jobId: mismatchJob.job.id,
      confirmedClaimIds: ["claim_fixture"],
    }),
    /evidence|resolv/i,
  );
  await writeFile(path.join(root, "README.md"), readme);
  await mismatchSession.inspectPageClaims({ runId: mismatch.runId, jobId: mismatchJob.job.id });
  await mismatchSession.submitPage({
    runId: mismatch.runId,
    jobId: mismatchJob.job.id,
    confirmedClaimIds: ["claim_fixture"],
  });
  assert.equal((await mismatchSession.finish({ runId: mismatch.runId })).status, "complete");
  const repairedSidecar = JSON.parse(await readFile(sidecarPath, "utf8"));
  const repairedPage = await readFile(path.join(root, page.slice(1)));
  assert.equal(repairedSidecar.pageVersion, `sha256:${createHash("sha256").update(repairedPage).digest("hex")}`);
  assert.notEqual(repairedSidecar.pageVersion, oldVersion);
  assert.equal(JSON.parse(await readFile(manifestPath, "utf8")).pages[page].completedRunId, mismatch.runId);
} finally {
  await rm(root, { recursive: true, force: true });
}
