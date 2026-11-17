#!/usr/bin/env bash
# Disposable pinned-image contract test: never reaches the cluster or host network.
set -euo pipefail
mode="${1:-full}"
case "$mode" in full|verify-only|probe-only) ;; *) echo "usage: $0 [full|verify-only|probe-only]" >&2; exit 2 ;; esac
repo_root="$(cd "$(dirname "${BASH_SOURCE[0]}")/../.." && pwd)"
image='docker.io/louislam/uptime-kuma:2.5.11@sha256:7554dba313c84e44fee921ef3b5626ba1c711e412e82815e8c957517026112a9'
scratch="$(mktemp -d)"
volume=""
trap 'if [[ -n "$volume" ]]; then docker volume rm "$volume" >/dev/null; fi; rm -rf "$scratch"' EXIT
chmod 755 "$scratch"
cat > "$scratch/integration.js" <<'JS'
"use strict";
const assert = require("node:assert/strict");
const fs = require("node:fs");
const { spawn } = require("node:child_process");
const adapter = require("/config/reconcile.js");
const password = "disposable-integration-only-password";
const opts = { url: "http://127.0.0.1:3001", dataDir: "/test/data" };
const m = { key: "fixture", name: "Fixture", ownerAppIds: ["fixture"], kind: "http", enabled: false, target: { url: "http://127.0.0.1:3001/dashboard" }, expected: { statusCodes: [200] }, intervalSeconds: 60, timeoutSeconds: 10, retries: 1, meaning: "Test process HTTP readiness", limitations: "Disposable integration only" };
const catalog = { schemaVersion: 1, apps: [], monitors: [m] };
async function stop(server) {
    if (server.exitCode !== null || server.signalCode !== null) return;
    const exited = new Promise(resolve => server.once("exit", resolve));
    server.kill("SIGTERM");
    let timer;
    try { await Promise.race([exited, new Promise((_, reject) => { timer = setTimeout(() => reject(Error("shutdown timeout")), 30000); })]); }
    finally { clearTimeout(timer); if (server.exitCode === null) server.kill("SIGKILL"); }
}
async function completed(child, timeout = 30000) {
    let timer;
    try {
        const [code, signal] = await Promise.race([
            new Promise(resolve => child.once("exit", (...result) => resolve(result))),
            new Promise((_, reject) => { timer = setTimeout(() => reject(Error("CLI completion timeout")), timeout); }),
        ]);
        assert.equal(signal, null);
        assert.equal(code, 0);
    } finally { clearTimeout(timer); if (child.exitCode === null && child.signalCode === null) child.kill("SIGKILL"); }
}
async function onceWithWatch() {
    const args = ["--catalog", "/test/projected/catalog.json", "--password-file", "/test/projected/password", "--status-file", "/test/work/status.json"];
    const watcher = spawn(process.execPath, ["/config/reconcile.js", "watch", ...args], { stdio: "ignore" });
    try {
        const deadline = Date.now() + 30000;
        while (!fs.existsSync("/test/work/status.json")) {
            assert.equal(watcher.exitCode, null, "watch must remain running");
            if (Date.now() > deadline) throw Error("watch initial reconciliation timeout");
            await new Promise(resolve => setTimeout(resolve, 50));
        }
        const initial = JSON.parse(fs.readFileSync("/test/work/status.json", "utf8"));
        assert.equal(initial.ok, true);
        await new Promise(resolve => setTimeout(resolve, 10));
        const once = spawn(process.execPath, ["/config/reconcile.js", "once", ...args], { stdio: "ignore" });
        await completed(once);
        assert.equal(watcher.exitCode, null, "once must not stop watch");
        assert.equal(watcher.signalCode, null);
        const after = JSON.parse(fs.readFileSync("/test/work/status.json", "utf8"));
        assert.equal(after.ok, true);
        assert.ok(Date.parse(after.lastSuccess) > Date.parse(initial.lastSuccess));
        assert.equal(after.catalogHash, initial.catalogHash);
        assert.deepEqual(after.counts, { managed: 1, created: 0, changed: 0, paused: 0, resumed: 0, settings: 0 });
    } finally { await stop(watcher); }
}
async function jsonHealth(client) {
    const jsonata = require("/app/node_modules/jsonata");
    const expression = jsonata(adapter.JSON_HEALTH);
    const response = value => ({ status: "success", data: { result: [{ value: [1, value] }] } });
    for (const [payload, expected] of [[response("1"), "1"], [response("0"), "0"], [{}, "0"], [{ status: "success", data: { result: [] } }, "0"], [{ status: "success", data: { result: [response("1").data.result[0], response("1").data.result[0]] } }, "0"], [{ status: "error", data: response("1").data }, "0"]]) assert.equal(await expression.evaluate(payload), expected);
    const http = require("node:http");
    const fixture = http.createServer((request, reply) => {
        if (request.url.startsWith("/ping-")) {
            const scenario = request.url.slice(6);
            if (scenario === "redirect") { reply.writeHead(302, { Location: "/ping-healthy" }).end(); return; }
            reply.writeHead(scenario === "error500" ? 500 : 200, { "Content-Type": "application/json" });
            reply.end(scenario === "malformed" ? "not-json" : JSON.stringify(scenario === "missing" ? {} : { status: scenario === "healthy" ? "OK" : "Error" })); return;
        }
        if (request.url === "/401") { reply.writeHead(401).end(); return; }
        if (request.url === "/302") { reply.writeHead(302, { Location: "/healthy" }).end(); return; }
        const payload = request.url === "/missing" ? {} : request.url === "/multiple" ? { status: "success", data: { result: [response("1").data.result[0], response("1").data.result[0]] } } : response(request.url === "/unhealthy" ? "0" : "1");
        reply.writeHead(200, { "Content-Type": "application/json" }); reply.end(JSON.stringify(payload));
    });
    const ids = [];
    await new Promise(resolve => fixture.listen(3903, "127.0.0.1", resolve));
    try {
        for (const scenario of ["healthy", "missing", "multiple", "unhealthy", "401", "302"]) {
            const fields = adapter.projection({ ...m, enabled: true, kind: "json-query", target: { url: `http://127.0.0.1:3903/${scenario}` }, expected: { statusCodes: [200], jsonPath: adapter.JSON_HEALTH, value: "1" } });
            const result = await client.request("add", { ...fields, name: `Integration ${scenario}`, description: `disposable-integration:${scenario}`, interval: 20, retryInterval: 20, maxretries: 0, parent: null, notificationIDList: {}, conditions: [], kafkaProducerBrokers: [], kafkaProducerSaslOptions: {}, rabbitmqNodes: [] });
            ids.push([result.monitorID, scenario === "healthy" ? 1 : 0]);
        }
        for (const scenario of ["healthy", "error500", "malformed", "missing", "wrong", "redirect"]) {
            const fields = adapter.projection({ ...m, enabled: true, kind: "json-query", target: { url: `http://127.0.0.1:3903/ping-${scenario}` }, expected: { statusCodes: [200], jsonPath: "status", value: "OK" } });
            const result = await client.request("add", { ...fields, name: `Integration ping ${scenario}`, description: `disposable-integration:ping-${scenario}`, interval: 20, retryInterval: 20, maxretries: 0, parent: null, notificationIDList: {}, conditions: [], kafkaProducerBrokers: [], kafkaProducerSaslOptions: {}, rabbitmqNodes: [] });
            ids.push([result.monitorID, scenario === "healthy" ? 1 : 0]);
        }
        await Promise.all(ids.map(([id, expected]) => adapter.waitForSamples(client, id, expected, 1, 0, 45000)));
        console.log("PASS: actual JSONata and native JSON-query reject missing/multiple/false, HTTP401 and redirect302");
    } finally {
        for (const [id] of ids) await client.request("pauseMonitor", id);
        await new Promise(resolve => fixture.close(resolve));
    }
}
async function acceptanceCLI() {
    const child = spawn(process.execPath, ["/config/reconcile.js", "acceptance", "--password-file", "/test/projected/password"], { stdio: ["ignore", "pipe", "ignore"] });
    let output = "";
    child.stdout.on("data", chunk => { output += chunk; });
    await completed(child, 570000);
    const result = JSON.parse(output.trim());
    assert.equal(result.ok, true); assert.equal(result.initialObservations, 3);
    assert.ok(result.downMs <= 180000); assert.ok(result.recoveryMs <= 180000);
    console.log(`PASS: actual acceptance CLI three observations, down ${result.downMs}ms, recovered ${result.recoveryMs}ms`);
    return result;
}
if (process.argv[2] === "prepare") {
    assert.equal(process.getuid(), 0);
    for (const name of ["data", "work"]) {
        fs.mkdirSync(`/test/${name}`, { mode: 0o750 });
        fs.chownSync(`/test/${name}`, 10001, 10001);
    }
    fs.mkdirSync("/test/projected", { mode: 0o750 });
    for (const [name, content] of [["password", password], ["catalog.json", JSON.stringify(catalog)], ["active-catalog.json", JSON.stringify({ ...catalog, monitors: [{ ...m, enabled: true }] })]]) {
        fs.writeFileSync(`/test/projected/${name}`, content, { mode: 0o440 });
        fs.chownSync(`/test/projected/${name}`, 0, 10001);
    }
    fs.chownSync("/test/projected", 0, 10001);
    process.exit(0);
}
(async () => {
    assert.equal(process.getuid(), 10001);
    assert.equal(process.getgid(), 10001);
    for (const name of ["password", "catalog.json", "active-catalog.json"]) {
        const metadata = fs.statSync(`/test/projected/${name}`);
        assert.equal(metadata.uid, 0); assert.equal(metadata.gid, 10001);
        assert.equal(metadata.mode & 0o777, 0o440);
    }
    assert.equal(fs.readFileSync("/test/projected/password", "utf8"), password);
    assert.deepEqual(JSON.parse(fs.readFileSync("/test/projected/catalog.json", "utf8")), catalog);
    assert.equal(fs.statSync(opts.dataDir).uid, 10001);
    assert.equal(fs.statSync(opts.dataDir).gid, 10001);
    assert.ok(require("/app/node_modules/socket.io-client"));
    assert.ok(require("/app/node_modules/@louislam/sqlite3"));
    await adapter.bootstrap(opts, password);
    assert.ok(fs.existsSync("/test/data/kuma.db"));
    assert.equal(fs.statSync("/test/data/kuma.db").uid, 10001);
    // A second bootstrap must preserve account and data, and stop before main.
    await adapter.bootstrap(opts, password);
    await assert.rejects(adapter.bootstrap(opts, "incorrect-integration-password"), /rejected-login/);
    const server = spawn(process.execPath, ["/app/server/server.js", "--host=127.0.0.1", "--port=3001", "--data-dir=/test/data"], { cwd: "/app", stdio: "ignore" });
    let client;
    try {
        client = await adapter.connect(opts.url);
        await adapter.login(client, password);
        assert.equal(await client.request("needSetup"), false);
        await assert.rejects(client.request("setup", "replacement", password));
        const settings = (await client.request("getSettings")).data;
        await client.request("setSettings", { ...settings, searchEngineIndex: false, keepDataPeriodDays: 14 }, password);
        let result = await adapter.reconcile(client, catalog, password);
        assert.equal(result.created, 1); assert.equal(result.settings, 1);
        const first = Object.values(await client.list())[0];
        const record = (await client.request("getMonitor", first.id)).monitor;
        assert.equal(record.active, false);
        assert.equal((await client.request("getSettings")).data.searchEngineIndex, false);
        result = await adapter.reconcile(client, catalog, password);
        assert.deepEqual(result, { managed: 1, created: 0, changed: 0, paused: 0, resumed: 0, settings: 0 });
        const changed = { ...catalog, monitors: [{ ...m, name: "Changed fixture", enabled: true }] };
        result = await adapter.reconcile(client, changed, password);
        assert.equal(result.changed, 1); assert.equal(result.resumed, 1);
        result = await adapter.reconcile(client, catalog, password);
        assert.equal(result.paused, 1);
        assert.equal(Object.values(await client.list())[0].id, first.id);
        assert.equal(Object.values(await client.list()).length, 1);
        await onceWithWatch();
        assert.equal(Object.values(await client.list()).length, 1);
        assert.equal(Object.values(await client.list())[0].id, first.id);
        console.log("PASS: real once CLI completes while watch remains live; shared status refreshed, no duplicate or mutation");
        const anonymous = await adapter.connect(opts.url);
        try { await assert.rejects(anonymous.request("getSettings"), /rejected-getSettings/); await assert.rejects(anonymous.request("getMonitor", first.id), /rejected-getMonitor/); } finally { anonymous.close(); }
        await jsonHealth(client);
        console.log("PASS: native ping JSON200 OK; 500/Error, malformed, missing/wrong status and redirect302 rejected");
        if (process.argv[2] === "probe-only") return;
        const activeCatalog = { ...catalog, monitors: [{ ...m, enabled: true }] };
        const observationStart = Date.now() - 1000;
        await adapter.reconcile(client, activeCatalog, password);
        if (process.argv[2] === "verify-only") {
            await adapter.waitForSamples(client, first.id, 1, 3, observationStart, 180000);
        } else {
            const acceptanceResult = await acceptanceCLI();
            assert.equal((await client.request("getMonitor", acceptanceResult.monitorID)).monitor.active, false);
        }
        const verification = await adapter.verify(client, activeCatalog);
        assert.equal(verification.ok, true); assert.equal(verification.healthy, true);
        assert.equal(verification.monitors[0].observations.length, 3);
        const verifier = spawn(process.execPath, ["/config/reconcile.js", "verify", "--catalog", "/test/projected/active-catalog.json", "--password-file", "/test/projected/password"], { stdio: "ignore" });
        await completed(verifier);
        await adapter.reconcile(client, catalog, password);
        console.log("PASS: unauthorized admin denied; verify CLI reads three real observations");
        console.log("PASS: pinned rootless bootstrap, existing owner, invalid login, add/edit/resume/pause/no-op, settings and IDs retained");
    } finally { client?.close(); await stop(server); }
})().catch(error => { console.error("FAIL:", error.message); process.exitCode = 1; });
JS
cp "$repo_root/clusters/homelab/apps/uptime-kuma/reconcile.js" "$scratch/reconcile.js"
chmod 444 "$scratch/integration.js" "$scratch/reconcile.js"
volume="$(docker volume create)"
# Test-only permission preparation models root-owned projected files and fsGroup.
docker run --rm --network none --user 0:0 --cap-drop ALL --cap-add CHOWN \
  --security-opt no-new-privileges --read-only --tmpfs /tmp:rw,nosuid,nodev,size=128m \
  --mount "type=bind,src=$scratch/reconcile.js,dst=/config/reconcile.js,readonly" \
  --mount "type=bind,src=$scratch/integration.js,dst=/integration.js,readonly" \
  --mount "type=volume,src=$volume,dst=/test" \
  --entrypoint node "$image" /integration.js prepare
docker run --rm --network none --user 10001:10001 \
  --cap-drop ALL --security-opt no-new-privileges --read-only \
  --tmpfs /tmp:rw,nosuid,nodev,size=128m \
  --mount "type=bind,src=$scratch/reconcile.js,dst=/config/reconcile.js,readonly" \
  --mount "type=bind,src=$scratch/integration.js,dst=/integration.js,readonly" \
  --mount "type=volume,src=$volume,dst=/test" \
  --entrypoint node "$image" /integration.js "$mode"
