#!/usr/bin/env node
"use strict";
const assert = require("node:assert/strict");
const { EventEmitter } = require("node:events");
const { test } = require("node:test");
const adapter = require("../../clusters/homelab/apps/uptime-kuma/reconcile.js");
const monitor = { key: "fixture", name: "Fixture", ownerAppIds: ["fixture"], kind: "http", enabled: true, target: { url: "http://fixture.default.svc:8080/health" }, expected: { statusCodes: [200] }, intervalSeconds: 60, timeoutSeconds: 10, retries: 1, meaning: "Fixture health", limitations: "Local test only" };
const catalog = { schemaVersion: 1, apps: [], monitors: [monitor] };
class Fake {
    constructor(records = []) { this.records = structuredClone(records); this.settings = { keepDataPeriodDays: 30, custom: "preserved" }; this.writes = []; this.needsSetup = false; }
    async list() { return Object.fromEntries(this.records.map(m => [m.id, structuredClone(m)])); }
    async request(event, ...args) {
        if (event === "needSetup") return this.needsSetup;
        if (event === "login") { if (this.invalidLogin) throw new adapter.AdapterError("rejected-login"); return { ok: true }; }
        if (event === "getSettings") return { data: structuredClone(this.settings) };
        if (event === "getMonitor") return { monitor: structuredClone(this.records.find(m => m.id === args[0])) };
        this.writes.push([event, structuredClone(args)]);
        if (event === "setup") this.needsSetup = false;
        if (event === "setSettings") this.settings = args[0];
        if (event === "add") {
            if (this.rejectAdd) throw new adapter.AdapterError("rejected-add");
            this.records.push({ ...args[0], id: this.records.length + 1 });
            if (this.uncertainAdd) throw new adapter.AdapterError("ack-timeout-add");
        }
        if (event === "editMonitor") { const index = this.records.findIndex(m => m.id === args[0].id); this.records[index] = { ...args[0], active: this.records[index].active }; }
        if (event === "pauseMonitor" || event === "resumeMonitor") this.records.find(m => m.id === args[0]).active = event === "resumeMonitor";
        return { ok: true };
    }
}
test("existing owner is never setup or reset, including invalid login", async () => {
    const client = new Fake(); await adapter.login(client, "fixture-password", true); assert.equal(client.writes.length, 0);
    client.invalidLogin = true; await assert.rejects(adapter.login(client, "fixture-password", true)); assert.equal(client.writes.length, 0);
});
test("first owner requires explicit bootstrap authority", async () => {
    const client = new Fake(); client.needsSetup = true; await assert.rejects(adapter.login(client, "fixture-password"));
    await adapter.login(client, "fixture-password", true); assert.equal(client.writes[0][0], "setup");
});
test("duplicate ownership stops before any writes including retention", async () => {
    const record = adapter.projection(monitor); const client = new Fake([{ ...record, id: 1 }, { ...record, id: 2 }]); client.settings = {};
    await assert.rejects(adapter.reconcile(client, catalog, "password"), /duplicate-owned-key/); assert.deepEqual(client.writes, []);
});
test("successful uncertain add is reread once and never duplicated", async () => {
    const client = new Fake(); client.uncertainAdd = true;
    await adapter.reconcile(client, catalog, "password"); assert.equal(client.records.length, 1); assert.equal(client.writes.filter(x => x[0] === "add").length, 1);
    client.writes = []; await adapter.reconcile(client, catalog, "password"); assert.equal(client.writes.length, 0);
});
test("partial failure is resumable, no blind add retry", async () => {
    const client = new Fake(); client.rejectAdd = true;
    await assert.rejects(adapter.reconcile(client, catalog, "password")); assert.equal(client.writes.length, 1);
    client.rejectAdd = false; await adapter.reconcile(client, catalog, "password"); assert.equal(client.records.length, 1);
});
test("edit preserves unrelated record/settings and uses explicit pause", async () => {
    const client = new Fake([{ ...adapter.projection(monitor), id: 7, name: "old", custom: "keep", notificationIDList: { 3: true } }, { id: 8, name: "unowned" }]);
    client.settings.keepDataPeriodDays = 14;
    await adapter.reconcile(client, { ...catalog, monitors: [{ ...monitor, enabled: false }] }, "password");
    assert.equal(client.records[0].custom, "keep"); assert.deepEqual(client.records[0].notificationIDList, { 3: true }); assert.equal(client.records[0].active, false);
    assert.equal(client.settings.custom, "preserved"); assert.equal(client.settings.keepDataPeriodDays, 30); assert.deepEqual(client.records[1], { id: 8, name: "unowned" });
    assert.ok(client.writes.some(x => x[0] === "pauseMonitor")); client.writes = [];
    await adapter.reconcile(client, { ...catalog, monitors: [{ ...monitor, enabled: false }] }, "password"); assert.equal(client.writes.length, 0);
});
test("explicit retired ownership pauses in place and preserves historical record fields", async () => {
    const retiredCatalog = { ...catalog, apps: [{ id: "fixture", lifecycle: "retired", monitorIds: ["fixture"], source: "retirement.md", reason: "Retired fixture; preserve monitoring history." }], monitors: [{ ...monitor, enabled: false }] };
    const client = new Fake([{ ...adapter.projection(monitor), id: 42, heartbeatHistory: [{ status: 1, time: "2026-11-17T00:00:00Z" }] }]);
    const original = structuredClone(client.records[0]);
    await adapter.reconcile(client, retiredCatalog, "password");
    assert.equal(client.records.length, 1); assert.equal(client.records[0].id, original.id);
    assert.deepEqual(client.records[0].heartbeatHistory, original.heartbeatHistory);
    assert.equal(client.records[0].active, false);
    assert.deepEqual(client.writes.map(([event]) => event), ["pauseMonitor"]);
    client.writes = []; await adapter.reconcile(client, retiredCatalog, "password"); assert.deepEqual(client.writes, []);
});
test("unrecorded retirement and disabled authentication fail closed", async () => {
    const client = new Fake([{ ...adapter.projection(monitor), id: 1 }]);
    await assert.rejects(adapter.reconcile(client, { ...catalog, monitors: [] }, "password"), /unrecorded-retirement/); assert.equal(client.writes.length, 0);
    client.settings.disableAuth = true; await assert.rejects(adapter.reconcile(client, catalog, "password"), /authentication-disabled/);
});
test("monitor list subscribes before request and requires event plus ack", async () => {
    class Socket extends EventEmitter { emit(name, ...args) { if (name === "getMonitorList") { super.emit("monitorList", { 1: { id: 1 } }); args[0]({ ok: true }); return true; } return super.emit(name, ...args); } }
    const client = new adapter.NativeClient(new Socket(), 20); assert.deepEqual(await client.list(), { 1: { id: 1 } });
    client.socket.emit = () => true; await assert.rejects(client.list()); assert.equal(client.socket.listenerCount("monitorList"), 0);
});
test("JSON-query uses actual pinned native fields and prevents redirects", () => {
    const fields = adapter.projection({ ...monitor, kind: "json-query", expected: { statusCodes: [200], jsonPath: "data.value", value: "1" } });
    assert.equal(fields.jsonPath, "data.value"); assert.equal(fields.expectedValue, "1"); assert.equal(fields.jsonPathOperator, "=="); assert.equal(fields.maxredirects, 0);
});
test("Prometheus form requests use native body encoding and reject arbitrary headers", () => {
    const m = { ...monitor, kind: "json-query", target: { url: "http://prometheus.monitoring.svc:9090/api/v1/query", method: "POST", body: "query=vector%281%29", headers: { "Content-Type": "application/x-www-form-urlencoded" } }, expected: { statusCodes: [200], jsonPath: "data.value", value: "1" } };
    adapter.validate({ ...catalog, monitors: [m] });
    const fields = adapter.projection(m);
    assert.equal(fields.method, "POST"); assert.equal(fields.httpBodyEncoding, "form"); assert.equal(fields.body, "query=vector%281%29"); assert.deepEqual(JSON.parse(fields.headers), m.target.headers);
    assert.throws(() => adapter.validate({ ...catalog, monitors: [{ ...m, target: { ...m.target, headers: { Authorization: "secret" } } }] }), /invalid-headers/);
});
test("writer lease bounds contention and permits next cycle after release", async () => {
    const net = require("node:net");
    const holder = net.createServer(socket => socket.destroy());
    await new Promise(resolve => holder.listen(0, "127.0.0.1", resolve));
    const port = holder.address().port;
    try {
        await assert.rejects(adapter.acquireLease(port, 30), /writer-contention-timeout/);
        let acquired = false;
        const next = adapter.acquireLease(port, 1000).then(release => { acquired = true; return release; });
        await new Promise(resolve => setTimeout(resolve, 20));
        assert.equal(acquired, false, "contender cannot enter while current cycle holds lease");
        await new Promise(resolve => holder.close(resolve));
        const release = await next;
        assert.equal(acquired, true);
        await assert.rejects(adapter.acquireLease(port, 20), /writer-contention-timeout/);
        await release();
        const subsequent = await adapter.acquireLease(port, 100);
        await subsequent();
    } finally { holder.close(); }
});
test("verify is read-only and distinguishes observed target failure from missing evidence", async () => {
    const client = new Fake([{ ...adapter.projection(monitor), id: 1 }]);
    client.observations = new Map([[1, [1, 2, 3].map(id => ({ id, status: 1, time: new Date().toISOString() }))]]);
    let result = await adapter.verify(client, catalog); assert.equal(result.ok, true); assert.equal(result.healthy, true);
    client.observations.get(1)[2].status = 0;
    result = await adapter.verify(client, catalog); assert.equal(result.ok, true); assert.equal(result.healthy, false);
    client.observations.get(1).pop(); result = await adapter.verify(client, catalog); assert.equal(result.ok, false);
    assert.deepEqual(client.writes, []);
});
test("heartbeat collector preserves distinct historical/live samples before login", () => {
    const socket = new EventEmitter(); const client = new adapter.NativeClient(socket);
    socket.emit("heartbeatList", 1, [{ id: 1, time: "2026-11-17 01:00:00.000", status: 1 }, { id: 2, time: "2026-11-17 01:01:00.000", status: 1 }]);
    socket.emit("heartbeat", { time: "2026-11-17 01:01:00.000", monitorID: 1, status: 0 });
    socket.emit("heartbeat", { time: "2026-11-17 01:02:00.000", monitorID: 1, status: 1 });
    assert.deepEqual(client.observations.get(1).map(x => x.status), [1, 0, 1]);
});
test("acceptance refuses an already-active fixture without pausing it or touching other monitors", async () => {
    const client = new Fake([{ id: 1, description: adapter.ACCEPTANCE_MARKER, active: true }, { ...adapter.projection(monitor), id: 2 }]);
    await assert.rejects(adapter.acceptance(client), /acceptance-already-active/);
    assert.equal(client.records[0].active, true); assert.deepEqual(client.writes, []);
});
test("verify rejects stale or malformed observation timestamps without changing records", async () => {
    const client = new Fake([{ ...adapter.projection(monitor), id: 1 }]);
    client.observations = new Map([[1, [1, 2, 3].map(id => ({ id, status: 1, time: new Date(Date.now() - 300000).toISOString() }))]]);
    assert.equal((await adapter.verify(client, catalog)).ok, false);
    client.observations.get(1)[2].time = "invalid";
    assert.equal((await adapter.verify(client, catalog)).ok, false); assert.deepEqual(client.writes, []);
});
test("sample waits use real native timestamps, ignore prior observations and honor cancellation", async () => {
    const now = new Date().toISOString();
    const client = { observations: new Map([[7, [{ monitorID: 7, time: now, status: 1 }]]]) };
    const result = await adapter.waitForSamples(client, 7, 1, 1, 0, 1);
    assert.equal(result.samples.length, 1);
    await assert.rejects(adapter.waitForSamples(client, 7, 1, 1, now, 1000, () => true), /acceptance-interrupted/);
});


test("Prowlarr native ping requires JSON status OK without redirect or auth fallback", () => {
    const catalog = require("../../clusters/homelab/apps/uptime-kuma/monitors.json");
    const m = catalog.monitors.find(m => m.key === "prowlarr-http");
    const fields = adapter.projection(m);
    assert.equal(fields.type, "json-query"); assert.equal(fields.method, "GET");
    assert.equal(fields.url, "http://prowlarr.media.svc:9696/ping");
    assert.equal(fields.jsonPath, "status"); assert.equal(fields.expectedValue, "OK");
    assert.deepEqual(fields.accepted_statuscodes, ["200"]); assert.equal(fields.maxredirects, 0);
});
