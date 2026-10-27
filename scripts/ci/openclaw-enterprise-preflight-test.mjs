#!/usr/bin/env node
// Exercise the actual preflight entrypoint with only its Kubernetes and file reads mocked.

import assert from "node:assert/strict";
import { createHash } from "node:crypto";
import { EventEmitter } from "node:events";
import { readFileSync } from "node:fs";
import { mock } from "node:test";

const root = new URL("../../", import.meta.url);
const app = new URL("clusters/homelab/apps/openclaw-enterprise/", root);
const candidate = readFileSync(new URL("installation.yaml", app));
const check = readFileSync(new URL("check-installation.mjs", app));
const sha = createHash("sha256").update(candidate).digest("hex");
const terminal = { status: { conditions: [{ type: "Failed", status: "True" }] } };

async function preflight(scenario, index) {
  const original = {
    env: { ...process.env },
    stdout: process.stdout.write,
    stderr: process.stderr.write,
    exitCode: process.exitCode,
  };
  const output = [];
  process.stdout.write = (text) => { output.push(String(text)); return true; };
  process.stderr.write = (text) => { output.push(String(text)); return true; };
  process.exitCode = 0;
  Object.assign(process.env, {
    OCE_INSTALLATION_SECRET: `occ-installation-startup-${sha.slice(0, 32)}`,
    OCE_INSTALLATION_SHA256: scenario.candidateSha ?? sha,
    OCE_POSTGRES_CLUSTER_IP: "10.96.0.51",
    OCE_BOOTSTRAP_ADMIN_EMAIL: "owner@example.test",
    KUBERNETES_SERVICE_HOST: "127.0.0.1",
    KUBERNETES_SERVICE_PORT: "6443",
  });
  const fsMock = mock.module("node:fs/promises", { namedExports: {
    readFile: async (path) => {
      if (path === "/var/run/secrets/kubernetes.io/serviceaccount/token") return "fixture-token";
      if (path === "/var/run/secrets/kubernetes.io/serviceaccount/ca.crt") return Buffer.from("fixture-ca");
      if (path === "/scripts/check-installation.mjs") return check;
      if (path === "/etc/openclaw/installation/installation.yaml") return candidate;
      throw new Error(`unexpected read: ${path}`);
    },
  } });
  const childMock = mock.module("node:child_process", { namedExports: {
    spawnSync: () => ({ status: 0, stdout: "installation-startup-ready\n" }),
  } });
  const httpsMock = mock.module("node:https", { defaultExport: {
    request: (options, callback) => {
      const request = new EventEmitter();
      request.end = () => queueMicrotask(() => {
        const path = options.path;
        let value;
        if (path.includes("/secrets/")) {
          const name = path.split("/").at(-1);
          value = { metadata: { name }, immutable: true, data: {
            "installation.yaml": candidate.toString("base64"),
            secret: "Zml4dHVyZQ==", "application-url": "Zml4dHVyZQ==",
            "migration-url": "Zml4dHVyZQ==", "tls.crt": "Zml4dHVyZQ==",
            occ: "Zml4dHVyZQ==",
          } };
        } else if (path.includes("/persistentvolumeclaims/")) {
          value = { status: { phase: "Bound" }, spec: {
            storageClassName: "openclaw-enterprise-bootstrap-local" } };
        } else if (path.includes("/services/")) {
          value = { spec: { clusterIP: "10.96.0.51" } };
        } else if (path.includes("/endpointslices?")) {
          value = { items: [{ endpoints: [{ conditions: { ready: true }, addresses: ["10.1.0.8"] }] }] };
        } else if (path.includes("/jobs/oce-initialization")) {
          value = scenario.job;
        } else if (path.includes("/pods?")) {
          value = { items: scenario.pods ?? [] };
        } else {
          throw new Error(`unexpected Kubernetes read: ${path}`);
        }
        const response = new EventEmitter();
        response.statusCode = value === null ? 404 : 200;
        response.setEncoding = () => {};
        callback(response);
        response.emit("data", JSON.stringify(value));
        response.emit("end");
      });
      request.destroy = (error) => request.emit("error", error);
      return request;
    },
  } });
  try {
    await import(`${new URL("preflight.mjs", app)}?fixture=${index}`);
    await new Promise((resolve) => setImmediate(resolve));
    assert.equal(process.exitCode, scenario.error ? 1 : 0, scenario.name);
    assert.match(output.join(""), scenario.error ?? /openclaw-enterprise-preflight-ready/, scenario.name);
  } finally {
    httpsMock.restore();
    childMock.restore();
    fsMock.restore();
    process.stdout.write = original.stdout;
    process.stderr.write = original.stderr;
    process.exitCode = original.exitCode;
    process.env = original.env;
  }
}

const scenarios = [
  { name: "first install", job: null },
  { name: "terminal failed attempt can retry", job: terminal, pods: [{ status: { phase: "Failed" } }] },
  { name: "active prior Job", job: { status: { active: 1 } }, error: /previous initialization Job is not terminal/ },
  { name: "stale prior Job", job: { status: { active: 0 } }, error: /previous initialization Job is not terminal/ },
  { name: "active prior Pod", job: terminal, pods: [{ status: { phase: "Running" } }],
    error: /previous initialization Pod is not terminal/ },
  { name: "changed candidate", job: null, candidateSha: "0".repeat(64),
    error: /mounted Installation bytes differ from reviewed checksum/ },
];
for (const [index, scenario] of scenarios.entries()) await preflight(scenario, index);
process.stdout.write(`${scenarios.length} preflight fixtures passed\n`);
