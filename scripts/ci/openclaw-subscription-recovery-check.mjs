// Run with node --experimental-vm-modules. Exercise the actual operator entry
// point with isolated provider/runtime boundaries; never contact a live account.
import assert from "node:assert/strict";
import { readFile } from "node:fs/promises";
import vm from "node:vm";

const source = await readFile("scripts/openclaw-recover-subscription.mjs", "utf8");
async function run(options = {}) {
  let now = 1_000_000;
  let blocked = options.blocked ?? true;
  let probes = 0;
  let reloads = 0;
  const output = [];
  const process = { argv: ["node", "-", options.mode ?? "--recover"] };
  const context = vm.createContext({
    process,
    Date: { now: () => now },
    console: { log: (s) => output.push(s), error: (s) => output.push(s) },
  });
  const loadStore = () => ({
    blocked,
    profiles: options.ambiguous ? {} : { fixture: { provider: "openai", type: "oauth" } },
    usageStats: { fixture: {
      blockedSource: options.source ?? "wham", blockedReason: "subscription_limit",
    } },
  });
  const modules = {
    "node:fs/promises": { readFile: async () => JSON.stringify({ version: options.version ?? "2026.9.2" }) },
    "node:timers/promises": { setTimeout: async (ms) => {
      now += ms;
      if (probes && options.available) blocked = false;
    } },
    "node:child_process": { execFile: async (command, args, limits) => {
      reloads++;
      assert.equal(command, "openclaw");
      assert.deepEqual(Array.from(args), ["secrets", "reload", "--json", "--timeout", "60000"]);
      assert.equal(limits.timeout, 120_000);
      if (options.reloadFails) throw new Error("private diagnostic must stay private");
      return { stdout: '{"ok":true}' };
    } },
    "node:util": { promisify: (fn) => fn },
    "/app/dist/store-F1B2duCT.js": { d: loadStore },
    "/app/dist/usage-state-CAKmPrwS.js": { o: (store) => store.blocked },
    "/app/dist/usage-_yfLJGtN.js": { s: () => { probes++; } },
    "/app/dist/store-CZzbMlii.js": { m: loadStore },
    "/app/dist/usage-state-C0QBjJnZ.js": { o: (store) => store.blocked },
    "/app/dist/usage-CWqpxTil.js": { s: () => { probes++; } },
  };
  async function moduleFor(name) {
    const exports = modules[name];
    assert.ok(exports, `Unexpected dependency: ${name}`);
    const module = new vm.SyntheticModule(Object.keys(exports), function () {
      for (const [key, value] of Object.entries(exports)) this.setExport(key, value);
    }, { context });
    await module.link(() => {});
    await module.evaluate();
    return module;
  }
  const entry = new vm.SourceTextModule(source, { context, importModuleDynamically: moduleFor });
  await entry.link(moduleFor);
  let error;
  try { await entry.evaluate(); } catch (e) { error = e; }
  return { probes, reloads, output, error, code: process.exitCode ?? 0 };
}

for (const options of [{ version: "2026.9.3" }, { ambiguous: true }, { source: "codex_rate_limits" }]) {
  const result = await run(options);
  assert.ok(result.error);
  assert.equal(result.probes, 0);
  assert.equal(result.reloads, 0);
}
const legacy = await run({ version: "2026.9.1", available: true });
assert.equal(legacy.error, undefined);
assert.equal(legacy.code, 0);
assert.equal(legacy.probes, 1);
assert.equal(legacy.reloads, 1);
const check = await run({ mode: "--check" });
assert.equal(check.code, 1);
assert.equal(check.probes + check.reloads, 0);
const denied = await run();
assert.equal(denied.code, 1);
assert.equal(denied.probes, 1);
assert.equal(denied.reloads, 0);
const recovered = await run({ available: true });
assert.equal(recovered.error, undefined);
assert.equal(recovered.code, 0);
assert.equal(recovered.probes, 1);
assert.equal(recovered.reloads, 1);
const repeated = await run({ blocked: false });
assert.equal(repeated.code, 0);
assert.equal(repeated.probes, 0);
assert.equal(repeated.reloads, 1);
const failedReload = await run({ blocked: false, reloadFails: true });
assert.equal(failedReload.code, 1);
assert.ok(failedReload.output.every((line) => !line.includes("private diagnostic")));
console.log("OpenClaw recovery: fail-closed guards, provider denial, snapshot reload, repeatability passed");
