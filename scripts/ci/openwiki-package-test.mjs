import assert from "node:assert/strict";
import { execFileSync } from "node:child_process";
import { createHash } from "node:crypto";
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
const { beginRepositoryRun, submitRepositoryPlan } = await import(pathToFileURL(path.join(
  packageRoot, "libexec/openwiki/node_modules/openwiki/dist/generation/repository-run.js",
)));

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

const coverageRepo = await mkdtemp(path.join(tmpdir(), "homelab-openwiki-coverage-"));
const git = (...args) => execFileSync("git", args, { cwd: coverageRepo, encoding: "utf8" }).trim();
const pageHash = (content) => `sha256:${createHash("sha256").update(content).digest("hex")}`;
try {
  git("init", "-q", "-b", "main");
  await mkdir(path.join(coverageRepo, "openwiki/apps"), { recursive: true });
  await mkdir(path.join(coverageRepo, "openwiki/.claims/apps"), { recursive: true });
  const pages = ["nofx", "durable"];
  const content = "---\ntype: app\ntitle: Test\ndescription: Test page.\ntags: [app]\n---\n\n# Test\n\nVerified content.\n";
  const evidence = "Verified content.\n";
  await writeFile(path.join(coverageRepo, "README.md"), evidence);
  const baselineClaims = {};
  for (const name of pages) {
    await writeFile(path.join(coverageRepo, `openwiki/apps/${name}.md`), content);
    baselineClaims[name] = `${JSON.stringify({
        schemaVersion: 1,
        pageVersion: pageHash(content),
        claims: [{
          id: `claim_${name}`,
          statement: "Verified content.",
          evidence: [{ resource: "repo://README.md", version: `repo-file-v1:${pageHash(evidence)}` }],
        }],
        verification: { by: "test", at: "2026-10-25T00:00:00Z" },
      }, null, 2)}\n`;
    await writeFile(path.join(coverageRepo, `openwiki/.claims/apps/${name}.json`), baselineClaims[name]);
  }
  git("add", ".");
  git("-c", "user.name=Test", "-c", "user.email=test@example.invalid", "commit", "-qm", "verified baseline");
  const baseline = git("rev-parse", "HEAD");
  const manifest = { schemaVersion: 1, pages: {} };
  for (const name of pages) {
    manifest.pages[`/openwiki/apps/${name}.md`] = {
      gitHead: baseline,
      sourceFingerprint: `sha256:${"a".repeat(64)}`,
      pageVersion: pageHash(content),
      completedBy: "test",
    };
  }
  await writeFile(path.join(coverageRepo, "openwiki/.page-manifest.json"),
    `${JSON.stringify(manifest, null, 2)}\n`);
  git("add", ".");
  git("-c", "user.name=Test", "-c", "user.email=test@example.invalid", "commit", "-qm", "manifest");
  const changedMarkdown = `${content}Unverified prose.\n`;
  await writeFile(path.join(coverageRepo, "openwiki/apps/nofx.md"), changedMarkdown);
  git("add", ".");
  git("-c", "user.name=Test", "-c", "user.email=test@example.invalid", "commit", "-qm", "wiki prose drift");

  const started = await beginRepositoryRun({
    root: coverageRepo, mode: "update", force: true,
    actor: { producerActor: "test", metadataModel: "test" },
  });
  assert.equal(started.view.status, "active");
  assert.deepEqual(started.run.state.requiredRewritePages, ["/openwiki/apps/nofx.md"]);
  await submitRepositoryPlan(started.run, { pages: [], deletePages: [] });
  assert.ok(started.run.state.plan.pages.some(({ path: page }) => page === "/openwiki/apps/nofx.md"));
  assert.equal(await readFile(path.join(coverageRepo, "openwiki/apps/nofx.md"), "utf8"), changedMarkdown);
  assert.equal(await readFile(path.join(coverageRepo, "openwiki/.claims/apps/nofx.json"), "utf8"), baselineClaims.nofx);
  const persisted = JSON.parse(await readFile(path.join(coverageRepo, "openwiki/.claims/apps/nofx.json")));
  assert.equal(persisted.pageVersion, pageHash(content));
  const advanced = JSON.parse(await readFile(path.join(coverageRepo, "openwiki/.page-manifest.json")));
  assert.equal(advanced.pages["/openwiki/apps/nofx.md"].pageVersion, pageHash(content));
  assert.equal(advanced.pages["/openwiki/apps/nofx.md"].gitHead, baseline);
  assert.equal(advanced.pages["/openwiki/apps/durable.md"].gitHead, git("rev-parse", "HEAD"));
} finally {
  await rm(coverageRepo, { recursive: true, force: true });
}
