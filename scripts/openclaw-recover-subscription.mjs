// Run inside the pinned OpenClaw container; see the app README.
// No SQL writes or unconditional cooldown reset: upstream probes the provider,
// checks credential/block generations, and owns the transactional update.
import { readFile } from "node:fs/promises";
import { setTimeout as delay } from "node:timers/promises";
import { execFile } from "node:child_process";
import { promisify } from "node:util";

const mode = process.argv[2] ?? "--check";
if (!["--check", "--recover"].includes(mode)) {
  throw new Error("Expected --check or --recover");
}
const runtime = JSON.parse(await readFile("/app/package.json", "utf8"));
if (runtime.version !== "2026.9.1") {
  throw new Error("Recovery requires reviewed OpenClaw 2026.9.1 internals");
}
const { m: loadStore } = await import("/app/dist/store-CZzbMlii.js");
const { o: inCooldown } = await import("/app/dist/usage-state-C0QBjJnZ.js");
const { s: reprobe } = await import("/app/dist/usage-CWqpxTil.js");
const agentDir = "/data/openclaw/agents/main/agent";
const model = "gpt-6-astra";
const store = loadStore(agentDir);
const profiles = Object.entries(store.profiles)
  .filter(([, p]) => p.provider === "openai" && p.type === "oauth")
  .map(([id]) => id);
if (profiles.length !== 1) {
  throw new Error("Expected exactly one OpenAI OAuth profile; refusing ambiguous recovery");
}
const [profileId] = profiles;
const blocked = (current) => inCooldown(current, profileId, Date.now(), model);
if (!blocked(store)) {
  console.log("PASS: Astra OAuth profile is not blocked (inference still needs verification)");
} else if (mode === "--check") {
  console.error("FAIL: Astra OAuth profile is blocked before inference");
  process.exitCode = 1;
} else {
  const stats = store.usageStats?.[profileId];
  if (stats?.blockedSource !== "wham" || stats.blockedReason !== "subscription_limit") {
    throw new Error("Not a provider usage block; refusing unrelated auth recovery");
  }
  // This schedules one bounded upstream recheck. It respects probe intervals,
  // active auth failures, current provider limits, and concurrent state changes.
  reprobe({ store, profileIds: profiles, agentDir, forModel: model });
  const deadline = Date.now() + 30_000;
  let recovered = false;
  while (Date.now() < deadline) {
    await delay(1_000);
    if (!blocked(loadStore(agentDir))) {
      recovered = true;
      break;
    }
  }
  if (!recovered) {
    console.error("FAIL: profile remains blocked; provider/probe policy retained, no forced reset");
    process.exitCode = 1;
  } else {
    console.log("PASS: provider recheck cleared stale usage block; verify gateway heartbeat");
  }
}
if (mode === "--recover" && !process.exitCode) {
  // A running gateway retains a separate auth snapshot. Reload through its
  // public API even on an already-clear rerun (e.g. after an interrupted reload).
  try {
    const { stdout } = await promisify(execFile)("openclaw", [
      "secrets", "reload", "--json", "--timeout", "60000",
    ], { timeout: 120_000, maxBuffer: 1024 * 1024 });
    if (JSON.parse(stdout).ok !== true) throw new Error("reload rejected");
    console.log("PASS: gateway auth snapshot reloaded; verify heartbeat completion");
  } catch {
    console.error("FAIL: gateway snapshot reload failed; rerun recovery after checking gateway health");
    process.exitCode = 1;
  }
}
