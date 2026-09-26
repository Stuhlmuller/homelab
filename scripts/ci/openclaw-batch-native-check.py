#!/usr/bin/env python3
"""Prove pinned OpenClaw batch semantics in disposable Linux Docker state; never start a gateway."""
import json
import os
from pathlib import Path
import platform
import re
import shutil
import subprocess
import sys
import tempfile
import uuid

ROOT = Path(__file__).resolve().parents[2]
VALUES = Path("clusters/homelab/apps/openclaw/values.yaml")
VERSION = "2026.9.2"

# Every credential-like value below is invented fixture data. No operator state,
# package installation, plugins, gateway, or network service is used by the test.
FIXTURE = r"""
import assert from "node:assert/strict";
import fs from "node:fs";
import path from "node:path";
import { spawnSync } from "node:child_process";
import { pathToFileURL } from "node:url";

let stage = "image-version";
try {
  assert.equal(JSON.parse(fs.readFileSync("/app/package.json", "utf8")).version, "2026.9.2", "unexpected vendor version");
  const files = fs.readdirSync("/app/dist").filter(name => /^io\.audit-.*\.js$/.test(name));
  assert.equal(files.length, 1, "ambiguous vendor config audit module");
  const audit = await import(pathToFileURL(path.join("/app/dist", files[0])).href);
  const readers = Object.values(audit).filter(value => typeof value === "function" && value.name === "readRecentConfigAuditRecords");
  assert.equal(readers.length, 1, "unknown vendor audit reader");
  const readAudit = readers[0];
  const baseline = {
    gateway: { mode: "local", port: 18000, auth: { mode: "none" } },
    agents: { defaults: { workspace: "/work/unrelated-workspace" } },
    logging: { level: "warn", consoleLevel: "silent" },
  };
  const cases = [];
  const make = (name, original = baseline) => {
    const directory = `/work/${name}`;
    fs.mkdirSync(directory, { mode: 0o700 });
    const config = `${directory}/openclaw.json`;
    fs.writeFileSync(config, JSON.stringify(original) + "\n", { mode: 0o600 });
    const env = {
      PATH: "/usr/local/bin:/usr/bin:/bin", HOME: directory,
      OPENCLAW_STATE_DIR: directory, OPENCLAW_CONFIG_PATH: config,
      OPENCLAW_GATEWAY_TOKEN: "aaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaa",
      GRAFANA_ALERT_HOOK_TOKEN: "bbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbb",
      NO_COLOR: "1", TERM: "dumb",
    };
    return { directory, config, env };
  };
  const cli = (fixture, args, success = true) => {
    const result = spawnSync(process.execPath, ["/app/openclaw.mjs", ...args], {
      cwd: fixture.directory, env: fixture.env, encoding: "utf8",
      timeout: 90000, killSignal: "SIGKILL", maxBuffer: 1024 * 1024,
      stdio: ["ignore", "pipe", "pipe"],
    });
    assert.equal(result.error, undefined, "vendor CLI timed out or exceeded output bound");
    assert.equal(result.signal, null, "vendor CLI was terminated");
    assert.equal(result.status === 0, success, `unexpected vendor CLI exit ${result.status}`);
  };
  const batch = (fixture, entries, dryRun = false, success = true) => {
    const file = `${fixture.directory}/batch.json`;
    fs.writeFileSync(file, JSON.stringify(entries), { mode: 0o600 });
    cli(fixture, ["config", "set", "--batch-file", file, ...(dryRun ? ["--dry-run"] : [])], success);
  };
  const successfulWrites = fixture => readAudit({ env: fixture.env, limit: 100 }).filter(record =>
    record.event === "config.write" && record.configPath === fixture.config &&
    record.result !== "failed" && record.result !== "rejected");
  const retained = value => {
    assert.deepEqual(value.agents, baseline.agents, "unrelated agent config changed");
    assert.deepEqual(value.logging, baseline.logging, "unrelated logging config changed");
  };
  const ref = { source: "env", provider: "default", id: "OPENCLAW_GATEWAY_TOKEN" };
  const operations = [
    { path: "secrets.providers.default", provider: { source: "env", allowlist: ["OPENCLAW_GATEWAY_TOKEN"] } },
    { path: "gateway.auth.mode", value: "token" },
    { path: "gateway.auth.token", ref },
    { path: "gateway.controlUi.allowedOrigins", value: ["https://fixture.invalid"] },
    { path: "browser.enabled", value: false },
    { path: "gateway.port", value: 19001 },
    { path: "gateway.port", value: 19002 },
  ];

  stage = "typed-ordered-preserving-batch";
  const applied = make("applied");
  batch(applied, operations);
  const value = JSON.parse(fs.readFileSync(applied.config, "utf8"));
  retained(value);
  assert.equal(value.gateway.port, 19002, "ordered duplicate path did not use last value");
  assert.equal(value.browser.enabled, false, "boolean assignment changed type");
  assert.deepEqual(value.gateway.controlUi.allowedOrigins, ["https://fixture.invalid"], "array assignment changed type");
  assert.deepEqual(value.gateway.auth.token, ref, "authored SecretRef was not preserved");
  assert.deepEqual(value.secrets.providers.default, { source: "env", allowlist: ["OPENCLAW_GATEWAY_TOKEN"] });
  assert.equal(successfulWrites(applied).length, 1, "batch did not produce exactly one successful config-write audit record");
  cases.push(stage);

  stage = "sequential-write-control";
  const sequential = make("sequential");
  cli(sequential, ["config", "set", "gateway.port", "19001", "--strict-json"]);
  cli(sequential, ["config", "set", "gateway.port", "19002", "--strict-json"]);
  assert.equal(successfulWrites(sequential).length, 2, "two real mutations did not produce two config-write records");
  cases.push(stage);

  stage = "dry-run-no-config-write";
  const dry = make("dry");
  const beforeDry = fs.readFileSync(dry.config);
  batch(dry, operations, true);
  assert.deepEqual(fs.readFileSync(dry.config), beforeDry, "dry-run changed config bytes");
  assert.equal(successfulWrites(dry).length, 0, "dry-run wrote config");
  cases.push(stage);

  stage = "late-schema-failure-atomicity";
  const invalid = make("invalid");
  const beforeInvalid = fs.readFileSync(invalid.config);
  batch(invalid, [{ path: "browser.enabled", value: true }, { path: "gateway.port", value: "not-a-number" }], false, false);
  assert.deepEqual(fs.readFileSync(invalid.config), beforeInvalid, "invalid batch partially changed config");
  assert.equal(successfulWrites(invalid).length, 0, "invalid batch wrote config");
  cases.push(stage);

  stage = "ambiguous-entry-atomicity";
  batch(invalid, [{ path: "gateway.port", value: 19003 }, { path: "gateway.auth.token", value: "synthetic", ref }], false, false);
  assert.deepEqual(fs.readFileSync(invalid.config), beforeInvalid, "malformed batch partially changed config");
  assert.equal(successfulWrites(invalid).length, 0, "malformed batch wrote config");
  cases.push(stage);

  stage = "legacy-hook-unset-before-literal-batch";
  const hook = make("hook", { ...baseline, hooks: { enabled: true, path: "/hooks", token: "${GRAFANA_ALERT_HOOK_TOKEN}" } });
  cli(hook, ["config", "unset", "hooks.token"]);
  batch(hook, [
    { path: "hooks.token", value: "synthetic-hook-after" },
    { path: "hooks.defaultSessionKey", value: "hook:fixture" },
    { path: "hooks.allowRequestSessionKey", value: false },
  ]);
  const hookValue = JSON.parse(fs.readFileSync(hook.config, "utf8"));
  retained(hookValue);
  assert.equal(hookValue.hooks.token, "synthetic-hook-after", "legacy env template survived the unset/literal sequence");
  assert.equal(hookValue.hooks.defaultSessionKey, "hook:fixture");
  assert.equal(hookValue.hooks.allowRequestSessionKey, false);
  assert.equal(successfulWrites(hook).length, 2, "unset and batch did not each write once");
  cases.push(stage);
  console.log(JSON.stringify({ vendor: "OpenClaw 2026.9.2", passed: cases.length, cases, successfulWrites: { batch: 1, sequential: 2 } }));
} catch (error) {
  // All inputs are synthetic, but never dump configs, audit rows or vendor output.
  console.error(`OpenClaw native batch fixture failed at ${stage}: ${String(error.message).split("\n")[0].slice(0, 240)}`);
  process.exitCode = 1;
}
"""


def image_reference():
    path = ROOT / VALUES
    if path.is_symlink() or not path.is_file():
        raise RuntimeError("Committed OpenClaw values are missing or invalid")
    committed = subprocess.run(["git", "show", f"HEAD:{VALUES.as_posix()}"], cwd=ROOT,
                               check=True, capture_output=True, timeout=30).stdout
    if committed != path.read_bytes():
        raise RuntimeError("Native proof requires the committed OpenClaw values")
    query = ('.controllers.openclaw | '
             '{"app": .containers.app.image, "bootstrap": .initContainers."bootstrap-config".image}')
    result = subprocess.run(["yq", "-o=json", query, str(path)],
                            check=True, capture_output=True, timeout=30)
    images = json.loads(result.stdout)
    image = images["app"]
    if (image != images["bootstrap"] or set(image) != {"repository", "tag"}
            or image["repository"] != "ghcr.io/openclaw/openclaw"
            or not re.fullmatch(re.escape(VERSION) + r"@sha256:[0-9a-f]{64}", image["tag"])):
        raise RuntimeError("Expected matching digest-pinned OpenClaw 2026.9.2 app/bootstrap images")
    return image["repository"] + ":" + image["tag"]


def main():
    if len(sys.argv) != 1:
        raise RuntimeError("Native batch proof accepts no overrides")
    if platform.system() != "Linux" or platform.machine() != "x86_64":
        raise RuntimeError("Native proof requires Linux amd64 Docker; no host CLI fallback")
    image = image_reference()
    executable = shutil.which("docker")
    if executable is None:
        raise RuntimeError("Docker is required; no daemon is started by this check")
    with tempfile.TemporaryDirectory(prefix="openclaw-batch-native-") as directory:
        scratch = Path(directory)
        scratch.chmod(0o755)
        config = scratch / "docker-config"
        config.mkdir(mode=0o700)
        (config / "config.json").write_text('{"auths":{}}\n')
        fixture = scratch / "fixture.mjs"
        fixture.write_text(FIXTURE)
        fixture.chmod(0o444)
        # Explicit local Linux daemon and empty credentials; no caller Docker
        # context, registry login, proxy, HOME, or environment input is forwarded.
        command = [executable, "--host", "unix:///var/run/docker.sock", "--config", str(config)]
        env = {"PATH": os.defpath, "HOME": str(scratch), "LANG": "C"}

        def docker(*args, timeout=120, check=True):
            result = subprocess.run([*command, *args], env=env, stdin=subprocess.DEVNULL,
                                    capture_output=True, text=True, timeout=timeout)
            if check and result.returncode:
                raise RuntimeError(f"Docker {args[0]} failed; output withheld")
            return result

        docker("pull", "--platform", "linux/amd64", image, timeout=300)
        image_id = docker("image", "inspect", "--format", "{{.Id}}", image).stdout.strip()
        if not re.fullmatch(r"sha256:[0-9a-f]{64}", image_id):
            raise RuntimeError("Pulled image identity is unavailable")
        name = "openclaw-batch-" + uuid.uuid4().hex
        try:
            docker("create", "--name", name, "--platform", "linux/amd64", "--pull", "never",
                   "--network", "none", "--user", "1000:1000", "--cap-drop", "ALL",
                   "--security-opt", "no-new-privileges:true", "--read-only", "--pids-limit", "128",
                   "--memory", "2g", "--memory-swap", "2g", "--cpus", "2", "--ulimit", "core=0",
                   "--tmpfs", "/work:rw,nosuid,nodev,size=256m,uid=1000,gid=1000,mode=0700",
                   "--tmpfs", "/tmp:rw,nosuid,nodev,size=64m,mode=1777",
                   "--mount", f"type=bind,src={fixture},dst=/fixture.mjs,readonly",
                   "--workdir", "/work", "--entrypoint", "node", image_id, "/fixture.mjs")
            result = docker("start", "--attach", name, timeout=600, check=False)
            if result.returncode:
                diagnostic = next((line for line in result.stderr.splitlines()
                                   if line.startswith("OpenClaw native batch fixture failed at ")), "fixture process failed")
                raise RuntimeError(diagnostic[:320])
            receipt = json.loads(result.stdout)
            if receipt.get("passed") != 6 or receipt.get("successfulWrites") != {"batch": 1, "sequential": 2}:
                raise RuntimeError("Native fixture receipt is incomplete")
            print(json.dumps(receipt, separators=(",", ":")))
        finally:
            removed = docker("rm", "--force", "--volumes", name, check=False)
            if removed.returncode and "No such container" not in removed.stderr:
                raise RuntimeError("Owned synthetic container cleanup failed")


if __name__ == "__main__":
    try:
        main()
    except Exception as error:
        print(f"OpenClaw native batch check failed: {error}", file=sys.stderr)
        raise SystemExit(1) from None
