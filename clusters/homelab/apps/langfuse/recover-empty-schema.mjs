#!/usr/bin/env node
// One-shot repair for the reviewed Langfuse ClickHouse empty-schema incident.
// It deliberately has no Kubernetes API access: the recovery Job's phase-1
// fence must prove every Langfuse web/worker pod is absent before this starts.
import { spawnSync } from "node:child_process";
import { createHash, randomUUID } from "node:crypto";
import {
  chmodSync,
  existsSync,
  linkSync,
  lstatSync,
  mkdirSync,
  openSync,
  readFileSync,
  readdirSync,
  renameSync,
  rmdirSync,
  statSync,
  unlinkSync,
  writeFileSync,
  fsyncSync,
  closeSync,
} from "node:fs";
import { request } from "node:http";
import { basename, join, relative } from "node:path";
import { fileURLToPath, pathToFileURL } from "node:url";

export const IMAGE = "docker.io/langfuse/langfuse:4.35.0@sha256:a5d8d2457702ab7e051bc0788d73871970caebd10aae6635e87cfb736e4067cd";
export const HTTP_HOST = "langfuse-clickhouse.langfuse.svc.cluster.local";
export const HTTP_PORT = 8123;
export const NATIVE_URL = "clickhouse://langfuse-clickhouse.langfuse.svc.cluster.local:9000";
export const DATABASE = "default";
export const USER = "default";
export const CLICKHOUSE_VERSION = "26.4.5.143";
export const PASSWORD_FILE = "/run/secrets/langfuse/clickhouse-password";
export const RECOVERY_ROOT = "/recovery";
export const MIGRATE = "/usr/bin/migrate";
export const MIGRATIONS = "/app/packages/shared/clickhouse/migrations/unclustered";
// Reviewed phase-1 fence revision; receipts bind recovery to that fence.
export const FENCE_REVISION = "712699ebfbf381a5f85cdb42fef0605a88c39c99";

const EXPECTED_OBJECTS = [
  ["analytics_observations", "View"],
  ["analytics_scores", "View"],
  ["analytics_traces", "View"],
  ["blob_storage_file_log", "ReplacingMergeTree"],
  ["dataset_run_items_rmt", "ReplacingMergeTree"],
  ["events_core", "ReplacingMergeTree"],
  ["events_core_mv", "MaterializedView"],
  ["events_full", "ReplacingMergeTree"],
  ["observations", "ReplacingMergeTree"],
  ["observations_batch_staging", "ReplacingMergeTree"],
  ["observations_pid_tid_sorting", "ReplacingMergeTree"],
  ["schema_migrations", "MergeTree"],
  ["scores", "ReplacingMergeTree"],
  ["traces", "ReplacingMergeTree"],
];

const INGESTION_TABLES = [
  "blob_storage_file_log",
  "dataset_run_items_rmt",
  "events_core",
  "events_full",
  "observations",
  "observations_batch_staging",
  "observations_pid_tid_sorting",
  "scores",
  "traces",
];

const LOCK_NAME = ".langfuse-empty-schema-recovery.lock";

const REQUIRED_47_COLUMNS = [
  ["events_core", "evaluator_execution_is_test", "Bool", "DEFAULT", "has(metadata_names, 'evaluator_test') AND (arrayElement(metadata_values, indexOf(metadata_names, 'evaluator_test')) = 'true')"],
  ["events_core", "evaluator_id", "String", "DEFAULT", "arrayElement(metadata_values, indexOf(metadata_names, 'evaluator_id'))"],
  ["events_core", "evaluation_rule_id", "String", "DEFAULT", "if(notEmpty(arrayElement(metadata_values, indexOf(metadata_names, 'evaluation_rule_id'))), arrayElement(metadata_values, indexOf(metadata_names, 'evaluation_rule_id')), arrayElement(metadata_values, indexOf(metadata_names, 'job_configuration_id')))"],
  ["events_full", "evaluator_execution_is_test", "Bool", "DEFAULT", "has(metadata_names, 'evaluator_test') AND (arrayElement(metadata_values, indexOf(metadata_names, 'evaluator_test')) = 'true')"],
  ["events_full", "evaluator_id", "String", "DEFAULT", "arrayElement(metadata_values, indexOf(metadata_names, 'evaluator_id'))"],
  ["events_full", "evaluation_rule_id", "String", "DEFAULT", "if(notEmpty(arrayElement(metadata_values, indexOf(metadata_names, 'evaluation_rule_id'))), arrayElement(metadata_values, indexOf(metadata_names, 'evaluation_rule_id')), arrayElement(metadata_values, indexOf(metadata_names, 'job_configuration_id')))"],
  ["scores", "evaluator_id", "String", "DEFAULT", "metadata['evaluator_id']"],
  ["scores", "evaluation_rule_id", "String", "DEFAULT", "if(notEmpty(metadata['evaluation_rule_id']), metadata['evaluation_rule_id'], metadata['job_configuration_id'])"],
];

const REQUIRED_47_INDICES = [
  ["events_core", "idx_evaluation_rule_id", "bloom_filter", "bloom_filter(0.01)", "evaluation_rule_id", "1"],
  ["events_core", "idx_evaluator_id", "bloom_filter", "bloom_filter(0.01)", "evaluator_id", "1"],
  ["scores", "idx_evaluation_rule_id", "bloom_filter", "bloom_filter(0.001)", "evaluation_rule_id", "1"],
  ["scores", "idx_evaluator_id", "bloom_filter", "bloom_filter(0.001)", "evaluator_id", "1"],
];

const SOURCE_SCRIPT_SHA256 = sha256(readFileSync(fileURLToPath(import.meta.url)));
const CONFIG_SHA256 = sha256(JSON.stringify({
  image: IMAGE,
  http: `http://${HTTP_HOST}:${HTTP_PORT}`,
  native: NATIVE_URL,
  database: DATABASE,
  user: USER,
  clickhouseVersion: CLICKHOUSE_VERSION,
  migrate: MIGRATE,
  migrations: MIGRATIONS,
  objects: EXPECTED_OBJECTS,
  sourceScriptSha256: SOURCE_SCRIPT_SHA256,
  fenceRevision: FENCE_REVISION,
}));

class RecoveryError extends Error {
  constructor(code) {
    super(code);
    this.code = code;
  }
}

function fail(code) {
  throw new RecoveryError(code);
}

function asBuffer(value) {
  return Buffer.isBuffer(value) ? value : Buffer.from(String(value), "utf8");
}

function sha256(value) {
  return createHash("sha256").update(asBuffer(value)).digest("hex");
}

function stableJson(value) {
  return JSON.stringify(value);
}

function rows(value) {
  const text = asBuffer(value).toString("utf8");
  if (text === "") return [];
  const lines = text.endsWith("\n") ? text.slice(0, -1).split("\n") : text.split("\n");
  return lines.map((line) => line.split("\t"));
}

function scalar(value) {
  const parsed = rows(value);
  if (parsed.length !== 1 || parsed[0].length !== 1) fail("unexpected-scalar");
  return parsed[0][0];
}

function assertMode(path, expected) {
  if ((statSync(path).mode & 0o777) !== expected) fail("unsafe-artifact-mode");
}

function privateDirectory(path) {
  mkdirSync(path, { mode: 0o700 });
  chmodSync(path, 0o700);
  assertMode(path, 0o700);
}

function privateFile(path, content, flag = "wx") {
  writeFileSync(path, content, { encoding: "utf8", mode: 0o600, flag });
  chmodSync(path, 0o600);
  assertMode(path, 0o600);
  const fd = openSync(path, "r");
  try {
    fsyncSync(fd);
  } finally {
    closeSync(fd);
  }
}

function appendPrivate(path, content) {
  const fd = openSync(path, "a", 0o600);
  try {
    writeFileSync(fd, content);
    fsyncSync(fd);
  } finally {
    closeSync(fd);
  }
  chmodSync(path, 0o600);
  assertMode(path, 0o600);
}

function safeChild(parent, child) {
  if (child === "" || child.startsWith("/")) fail("unsafe-artifact-path");
  const path = join(parent, child);
  const childPath = relative(parent, path);
  if (childPath === "" || childPath === ".." || childPath.startsWith(`..${process.platform === "win32" ? "\\" : "/"}`)) fail("unsafe-artifact-path");
  return path;
}

export function fixedConfig() {
  if (!/^[0-9a-f]{40}$/.test(FENCE_REVISION)) fail("fence-revision-unpinned");
  return {
    image: IMAGE,
    configSha256: CONFIG_SHA256,
    sourceScriptSha256: SOURCE_SCRIPT_SHA256,
    fenceRevision: FENCE_REVISION,
    clickhouseVersion: CLICKHOUSE_VERSION,
  };
}

function readPassword(path = PASSWORD_FILE) {
  const raw = readFileSync(path, "utf8").replace(/\r?\n$/, "");
  if (raw === "" || /[\r\n]/.test(raw)) fail("invalid-password-file");
  return raw;
}

export function createClickHouseQuery(password) {
  return async (sql) => new Promise((resolve, reject) => {
    const body = Buffer.from(sql, "utf8");
    const req = request({
      host: HTTP_HOST,
      port: HTTP_PORT,
      path: `/?database=${DATABASE}&wait_end_of_query=1&readonly=1`,
      method: "POST",
      headers: {
        authorization: `Basic ${Buffer.from(`${USER}:${password}`, "utf8").toString("base64")}`,
        "content-type": "text/plain; charset=utf-8",
        "content-length": body.length,
      },
      timeout: 15_000,
    }, (res) => {
      const chunks = [];
      let size = 0;
      res.on("data", (chunk) => {
        size += chunk.length;
        if (size > 64 * 1024 * 1024) {
          req.destroy();
          return;
        }
        chunks.push(chunk);
      });
      res.on("end", () => {
        if (res.statusCode !== 200 || res.headers["x-clickhouse-exception-code"]) {
          reject(new RecoveryError("clickhouse-query-failed"));
          return;
        }
        resolve(Buffer.concat(chunks));
      });
    });
    req.on("timeout", () => req.destroy(new RecoveryError("clickhouse-query-timeout")));
    req.on("error", () => reject(new RecoveryError("clickhouse-query-failed")));
    req.end(body);
  });
}

function querySql() {
  return {
    identity: "SELECT currentDatabase(), version() FORMAT TSVRaw",
    migrations: "SELECT version, dirty, sequence FROM default.schema_migrations ORDER BY sequence FORMAT TSVRaw",
    inventory: "SELECT name, engine FROM system.tables WHERE database = 'default' ORDER BY name FORMAT TSVRaw",
    activeMigration: `SELECT count() FROM system.processes WHERE query_id != currentQueryID() AND (query_kind = 'Alter' OR positionCaseInsensitive(query, 'schema_migrations') > 0 OR (query_kind IN ('Create', 'Drop', 'Rename', 'Truncate') AND current_database = 'default')) FORMAT TSVRaw`,
    nonRead: "SELECT count() FROM system.processes WHERE query_id != currentQueryID() AND query_kind NOT IN ('Select', 'Show', 'Describe', 'Explain', 'Exists') FORMAT TSVRaw",
    partialColumns: "SELECT table, name, type, default_kind, default_expression FROM system.columns WHERE database = 'default' AND name IN ('evaluator_id', 'evaluation_rule_id', 'evaluator_execution_is_test') AND table IN ('events_full', 'events_core', 'scores') ORDER BY table, name FORMAT TSVRaw",
    partialIndices: "SELECT table, name FROM system.data_skipping_indices WHERE database = 'default' AND name IN ('idx_evaluator_id', 'idx_evaluation_rule_id') AND table IN ('events_core', 'scores') ORDER BY table, name FORMAT TSVRaw",
    requiredColumns: "SELECT table, name, type, default_kind, default_expression FROM system.columns WHERE database = 'default' AND name IN ('evaluator_id', 'evaluation_rule_id', 'evaluator_execution_is_test') AND table IN ('events_full', 'events_core', 'scores') ORDER BY table, name FORMAT TSVRaw",
    requiredIndices: "SELECT table, name, type, type_full, expr, granularity FROM system.data_skipping_indices WHERE database = 'default' AND name IN ('idx_evaluator_id', 'idx_evaluation_rule_id') AND table IN ('events_core', 'scores') ORDER BY table, name FORMAT TSVRaw",
  };
}

function countSql(table) {
  return `SELECT count() FROM default.\`${table}\` FORMAT TSVRaw`;
}

function showObjectSql(name) {
  return `SHOW CREATE TABLE default.\`${name}\` FORMAT TSVRaw`;
}

function assertRows(actual, expected, code) {
  if (stableJson(actual) !== stableJson(expected)) fail(code);
}

function normalizedSql(value) {
  return value.replace(/\s+/g, " ").trim();
}

function assertSemanticRows(actual, expected, code) {
  const normalized = actual.map((row) => row.map((field, index) => index === row.length - 1 ? normalizedSql(field) : field));
  const wanted = expected.map((row) => row.map((field, index) => index === row.length - 1 ? normalizedSql(field) : field));
  assertRows(normalized, wanted, code);
}

function assertZero(value, code) {
  if (scalar(value) !== "0") fail(code);
}

function migrationRows(raw) {
  const parsed = rows(raw);
  if (parsed.length < 2 || parsed.some((row) => row.length !== 3 || !/^\d+$/.test(row[0]) || !/^[01]$/.test(row[1]) || !/^\d+$/.test(row[2]))) {
    fail("invalid-migration-history");
  }
  return parsed;
}

function assertInitialHistory(history) {
  const latest = history.at(-1);
  const previous = history.at(-2);
  if (latest[0] !== "47" || latest[1] !== "1" || previous[0] !== "46" || previous[1] !== "0") fail("unexpected-initial-migration-state");
  if (history.some(([version]) => BigInt(version) > 47n)) fail("unexpected-initial-migration-state");
  assertIncreasingSequences(history, "unexpected-initial-migration-state");
}

function assertIncreasingSequences(history, code) {
  for (let index = 1; index < history.length; index++) {
    if (BigInt(history[index][2]) <= BigInt(history[index - 1][2])) fail(code);
  }
}

function assertForcedHistory(history, before) {
  const latest = history.at(-1);
  if (!before || history.length !== before.length + 1 || stableJson(history.slice(0, -1)) !== stableJson(before) || latest[0] !== "46" || latest[1] !== "0") fail("force-46-did-not-converge");
  assertIncreasingSequences(history, "force-46-did-not-converge");
}

function assertPostHistory(history, forced) {
  const latest = history.at(-1);
  if (latest[0] !== "48" || latest[1] !== "0" || history.some(([version]) => BigInt(version) > 48n)) fail("post-migration-history-invalid");
  assertIncreasingSequences(history, "post-migration-history-invalid");
  if (forced) {
    const tail = history.slice(forced.length).map(([version, dirty]) => [version, dirty]);
    if (stableJson(history.slice(0, forced.length)) !== stableJson(forced) || stableJson(tail) !== stableJson([["47", "1"], ["47", "0"], ["48", "1"], ["48", "0"]])) fail("post-migration-history-invalid");
  }
}

async function assertQuiet(query) {
  const sql = querySql();
  assertZero(await query(sql.activeMigration), "concurrent-migration-or-ddl");
  assertZero(await query(sql.nonRead), "concurrent-writer");
}

async function inspect(query, stage, expectedHistory) {
  const sql = querySql();
  const identityRaw = await query(sql.identity);
  const migrationRaw = await query(sql.migrations);
  const inventoryRaw = await query(sql.inventory);
  const identity = rows(identityRaw);
  if (identity.length !== 1 || identity[0].length !== 2 || identity[0][0] !== DATABASE) fail("unexpected-database-identity");
  if (identity[0][1] !== CLICKHOUSE_VERSION) fail("unexpected-clickhouse-version");
  const history = migrationRows(migrationRaw);
  assertRows(rows(inventoryRaw), EXPECTED_OBJECTS, "unexpected-object-inventory");

  const counts = {};
  for (const table of INGESTION_TABLES) {
    const count = scalar(await query(countSql(table)));
    if (count !== "0") fail("database-not-empty");
    counts[table] = count;
  }

  if (stage === "initial") {
    assertInitialHistory(history);
    const partialColumns = await query(sql.partialColumns);
    const partialIndices = await query(sql.partialIndices);
    const mv = await query(showObjectSql("events_core_mv"));
    assertSemanticRows(rows(partialColumns), [["events_full", "evaluator_id", "String", "DEFAULT", "arrayElement(metadata_values, indexOf(metadata_names, 'evaluator_id'))"]], "unexpected-partial-47-columns");
    assertRows(rows(partialIndices), [], "unexpected-partial-47-indices");
    const mvText = asBuffer(mv).toString("utf8");
    if (["evaluator_id", "evaluation_rule_id", "evaluator_execution_is_test"].some((name) => mvText.includes(name))) fail("unexpected-partial-47-view");
  } else if (stage === "forced") {
    assertForcedHistory(history, expectedHistory);
  } else if (stage === "post") {
    assertPostHistory(history, expectedHistory);
  }
  await assertQuiet(query);

  return {
    identity: identity[0],
    historyRaw: asBuffer(migrationRaw),
    history,
    inventoryRaw: asBuffer(inventoryRaw),
    counts,
  };
}

async function captureDefinitions(query) {
  const database = asBuffer(await query(`SHOW CREATE DATABASE ${DATABASE} FORMAT TSVRaw`));
  if (!/^CREATE DATABASE `?default`?(?=\s|$)/.test(normalizedSql(database.toString("utf8")))) fail("unexpected-database-ddl");
  const objects = {};
  for (const [name, type] of EXPECTED_OBJECTS) {
    const ddl = asBuffer(await query(showObjectSql(name)));
    const text = normalizedSql(ddl.toString("utf8"));
    const prefix = type === "View" ? "CREATE VIEW" : type === "MaterializedView" ? "CREATE MATERIALIZED VIEW" : "CREATE TABLE";
    const objectPattern = new RegExp("^" + prefix + " .*(?:`?default`?\\.)`?" + name + "`?(?=\\s|\\(|$)");
    if (!objectPattern.test(text)) fail("unexpected-object-ddl");
    objects[name] = ddl;
  }
  return { database, objects };
}

function fingerprint(state, definitions) {
  return sha256(stableJson({
    identity: state.identity,
    history: sha256(state.historyRaw),
    inventory: sha256(state.inventoryRaw),
    counts: state.counts,
    database: sha256(definitions.database),
    objects: Object.fromEntries(Object.entries(definitions.objects).map(([name, ddl]) => [name, sha256(ddl)])),
  }));
}

function ensureRecoveryRoot(root) {
  if (!existsSync(root) || !lstatSync(root).isDirectory()) fail("recovery-root-invalid");
}

function rootEntries(root) {
  return readdirSync(root).filter((entry) => entry !== LOCK_NAME).sort();
}

function acquireLock(root) {
  const lock = safeChild(root, LOCK_NAME);
  if (existsSync(lock)) fail("recovery-lock-held");
  privateDirectory(lock);
  return lock;
}

function releaseLock(lock) {
  try {
    rmdirSync(lock);
  } catch {
    fail("recovery-lock-release-failed");
  }
}

function writeSnapshot(root, state, definitions, config) {
  const id = `snapshot-${randomUUID()}`;
  const partial = safeChild(root, `${id}.partial`);
  const complete = safeChild(root, `${id}.complete`);
  if (existsSync(partial) || existsSync(complete)) fail("snapshot-name-collision");
  privateDirectory(partial);
  privateDirectory(join(partial, "objects"));

  privateFile(join(partial, "database.sql"), definitions.database);
  privateFile(join(partial, "schema_migrations.tsv"), state.historyRaw);
  for (const [name] of EXPECTED_OBJECTS) privateFile(join(partial, "objects", `${name}.sql`), definitions.objects[name]);

  const files = {
    "database.sql": sha256(definitions.database),
    "schema_migrations.tsv": sha256(state.historyRaw),
  };
  for (const [name] of EXPECTED_OBJECTS) files[`objects/${name}.sql`] = sha256(definitions.objects[name]);
  const manifest = {
    kind: "langfuse-empty-schema-backup-v1",
    image: config.image,
    configSha256: config.configSha256,
    sourceScriptSha256: config.sourceScriptSha256,
    fenceRevision: config.fenceRevision,
    clickhouseVersion: config.clickhouseVersion,
    databaseIdentity: state.identity,
    migrationHistorySha256: sha256(state.historyRaw),
    objectInventorySha256: sha256(state.inventoryRaw),
    tableCounts: state.counts,
    schemaSha256: sha256(stableJson(files)),
    files,
  };
  privateFile(join(partial, "manifest.json"), `${JSON.stringify(manifest)}\n`);
  verifySnapshot(partial, config);
  return { id, partial, complete, manifest };
}

function snapshotExpectedPaths() {
  return [
    "database.sql",
    "schema_migrations.tsv",
    "manifest.json",
    ...EXPECTED_OBJECTS.map(([name]) => `objects/${name}.sql`),
  ];
}

function verifySnapshot(snapshot, config) {
  if (!lstatSync(snapshot).isDirectory()) fail("snapshot-invalid");
  assertMode(snapshot, 0o700);
  const objectsDirectory = join(snapshot, "objects");
  if (!lstatSync(objectsDirectory).isDirectory()) fail("snapshot-invalid");
  assertMode(objectsDirectory, 0o700);
  const manifestPath = join(snapshot, "manifest.json");
  assertMode(manifestPath, 0o600);
  let manifest;
  try {
    manifest = JSON.parse(readFileSync(manifestPath, "utf8"));
  } catch {
    fail("snapshot-manifest-invalid");
  }
  if (manifest.kind !== "langfuse-empty-schema-backup-v1" || manifest.image !== config.image || manifest.configSha256 !== config.configSha256 || manifest.sourceScriptSha256 !== config.sourceScriptSha256 || manifest.fenceRevision !== config.fenceRevision || manifest.clickhouseVersion !== config.clickhouseVersion) {
    fail("snapshot-manifest-invalid");
  }
  const expected = snapshotExpectedPaths().filter((path) => path !== "manifest.json").sort();
  if (stableJson(Object.keys(manifest.files ?? {}).sort()) !== stableJson(expected)) fail("snapshot-manifest-invalid");
  for (const path of expected) {
    const full = safeChild(snapshot, path);
    assertMode(full, 0o600);
    if (typeof manifest.files[path] !== "string" || manifest.files[path] !== sha256(readFileSync(full))) fail("snapshot-checksum-invalid");
  }
  const allowedTop = new Set(["database.sql", "schema_migrations.tsv", "manifest.json", "objects", "migration.log"]);
  if (readdirSync(snapshot).some((name) => !allowedTop.has(name))) fail("snapshot-extra-artifact");
  if (existsSync(join(snapshot, "migration.log"))) assertMode(join(snapshot, "migration.log"), 0o600);
  return manifest;
}

function publishSnapshot(snapshot) {
  if (existsSync(snapshot.complete)) fail("snapshot-already-published");
  renameSync(snapshot.partial, snapshot.complete);
  assertMode(snapshot.complete, 0o700);
  return snapshot.complete;
}

function createDiagnosticLog(snapshot) {
  const log = join(snapshot, "migration.log");
  privateFile(log, "native migration diagnostics; private\n");
  return log;
}

function nativeDsn(password) {
  return `${NATIVE_URL}?username=${encodeURIComponent(USER)}&password=${encodeURIComponent(password)}&database=${DATABASE}&x-multi-statement=true&x-migrations-table-engine=MergeTree`;
}

export function runNative({ command, args, env }) {
  const result = spawnSync(command, args, { encoding: null, env, maxBuffer: 32 * 1024 * 1024 });
  return {
    ok: !result.error && result.status === 0,
    stdout: result.stdout ?? Buffer.alloc(0),
    stderr: result.stderr ?? Buffer.alloc(0),
  };
}

function recordNativeResult(log, label, result) {
  appendPrivate(log, `${label}: ${result.ok ? "ok" : "failed"}\n`);
  appendPrivate(log, result.stdout);
  appendPrivate(log, result.stderr);
}

function forceCommand(password) {
  return {
    command: MIGRATE,
    args: ["-source", `file://${MIGRATIONS}`, "-database", nativeDsn(password), "force", "46"],
    env: { PATH: "/usr/bin:/bin" },
  };
}

function upCommand(password) {
  return {
    command: MIGRATE,
    args: ["-source", `file://${MIGRATIONS}`, "-database", nativeDsn(password), "up"],
    env: { PATH: "/usr/bin:/bin" },
  };
}

async function verifyPost(query, forcedHistory) {
  const state = await inspect(query, "post", forcedHistory);
  const sql = querySql();
  const columns = await query(sql.requiredColumns);
  const indices = await query(sql.requiredIndices);
  const view = await query(showObjectSql("events_core_mv"));
  const scores = await query(showObjectSql("scores"));
  const datasetRunItems = await query(showObjectSql("dataset_run_items_rmt"));
  assertSemanticRows(rows(columns), REQUIRED_47_COLUMNS, "migration-47-columns-missing");
  assertRows(rows(indices), REQUIRED_47_INDICES, "migration-47-indices-missing");
  const viewText = asBuffer(view).toString("utf8");
  const projection = normalizedSql(viewText).toLowerCase();
  if (!/metadata_values(?:\s+as\s+metadata_values)?, evaluator_id, evaluation_rule_id, evaluator_execution_is_test, experiment_id/.test(projection) || !/from (?:`?default`?\.)?`?events_full`?(?=\s|$)/.test(projection)) fail("migration-47-view-missing");
  for (const ddl of [scores, datasetRunItems]) {
    const text = asBuffer(ddl).toString("utf8");
    if (!/\benable_block_number_column\s*=\s*1\b/.test(text) || !/\benable_block_offset_column\s*=\s*1\b/.test(text)) fail("migration-48-settings-missing");
  }
  await assertQuiet(query);
  return {
    latest: state.history.at(-1),
    migrationHistorySha256: sha256(state.historyRaw),
    objectInventorySha256: sha256(state.inventoryRaw),
    tableCountsSha256: sha256(stableJson(state.counts)),
    columnsSha256: sha256(columns),
    indicesSha256: sha256(indices),
    eventsCoreMvSha256: sha256(view),
    settingsSha256: sha256(Buffer.concat([asBuffer(scores), asBuffer(datasetRunItems)])),
  };
}

function writeReceipt(root, snapshot, before, after, config) {
  const id = `receipt-${randomUUID()}`;
  const partial = safeChild(root, `${id}.partial`);
  const complete = safeChild(root, `${id}.json`);
  if (existsSync(partial) || existsSync(complete)) fail("receipt-name-collision");
  const manifestPath = join(snapshot, "manifest.json");
  const receipt = {
    kind: "langfuse-empty-schema-recovery-receipt-v1",
    image: config.image,
    configSha256: config.configSha256,
    sourceScriptSha256: config.sourceScriptSha256,
    fenceRevision: config.fenceRevision,
    clickhouseVersion: config.clickhouseVersion,
    databaseIdentity: before.identity,
    snapshot: basename(snapshot),
    snapshotManifestSha256: sha256(readFileSync(manifestPath)),
    before: {
      migrationHistorySha256: sha256(before.historyRaw),
      objectInventorySha256: sha256(before.inventoryRaw),
      tableCountsSha256: sha256(stableJson(before.counts)),
      latest: before.history.at(-1),
    },
    operation: {
      migrate: MIGRATE,
      migrationSource: MIGRATIONS,
      forceVersion: "46",
      upCommand: "up",
    },
    after,
  };
  privateFile(partial, `${JSON.stringify(receipt)}\n`);
  linkSync(partial, complete);
  assertMode(complete, 0o600);
  unlinkSync(partial);
  return complete;
}

function existingReceipt(root, config) {
  const entries = rootEntries(root);
  if (entries.length === 0) return null;
  const receipts = entries.filter((entry) => /^receipt-[0-9a-f-]+\.json$/.test(entry));
  const snapshots = entries.filter((entry) => /^snapshot-[0-9a-f-]+\.complete$/.test(entry));
  if (receipts.length !== 1 || snapshots.length !== 1 || entries.length !== 2) fail("incomplete-or-ambiguous-prior-recovery");
  const receiptPath = safeChild(root, receipts[0]);
  assertMode(receiptPath, 0o600);
  let receipt;
  try {
    receipt = JSON.parse(readFileSync(receiptPath, "utf8"));
  } catch {
    fail("receipt-invalid");
  }
  if (receipt.kind !== "langfuse-empty-schema-recovery-receipt-v1" || receipt.image !== config.image || receipt.configSha256 !== config.configSha256 || receipt.sourceScriptSha256 !== config.sourceScriptSha256 || receipt.fenceRevision !== config.fenceRevision || receipt.clickhouseVersion !== config.clickhouseVersion || receipt.snapshot !== snapshots[0]) {
    fail("receipt-invalid");
  }
  const snapshot = safeChild(root, snapshots[0]);
  if (receipt.snapshotManifestSha256 !== sha256(readFileSync(join(snapshot, "manifest.json")))) fail("receipt-invalid");
  verifySnapshot(snapshot, config);
  return receipt;
}

function afterMatches(actual, expected) {
  return stableJson(actual) === stableJson(expected);
}

export async function recover({
  query,
  run = runNative,
  root = RECOVERY_ROOT,
  password = readPassword(),
  config = fixedConfig(),
} = {}) {
  if (typeof query !== "function" || typeof run !== "function") fail("recovery-adapter-invalid");
  ensureRecoveryRoot(root);
  const lock = acquireLock(root);
  try {
    const receipt = existingReceipt(root, config);
    if (receipt) {
      const post = await verifyPost(query);
      if (!afterMatches(post, receipt.after)) fail("receipt-postcondition-mismatch");
      return { mode: "readonly", receipt };
    }

    if (rootEntries(root).length !== 0) fail("incomplete-or-ambiguous-prior-recovery");
    const before = await inspect(query, "initial");
    const definitions = await captureDefinitions(query);
    await assertQuiet(query);
    const snapshot = writeSnapshot(root, before, definitions, config);

    const rechecked = await inspect(query, "initial");
    const definitionsRechecked = await captureDefinitions(query);
    await assertQuiet(query);
    if (fingerprint(before, definitions) !== fingerprint(rechecked, definitionsRechecked)) fail("snapshot-state-changed");

    const complete = publishSnapshot(snapshot);
    const diagnostic = createDiagnosticLog(complete);
    verifySnapshot(complete, config);
    const force = run(forceCommand(password));
    recordNativeResult(diagnostic, "force-46", force);
    if (!force.ok) fail("native-force-failed");
    const forced = await inspect(query, "forced", before.history);

    const up = run(upCommand(password));
    recordNativeResult(diagnostic, "native-up", up);
    if (!up.ok) fail("native-up-failed");
    const after = await verifyPost(query, forced.history);
    const receiptPath = writeReceipt(root, complete, before, after, config);
    return { mode: "completed", receiptPath, snapshot: complete, receipt: JSON.parse(readFileSync(receiptPath, "utf8")) };
  } finally {
    releaseLock(lock);
  }
}

async function main() {
  try {
    const config = fixedConfig();
    const password = readPassword();
    const result = await recover({ query: createClickHouseQuery(password), password, config });
    console.log(result.mode === "readonly" ? "Langfuse empty-schema recovery receipt verified" : "Langfuse empty-schema recovery completed");
  } catch (error) {
    const code = error instanceof RecoveryError ? error.code : "unexpected-error";
    console.error(`Langfuse empty-schema recovery failed (${code})`);
    process.exitCode = 1;
  }
}

if (process.argv[1] && import.meta.url === pathToFileURL(process.argv[1]).href) await main();
