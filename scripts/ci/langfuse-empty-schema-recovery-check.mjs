// Offline recovery regression: no cluster, credentials, or network access.
import assert from "node:assert/strict";
import { spawnSync } from "node:child_process";
import { copyFileSync, mkdirSync, mkdtempSync, readFileSync, readdirSync, realpathSync, statSync, symlinkSync, writeFileSync } from "node:fs";
import { join } from "node:path";
import { tmpdir } from "node:os";
import { fileURLToPath } from "node:url";
import { CLICKHOUSE_VERSION, IMAGE, MIGRATE, MIGRATIONS, fixedConfig, recover } from "../../clusters/homelab/apps/langfuse/recover-empty-schema.mjs";

const config = {
  image: IMAGE,
  configSha256: "c".repeat(64),
  sourceScriptSha256: "s".repeat(64),
  fenceRevision: "f".repeat(40),
  clickhouseVersion: CLICKHOUSE_VERSION,
};
const password = "super-secret"; // Inert sentinel, never a real credential.
const objects = [
  ["analytics_observations", "View"], ["analytics_scores", "View"], ["analytics_traces", "View"],
  ["blob_storage_file_log", "ReplacingMergeTree"], ["dataset_run_items_rmt", "ReplacingMergeTree"],
  ["events_core", "ReplacingMergeTree"], ["events_core_mv", "MaterializedView"], ["events_full", "ReplacingMergeTree"],
  ["observations", "ReplacingMergeTree"], ["observations_batch_staging", "ReplacingMergeTree"],
  ["observations_pid_tid_sorting", "ReplacingMergeTree"], ["schema_migrations", "MergeTree"],
  ["scores", "ReplacingMergeTree"], ["traces", "ReplacingMergeTree"],
];
const tables = ["blob_storage_file_log", "dataset_run_items_rmt", "events_core", "events_full", "observations", "observations_batch_staging", "observations_pid_tid_sorting", "scores", "traces"];
const initialHistory = [
  ["45", "1", "9007199254741001"], ["45", "0", "9007199254741002"],
  ["46", "1", "9007199254741003"], ["46", "0", "9007199254741004"],
  ["47", "1", "9007199254741005"],
];
const postColumns = [
  ["events_core", "evaluator_execution_is_test", "Bool", "DEFAULT", "has(metadata_names, 'evaluator_test') AND (arrayElement(metadata_values, indexOf(metadata_names, 'evaluator_test')) = 'true')"],
  ["events_core", "evaluator_id", "String", "DEFAULT", "arrayElement(metadata_values, indexOf(metadata_names, 'evaluator_id'))"],
  ["events_core", "evaluation_rule_id", "String", "DEFAULT", "if(notEmpty(arrayElement(metadata_values, indexOf(metadata_names, 'evaluation_rule_id'))), arrayElement(metadata_values, indexOf(metadata_names, 'evaluation_rule_id')), arrayElement(metadata_values, indexOf(metadata_names, 'job_configuration_id')))"],
  ["events_full", "evaluator_execution_is_test", "Bool", "DEFAULT", "has(metadata_names, 'evaluator_test') AND (arrayElement(metadata_values, indexOf(metadata_names, 'evaluator_test')) = 'true')"],
  ["events_full", "evaluator_id", "String", "DEFAULT", "arrayElement(metadata_values, indexOf(metadata_names, 'evaluator_id'))"],
  ["events_full", "evaluation_rule_id", "String", "DEFAULT", "if(notEmpty(arrayElement(metadata_values, indexOf(metadata_names, 'evaluation_rule_id'))), arrayElement(metadata_values, indexOf(metadata_names, 'evaluation_rule_id')), arrayElement(metadata_values, indexOf(metadata_names, 'job_configuration_id')))"],
  ["scores", "evaluator_id", "String", "DEFAULT", "metadata['evaluator_id']"],
  ["scores", "evaluation_rule_id", "String", "DEFAULT", "if(notEmpty(metadata['evaluation_rule_id']), metadata['evaluation_rule_id'], metadata['job_configuration_id'])"],
];
const postIndices = [
  ["events_core", "idx_evaluation_rule_id", "bloom_filter", "bloom_filter(0.01)", "evaluation_rule_id", "1"],
  ["events_core", "idx_evaluator_id", "bloom_filter", "bloom_filter(0.01)", "evaluator_id", "1"],
  ["scores", "idx_evaluation_rule_id", "bloom_filter", "bloom_filter(0.001)", "evaluation_rule_id", "1"],
  ["scores", "idx_evaluator_id", "bloom_filter", "bloom_filter(0.001)", "evaluator_id", "1"],
];

const tsv = (data) => data.length === 0 ? "" : `${data.map((row) => row.join("\t")).join("\n")}\n`;
const mode = (path) => statSync(path).mode & 0o777;
const temporaryRoot = () => {
  const root = join(mkdtempSync(join(tmpdir(), "langfuse-empty-schema-")), "recovery");
  mkdirSync(root, { mode: 0o700 });
  return root;
};

class FakeClickHouse {
  constructor(options = {}) {
    this.options = options;
    this.phase = "initial";
    this.history = initialHistory.map((row) => [...row]);
  }

  objectDdl(name) {
    if (name === "events_core_mv") {
      return this.phase === "post"
        ? "CREATE MATERIALIZED VIEW default.events_core_mv AS SELECT arrayMap(v -> leftUTF8(v, 200), metadata_values) AS metadata_values, evaluator_id, evaluation_rule_id, evaluator_execution_is_test, experiment_id FROM default.events_full\n"
        : "CREATE MATERIALIZED VIEW default.events_core_mv AS SELECT metadata_values AS metadata_values, experiment_id FROM default.events_full\n";
    }
    if (name === "scores" || name === "dataset_run_items_rmt") {
      return `CREATE TABLE default.${name} (id String) ENGINE = ReplacingMergeTree SETTINGS${this.phase === "post" ? " enable_block_number_column = 1, enable_block_offset_column = 1" : " index_granularity = 8192"}\n`;
    }
    const type = objects.find(([object]) => object === name)[1];
    return type === "View" ? `CREATE VIEW default.${name} AS SELECT 1\n` : `CREATE TABLE default.${name} (id String) ENGINE = ${type}\n`;
  }

  async query(sql) {
    if (sql.startsWith("SELECT currentDatabase()")) return `default\t${this.options.wrongVersion ? "26.4.5.144" : CLICKHOUSE_VERSION}\n`;
    if (sql.startsWith("SELECT version, dirty, sequence")) return tsv(this.history);
    if (sql.startsWith("SELECT name, engine FROM system.tables")) return tsv(this.options.extraObject ? [...objects, ["unexpected", "MergeTree"]] : objects);
    if (sql.includes("FROM system.processes") && sql.includes("query_kind = 'Alter'")) return `${this.options.active ?? 0}\n`;
    if (sql.includes("FROM system.processes") && sql.includes("query_kind NOT IN")) return `${this.options.writer ?? 0}\n`;
    if (sql.startsWith("SELECT count() FROM default.")) {
      const table = /`([^`]+)`/.exec(sql)?.[1];
      assert.ok(tables.includes(table));
      return `${this.options.count ?? 0}\n`;
    }
    if (sql.includes("FROM system.columns")) {
      if (this.phase !== "post") return tsv([["events_full", "evaluator_id", "String", "DEFAULT", this.options.wrongInitialDefault ? "wrong_default" : "arrayElement(metadata_values, indexOf(metadata_names, 'evaluator_id'))"]]);
      const columns = this.options.wrongDefault ? postColumns.map((row) => [...row]) : postColumns;
      if (this.options.wrongDefault) columns[0][4] = "wrong_default";
      // Match ClickHouse ORDER BY table, name rather than fixture insertion order.
      return tsv([...columns].sort((left, right) =>
        left[0].localeCompare(right[0]) || left[1].localeCompare(right[1])));
    }
    if (sql.includes("FROM system.data_skipping_indices")) return tsv(this.phase === "post" ? postIndices : []);
    if (sql.startsWith("SHOW CREATE DATABASE")) return "CREATE DATABASE default ENGINE = Atomic\n";
    if (sql.startsWith("SHOW CREATE TABLE")) {
      const name = /`([^`]+)`/.exec(sql)?.[1];
      assert.ok(objects.some(([object]) => object === name));
      return this.objectDdl(name);
    }
    throw new Error(`unexpected fake query: ${sql}`);
  }
}

function runner(fake, calls, options = {}) {
  return (spec) => {
    calls.push(spec);
    const dsn = `clickhouse://langfuse-clickhouse.langfuse.svc.cluster.local:9000?username=default&password=${password}&database=default&x-multi-statement=true&x-migrations-table-engine=MergeTree`;
    assert.equal(spec.command, MIGRATE);
    assert.deepEqual(spec.args.slice(0, 4), ["-source", `file://${MIGRATIONS}`, "-database", dsn]);
    if (spec.args.at(-2) === "force") {
      assert.deepEqual(spec.args.slice(-2), ["force", "46"]);
      if (options.failForce) return { ok: false, stdout: Buffer.alloc(0), stderr: Buffer.from(password) };
      if (options.dropPrehistory) fake.history = [["45", "0", "9007199254741004"], ["46", "0", "9007199254741006"]];
      else fake.history.push(["46", "0", options.duplicateForceSequence ? fake.history.at(-1)[2] : "9007199254741006"]);
      fake.phase = "forced";
      return { ok: true, stdout: Buffer.from("force complete\n"), stderr: Buffer.from(`provider echoed ${password}\n`) };
    }
    assert.deepEqual(spec.args.slice(-1), ["up"]);
    if (options.failUp) return { ok: false, stdout: Buffer.alloc(0), stderr: Buffer.from(password) };
    if (options.replaceHistoryOnUp) fake.history = [["47", "1", "9007199254741007"], ["47", "0", "9007199254741008"], ["48", "1", "9007199254741009"], ["48", "0", "9007199254741010"]];
    else fake.history.push(["47", "1", "9007199254741007"], ["47", "0", "9007199254741008"], ["48", "1", "9007199254741009"], ["48", "0", "9007199254741010"]);
    fake.phase = "post";
    return { ok: true, stdout: Buffer.from("up complete\n"), stderr: Buffer.from(`provider echoed ${password}\n`) };
  };
}

async function rejects(promise, code) {
  await assert.rejects(promise, (error) => error?.message === code);
}

assert.match(fixedConfig().fenceRevision, /^[0-9a-f]{40}$/);

{
  // Exercise the actual CLI through Kubernetes' projected ConfigMap symlinks.
  const root = realpathSync(mkdtempSync(join(tmpdir(), "langfuse-recovery-entrypoint-")));
  const payload = join(root, "..payload");
  const name = "recover-empty-schema.mjs";
  mkdirSync(payload);
  copyFileSync(fileURLToPath(new URL(`../../clusters/homelab/apps/langfuse/${name}`, import.meta.url)), join(payload, name));
  symlinkSync("..payload", join(root, "..data"));
  symlinkSync(`..data/${name}`, join(root, name));
  for (const script of [join(payload, name), join(root, name)]) {
    // Deny credentials, writes and child processes even if run on a cluster node.
    const result = spawnSync(process.execPath, ["--permission", `--allow-fs-read=${root}`, script], {
      cwd: root, env: {}, encoding: "utf8", timeout: 5_000,
    });
    assert.ifError(result.error);
    assert.equal(result.status, 1, "CLI must enter main and fail closed without secret access");
    assert.equal(result.stdout, "");
    assert.equal(result.stderr, "Langfuse empty-schema recovery failed (unexpected-error)\n");
  }
}

for (const [options, code] of [
  [{ wrongVersion: true }, "unexpected-clickhouse-version"],
  [{ writer: 1 }, "concurrent-writer"],
  [{ count: 1 }, "database-not-empty"],
  [{ extraObject: true }, "unexpected-object-inventory"],
  [{ wrongInitialDefault: true }, "unexpected-partial-47-columns"],
]) {
  const root = temporaryRoot();
  const fake = new FakeClickHouse(options);
  const calls = [];
  await rejects(recover({ query: fake.query.bind(fake), run: runner(fake, calls), root, password, config }), code);
  assert.equal(calls.length, 0);
  assert.equal(readdirSync(root).length, 0);
}

let happy;
{
  const root = temporaryRoot();
  const fake = new FakeClickHouse();
  const calls = [];
  const result = await recover({ query: fake.query.bind(fake), run: runner(fake, calls), root, password, config });
  assert.equal(result.mode, "completed");
  assert.equal(calls.length, 2);
  assert.equal(mode(result.snapshot), 0o700);
  assert.equal(mode(join(result.snapshot, "objects")), 0o700);
  assert.equal(mode(join(result.snapshot, "database.sql")), 0o600);
  assert.equal(mode(join(result.snapshot, "migration.log")), 0o600);
  assert.equal(mode(result.receiptPath), 0o600);
  assert.equal(typeof result.receipt.before.latest[2], "string");
  assert.equal(result.receipt.before.latest[2], "9007199254741005");
  assert.ok(readFileSync(join(result.snapshot, "migration.log"), "utf8").includes("super-secret"));
  assert.ok(!JSON.stringify(result.receipt).includes("super-secret"));
  happy = { root, fake, calls, result };
}

{
  const before = readdirSync(happy.root).sort();
  const calls = [];
  const result = await recover({ query: happy.fake.query.bind(happy.fake), run: runner(happy.fake, calls), root: happy.root, password, config });
  assert.equal(result.mode, "readonly");
  assert.equal(calls.length, 0);
  assert.deepEqual(readdirSync(happy.root).sort(), before);
}

{
  const root = temporaryRoot();
  mkdirSync(root, { recursive: true, mode: 0o700 });
  mkdirSync(join(root, ".langfuse-empty-schema-recovery.lock"), { mode: 0o700 });
  const fake = new FakeClickHouse();
  const calls = [];
  await rejects(recover({ query: fake.query.bind(fake), run: runner(fake, calls), root, password, config }), "recovery-lock-held");
  assert.equal(calls.length, 0);
}

{
  const root = temporaryRoot();
  const fake = new FakeClickHouse({ wrongDefault: true });
  const calls = [];
  await rejects(recover({ query: fake.query.bind(fake), run: runner(fake, calls), root, password, config }), "migration-47-columns-missing");
  assert.equal(calls.length, 2);
  assert.equal(readdirSync(root).filter((entry) => entry.endsWith(".complete")).length, 1);
  assert.equal(readdirSync(root).filter((entry) => entry.endsWith(".json")).length, 0);
}

for (const options of [{ dropPrehistory: true }, { duplicateForceSequence: true }]) {
  const root = temporaryRoot();
  const fake = new FakeClickHouse();
  const calls = [];
  await rejects(recover({ query: fake.query.bind(fake), run: runner(fake, calls, options), root, password, config }), "force-46-did-not-converge");
  assert.equal(calls.length, 1);
  assert.equal(readdirSync(root).filter((entry) => entry.endsWith(".json")).length, 0);
}

{
  const root = temporaryRoot();
  const fake = new FakeClickHouse();
  const calls = [];
  await rejects(recover({ query: fake.query.bind(fake), run: runner(fake, calls, { replaceHistoryOnUp: true }), root, password, config }), "post-migration-history-invalid");
  assert.equal(calls.length, 2);
  assert.equal(readdirSync(root).filter((entry) => entry.endsWith(".json")).length, 0);
}

{
  const root = temporaryRoot();
  const fake = new FakeClickHouse();
  const calls = [];
  await rejects(recover({ query: fake.query.bind(fake), run: runner(fake, calls, { failUp: true }), root, password, config }), "native-up-failed");
  assert.equal(calls.length, 2);
  assert.equal(readdirSync(root).filter((entry) => entry.endsWith(".json")).length, 0);
}

{
  const root = temporaryRoot();
  const fake = new FakeClickHouse();
  const calls = [];
  await rejects(recover({ query: fake.query.bind(fake), run: runner(fake, calls, { failForce: true }), root, password, config }), "native-force-failed");
  assert.equal(calls.length, 1);
  const snapshot = readdirSync(root).find((entry) => entry.endsWith(".complete"));
  assert.ok(snapshot);
  assert.equal(mode(join(root, snapshot, "migration.log")), 0o600);
  assert.equal(readdirSync(root).filter((entry) => entry.endsWith(".json")).length, 0);
  await rejects(recover({ query: fake.query.bind(fake), run: runner(fake, calls), root, password, config }), "incomplete-or-ambiguous-prior-recovery");
  assert.equal(calls.length, 1);
}

{
  writeFileSync(join(happy.result.snapshot, "objects", "events_core.sql"), "tampered\n");
  const calls = [];
  await rejects(recover({ query: happy.fake.query.bind(happy.fake), run: runner(happy.fake, calls), root: happy.root, password, config }), "snapshot-checksum-invalid");
  assert.equal(calls.length, 0);
}

console.log("Langfuse empty-schema recovery: guards, immutable backup, UInt64 history, native failure, and receipt replay passed");
