#!/usr/bin/env node
"use strict";
// Version-bound to the pinned Kuma image; never install dependencies at runtime.
const fs = require("node:fs");
const path = require("node:path");
const crypto = require("node:crypto");
const net = require("node:net");
const http = require("node:http");
const { spawn } = require("node:child_process");
const PREFIX = "homelab-managed:uptime-kuma:v1:";
const ACCEPTANCE_MARKER = "homelab-acceptance:uptime-kuma:v1:loopback-json";
const JSON_HEALTH = '(status = "success" and $count(data.result) = 1 and data.result[0].value[1] = "1") ? "1" : "0"';
const sleep = ms => new Promise(resolve => setTimeout(resolve, ms));
class AdapterError extends Error {
    constructor(category) { super(category); this.category = category; }
}
function validate(catalog) {
    if (catalog.schemaVersion !== 1 || !Array.isArray(catalog.monitors) || !Array.isArray(catalog.apps)) throw new AdapterError("invalid-catalog");
    const keys = new Set();
    for (const m of catalog.monitors) {
        if (!/^[a-z0-9]+(?:-[a-z0-9]+)*$/.test(m.key) || keys.has(m.key) || typeof m.enabled !== "boolean" || !["http", "json-query", "tcp"].includes(m.kind)) throw new AdapterError("invalid-catalog");
        keys.add(m.key);
        if (!m.name || !m.meaning || !m.limitations || m.intervalSeconds !== 60 || m.timeoutSeconds !== 10 || m.retries !== 1) throw new AdapterError("invalid-catalog");
        if (m.kind !== "tcp") {
            const u = new URL(m.target.url);
            if (!["http:", "https:"].includes(u.protocol) || u.username || u.password || !m.expected.statusCodes.every(c => Number.isInteger(c) && c >= 200 && c < 300)) throw new AdapterError("invalid-target");
            if (m.target.method && !["GET", "POST"].includes(m.target.method)) throw new AdapterError("invalid-method");
            if (m.target.method === "POST" && (m.kind !== "json-query" || u.pathname !== "/api/v1/query" || !m.target.body?.startsWith("query="))) throw new AdapterError("invalid-query-request");
            if (m.target.headers && !same(m.target.headers, { "Content-Type": "application/x-www-form-urlencoded" })) throw new AdapterError("invalid-headers");
        }
    }
    return catalog;
}
function projection(m) {
    const result = {
        name: m.name, description: `${PREFIX}${m.key}\n${m.meaning}\nLimits: ${m.limitations}`,
        type: m.kind === "tcp" ? "port" : m.kind, interval: m.intervalSeconds,
        retryInterval: m.intervalSeconds, timeout: m.timeoutSeconds, maxretries: m.retries,
        active: m.enabled, accepted_statuscodes: (m.expected?.statusCodes || [200]).map(String),
        maxredirects: 0,
    };
    if (m.kind === "tcp") Object.assign(result, { hostname: m.target.hostname, port: m.target.port });
    else Object.assign(result, { url: m.target.url, method: m.target.method || "GET", body: m.target.body || null, headers: m.target.headers ? JSON.stringify(m.target.headers) : null, httpBodyEncoding: m.target.method === "POST" ? "form" : "json", ignoreTls: false });
    if (m.kind === "json-query") Object.assign(result, { jsonPath: m.expected.jsonPath, expectedValue: String(m.expected.value), jsonPathOperator: "==" });
    return result;
}
function keyOf(m) {
    const lines = (m.description || "").split("\n").filter(line => line.startsWith(PREFIX));
    if (lines.length > 1) throw new AdapterError("duplicate-ownership-marker");
    return lines.length ? lines[0].slice(PREFIX.length) : null;
}
function owned(list) {
    const result = new Map();
    for (const m of Object.values(list)) {
        const key = keyOf(m);
        if (key !== null) {
            if (!/^[a-z0-9]+(?:-[a-z0-9]+)*$/.test(key) || result.has(key)) throw new AdapterError("duplicate-owned-key");
            result.set(key, m);
        }
    }
    return result;
}
function same(a, b) { return JSON.stringify(a) === JSON.stringify(b); }
class NativeClient {
    constructor(socket, deadline = 15000) {
        this.socket = socket; this.deadline = deadline; this.observations = new Map();
        const remember = (id, samples) => {
            const known = new Map((this.observations.get(Number(id)) || []).map(item => [item.time, item]));
            for (const item of samples) known.set(item.time, item);
            this.observations.set(Number(id), [...known.values()].sort((a, b) => heartbeatTime(a.time) - heartbeatTime(b.time)).slice(-100));
        };
        socket.on("heartbeatList", (id, samples) => remember(id, samples));
        socket.on("heartbeat", sample => remember(sample.monitorID, [sample]));
    }
    request(event, ...args) {
        return new Promise((resolve, reject) => {
            const timer = setTimeout(() => reject(new AdapterError(`ack-timeout-${event}`)), this.deadline);
            this.socket.emit(event, ...args, response => {
                clearTimeout(timer);
                if (event === "needSetup" && typeof response === "boolean") resolve(response);
                else if (response?.ok === true) resolve(response);
                else reject(new AdapterError(`rejected-${event}`));
            });
        });
    }
    async list() {
        let listener;
        let timer;
        const event = new Promise((resolve, reject) => {
            listener = value => { clearTimeout(timer); resolve(value); };
            this.socket.once("monitorList", listener);
            timer = setTimeout(() => reject(new AdapterError("monitor-list-timeout")), this.deadline);
        });
        try {
            const [, list] = await Promise.all([this.request("getMonitorList"), event]);
            return list;
        } finally { clearTimeout(timer); this.socket.off("monitorList", listener); }
    }
    close() { this.socket.disconnect(); }
}
async function connect(url, timeout = 90000) {
    const target = new URL(url);
    if (target.hostname !== "127.0.0.1" || target.protocol !== "http:") throw new AdapterError("non-loopback-api");
    const { io } = require("/app/node_modules/socket.io-client");
    const socket = io(url, { transports: ["websocket"], reconnection: true, reconnectionDelay: 500, timeout: 3000, autoConnect: false });
    try {
        await new Promise((resolve, reject) => {
            const timer = setTimeout(() => reject(new AdapterError("connection-timeout")), timeout);
            // Kuma awaits sendInfo before installing request handlers. Transport
            // connect alone can race those handlers and lose the first request.
            socket.once("info", () => { clearTimeout(timer); setImmediate(resolve); });
            socket.connect();
        });
        return new NativeClient(socket);
    } catch (e) { socket.disconnect(); throw e; }
}
async function login(client, password, allowSetup = false) {
    const needsSetup = await client.request("needSetup");
    if (needsSetup) {
        if (!allowSetup) throw new AdapterError("owner-missing");
        await client.request("setup", "admin", password);
    }
    await client.request("login", { username: "admin", password });
}
async function retention(client, password) {
    const { data } = await client.request("getSettings");
    if (data.disableAuth) throw new AdapterError("authentication-disabled");
    if (Number(data.keepDataPeriodDays) !== 30) {
        await client.request("setSettings", { ...data, keepDataPeriodDays: 30 }, password);
        return 1;
    }
    return 0;
}
async function reconcile(client, catalog, password) {
    validate(catalog);
    let existing = owned(await client.list());
    const desiredKeys = new Set(catalog.monitors.map(m => m.key));
    // Removal must be an explicit disabled catalog record, never an implicit delete.
    if ([...existing.keys()].some(key => !desiredKeys.has(key))) throw new AdapterError("unrecorded-retirement");
    const count = { managed: catalog.monitors.length, created: 0, changed: 0, paused: 0, resumed: 0, settings: 0 };
    // Fetch and validate every owned record before any mutation, including settings.
    const records = new Map();
    for (const [key, item] of existing) {
        const { monitor } = await client.request("getMonitor", item.id);
        if (keyOf(monitor) !== key) throw new AdapterError("ownership-changed");
        records.set(key, monitor);
    }
    count.settings = await retention(client, password);
    for (const m of catalog.monitors) {
        const desired = projection(m);
        let current = records.get(m.key);
        if (!current) {
            try {
                await client.request("add", { ...desired, notificationIDList: {}, parent: null, upsideDown: false, expiryNotification: false, conditions: [], kafkaProducerBrokers: [], kafkaProducerSaslOptions: {}, rabbitmqNodes: [] });
                count.created++;
            } catch (e) {
                // The server may have committed before an acknowledgement was lost.
                existing = owned(await client.list());
                const found = existing.get(m.key);
                if (!found) throw e; // Never blindly retry an uncertain add.
                current = (await client.request("getMonitor", found.id)).monitor;
                if (keyOf(current) !== m.key) throw new AdapterError("ownership-changed");
                count.created++;
            }
            if (!current) continue;
        }
        const changes = Object.entries(desired).some(([key, value]) => key !== "active" && !same(current[key], value));
        if (changes) {
            await client.request("editMonitor", { ...current, ...desired });
            count.changed++;
        }
        if (Boolean(current.active) !== desired.active) {
            await client.request(desired.active ? "resumeMonitor" : "pauseMonitor", current.id);
            count[desired.active ? "resumed" : "paused"]++;
        }
    }
    return count;
}
function options(args) {
    const result = { mode: args.shift(), catalog: "/config/monitors.json", passwordFile: "/secret/admin-password", dataDir: "/app/data", statusFile: "/status/reconcile.json", url: "http://127.0.0.1:3001" };
    const names = { "--catalog": "catalog", "--password-file": "passwordFile", "--data-dir": "dataDir", "--status-file": "statusFile", "--url": "url" };
    while (args.length) { const key = names[args.shift()]; if (!key || !args.length) throw new AdapterError("invalid-arguments"); result[key] = args.shift(); }
    return result;
}
function passwordFrom(file) {
    const password = fs.readFileSync(file, "utf8").replace(/\r?\n$/, "");
    if (password.length < 12) throw new AdapterError("invalid-credential-file");
    return password;
}
function status(file, values) {
    fs.mkdirSync(path.dirname(file), { recursive: true });
    let old = {};
    try { old = JSON.parse(fs.readFileSync(file, "utf8")); } catch { /* First run. */ }
    const next = { ...old, ...values, attemptedAt: new Date().toISOString() };
    fs.writeFileSync(`${file}.tmp`, JSON.stringify(next), { mode: 0o600 });
    fs.renameSync(`${file}.tmp`, file);
}
async function bootstrap(opts, password) {
    fs.mkdirSync(opts.dataDir, { recursive: true });
    const config = path.join(opts.dataDir, "db-config.json");
    if (!fs.existsSync(config)) {
        if (fs.readdirSync(opts.dataDir).length) throw new AdapterError("nonempty-data-without-config");
        fs.writeFileSync(config, JSON.stringify({ type: "sqlite" }), { flag: "wx", mode: 0o600 });
    } else if (JSON.parse(fs.readFileSync(config, "utf8")).type !== "sqlite") throw new AdapterError("unexpected-database-config");
    const port = new URL(opts.url).port || "3001";
    const server = spawn(process.execPath, ["/app/server/server.js", "--host=127.0.0.1", `--port=${port}`, `--data-dir=${opts.dataDir}`], { cwd: "/app", stdio: "ignore" });
    let stopped = false;
    const exit = new Promise(resolve => server.once("exit", () => { stopped = true; resolve(); }));
    server.once("error", () => { stopped = true; });
    let client;
    try {
        client = await connect(opts.url);
        await login(client, password, true);
        await retention(client, password);
    } finally {
        client?.close();
        if (!stopped) server.kill("SIGTERM");
        let shutdownTimer;
        try { await Promise.race([exit, new Promise(resolve => { shutdownTimer = setTimeout(resolve, 30000); })]); }
        finally { clearTimeout(shutdownTimer); }
        if (!stopped) { server.kill("SIGKILL"); await exit; throw new AdapterError("server-shutdown-timeout"); }
    }
}
function heartbeatTime(value) {
    return Date.parse(value.includes("T") ? value : value.replace(" ", "T") + "Z");
}
async function verify(client, catalog) {
    validate(catalog);
    const records = owned(await client.list());
    const monitors = [];
    for (const desired of catalog.monitors) {
        const item = records.get(desired.key);
        const record = item ? (await client.request("getMonitor", item.id)).monitor : null;
        const fields = projection(desired);
        const defined = Boolean(record) && Object.entries(fields).every(([key, value]) => key === "active" ? Boolean(record.active) === value : same(record[key], value));
        const samples = (client.observations.get(Number(item?.id)) || []).slice(-3);
        const recent = samples.length === 3 && samples.every(sample => Number.isFinite(heartbeatTime(sample.time)) && Date.now() - heartbeatTime(sample.time) <= 260000);
        monitors.push({ key: desired.key, id: item?.id || null, enabled: desired.enabled, defined,
            observed: !desired.enabled || recent, healthy: !desired.enabled || (recent && samples.every(sample => sample.status === 1)),
            observations: samples.map(sample => ({ status: sample.status, time: sample.time })) });
    }
    const extra = [...records.keys()].filter(key => !catalog.monitors.some(m => m.key === key));
    return { ok: extra.length === 0 && monitors.every(m => m.defined && m.observed), healthy: monitors.every(m => m.healthy), extra, monitors };
}
async function waitForSamples(client, id, desiredStatus, count, afterId, timeout = 180000, cancelled = () => false) {
    const started = Date.now();
    while (Date.now() - started <= timeout) {
        if (cancelled()) throw new AdapterError("acceptance-interrupted");
        const after = typeof afterId === "number" ? afterId : heartbeatTime(afterId);
        const samples = (client.observations.get(Number(id)) || []).filter(item => heartbeatTime(item.time) > after);
        const matching = samples.slice(-count);
        if (matching.length === count && matching.every(item => item.status === desiredStatus)) return { elapsedMs: Date.now() - started, samples: matching };
        await sleep(250);
    }
    throw new AdapterError(`observation-timeout-${desiredStatus}`);
}
async function acceptance(client) {
    // Fixed loopback target and separate ownership domain: never alter app monitors.
    const release = await acquireLease();
    let healthy = true;
    let interrupted = false;
    const cancel = () => { interrupted = true; };
    process.once("SIGTERM", cancel); process.once("SIGINT", cancel);
    let fixture;
    let id;
    let original;
    try {
        fixture = http.createServer((request, response) => {
            let body = "";
            request.on("data", chunk => { body += chunk; if (body.length > 4096) request.destroy(); });
            request.on("end", () => {
                if (request.method !== "POST" || request.url !== "/api/v1/query" || body !== "query=vector%281%29") { response.writeHead(400).end(); return; }
                response.writeHead(200, { "Content-Type": "application/json" });
                response.end(JSON.stringify({ status: "success", data: { result: [{ value: [Date.now() / 1000, healthy ? "1" : "0"] }] } }));
            });
        });
        await new Promise((resolve, reject) => { fixture.once("error", () => reject(new AdapterError("acceptance-port-unavailable"))); fixture.listen(3901, "127.0.0.1", resolve); });
        const listed = Object.values(await client.list());
        const matches = listed.filter(m => m.description === ACCEPTANCE_MARKER);
        if (matches.length > 1) throw new AdapterError("duplicate-acceptance-key");
        original = new Map();
        for (const m of listed.filter(m => m.description !== ACCEPTANCE_MARKER)) original.set(m.id, (await client.request("getMonitor", m.id)).monitor);
        const fields = { ...projection({ key: "acceptance", name: "Homelab acceptance (disposable)", kind: "json-query", enabled: false,
            target: { url: "http://127.0.0.1:3901/api/v1/query", method: "POST", body: "query=vector%281%29", headers: { "Content-Type": "application/x-www-form-urlencoded" } },
            expected: { statusCodes: [200], jsonPath: JSON_HEALTH, value: "1" }, intervalSeconds: 60, timeoutSeconds: 10, retries: 1,
            meaning: "Controlled localhost acceptance", limitations: "Not app coverage" }), description: ACCEPTANCE_MARKER };
        if (matches.length) {
            const record = (await client.request("getMonitor", matches[0].id)).monitor;
            if (record.active) throw new AdapterError("acceptance-already-active");
            id = matches[0].id;
            await client.request("editMonitor", { ...record, ...fields });
        } else {
            try { id = (await client.request("add", { ...fields, notificationIDList: {}, parent: null, conditions: [], kafkaProducerBrokers: [], kafkaProducerSaslOptions: {}, rabbitmqNodes: [] })).monitorID; }
            catch (error) {
                const found = Object.values(await client.list()).filter(m => m.description === ACCEPTANCE_MARKER);
                if (found.length !== 1) throw error;
                id = found[0].id;
            }
        }
        const previous = (client.observations.get(Number(id)) || []).at(-1)?.time || 0;
        await client.request("resumeMonitor", id);
        const up = await waitForSamples(client, id, 1, 3, previous, 180000, () => interrupted);
        healthy = false;
        const down = await waitForSamples(client, id, 0, 1, up.samples.at(-1).time, 180000, () => interrupted);
        healthy = true;
        const recovered = await waitForSamples(client, id, 1, 1, down.samples.at(-1).time, 180000, () => interrupted);
        return { ok: true, monitorID: id, initialObservations: up.samples.length, downMs: down.elapsedMs, recoveryMs: recovered.elapsedMs };
    } finally {
        let failure;
        try {
            if (id !== undefined) await client.request("pauseMonitor", id);
            if (original) {
                const current = Object.values(await client.list()).filter(m => m.description !== ACCEPTANCE_MARKER);
                if (current.length !== original.size) throw new AdapterError("acceptance-other-monitors-changed");
                for (const m of current) if (!same((await client.request("getMonitor", m.id)).monitor, original.get(m.id))) throw new AdapterError("acceptance-other-monitors-changed");
            }
        } catch (error) { failure = error; }
        if (fixture?.listening) await new Promise(resolve => fixture.close(resolve));
        await release();
        process.off("SIGTERM", cancel); process.off("SIGINT", cancel);
        if (failure) throw failure;
    }
}
async function acquireLease(port = 3002, timeout = 120000) {
    const deadline = Date.now() + timeout;
    for (;;) {
        // Kernel-owned loopback lease is released even if the process crashes.
        const lease = net.createServer(socket => socket.destroy());
        try {
            await new Promise((resolve, reject) => {
                lease.once("error", reject);
                lease.listen(port, "127.0.0.1", resolve);
            });
            return () => new Promise(resolve => lease.close(resolve));
        } catch (error) {
            lease.close();
            if (error.code !== "EADDRINUSE") throw new AdapterError("writer-lease-failed");
            if (Date.now() >= deadline) throw new AdapterError("writer-contention-timeout");
            await sleep(Math.min(100, Math.max(1, deadline - Date.now())));
        }
    }
}
async function run(opts) {
    if (opts.mode === "health") {
        const state = JSON.parse(fs.readFileSync(opts.statusFile, "utf8"));
        if (!state.ok || !Number.isFinite(Date.parse(state.lastSuccess)) || Date.now() - Date.parse(state.lastSuccess) > 660000) throw new AdapterError("reconciliation-unhealthy");
        return;
    }
    const password = passwordFrom(opts.passwordFile);
    if (opts.mode === "bootstrap") return bootstrap(opts, password);
    if (["verify", "acceptance"].includes(opts.mode)) {
        const client = await connect(opts.url);
        try {
            await login(client, password);
            const result = opts.mode === "acceptance" ? await acceptance(client) : await verify(client, JSON.parse(fs.readFileSync(opts.catalog, "utf8")));
            console.log(JSON.stringify(result));
            if (!result.ok) throw new AdapterError("verification-incomplete");
            return result;
        } finally { client.close(); }
    }
    if (!["once", "watch"].includes(opts.mode)) throw new AdapterError("invalid-mode");
    fs.mkdirSync(path.dirname(opts.statusFile), { recursive: true });
    let stopping = false;
    const stop = () => { stopping = true; };
    process.once("SIGTERM", stop); process.once("SIGINT", stop);
    try {
        do {
            let client;
            let release;
            try {
                release = await acquireLease();
                const raw = fs.readFileSync(opts.catalog, "utf8");
                const catalog = validate(JSON.parse(raw));
                client = await connect(opts.url);
                await login(client, password);
                const counts = await reconcile(client, catalog, password);
                status(opts.statusFile, { ok: true, lastSuccess: new Date().toISOString(), catalogHash: crypto.createHash("sha256").update(raw).digest("hex"), counts, error: null });
                console.log(JSON.stringify({ ok: true, ...counts }));
            } catch (e) {
                // A contender cannot overwrite the active writer's status.
                if (release) status(opts.statusFile, { ok: false, error: e.category || "adapter-failure" });
                if (opts.mode === "once") throw e;
                console.error(JSON.stringify({ ok: false, error: e.category || "adapter-failure" }));
            } finally { client?.close(); if (release) await release(); }
            if (opts.mode === "once") break;
            for (let i = 0; i < 300 && !stopping; i++) await sleep(1000);
        } while (!stopping);
    } finally { process.off("SIGTERM", stop); process.off("SIGINT", stop); }
}
module.exports = { AdapterError, NativeClient, validate, projection, keyOf, owned, login, retention, reconcile, options, bootstrap, connect, acquireLease, verify, acceptance, waitForSamples, heartbeatTime, JSON_HEALTH, ACCEPTANCE_MARKER, run };
if (require.main === module) run(options(process.argv.slice(2))).catch(e => { console.error(JSON.stringify({ ok: false, error: e.category || "adapter-failure" })); process.exitCode = 1; });
