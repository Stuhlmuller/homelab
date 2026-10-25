const assert = require('node:assert/strict');
const test = require('node:test');
const fs = require('node:fs');
const os = require('node:os');
const path = require('node:path');
const collector = require('../../clusters/homelab/apps/renovate/acceptance-schedule-collector.js');

const cronUid = '11111111-1111-1111-1111-111111111111';
const jobUid = '22222222-2222-2222-2222-222222222222';
const podUid = '33333333-3333-3333-3333-333333333333';
const jobName = 'renovate-29881680';
const scheduledAt = '2026-10-25T04:00:00Z';

function fixture({ complete = true, marker = true, failed = false } = {}) {
  const cron = { kind: 'CronJob', metadata: { name: 'renovate', uid: cronUid,
    resourceVersion: '101', generation: 1 }, spec: { schedule: '0 * * * *',
    timeZone: 'Etc/UTC', suspend: false, concurrencyPolicy: 'Forbid',
    startingDeadlineSeconds: 900, successfulJobsHistoryLimit: 3,
    failedJobsHistoryLimit: 3 }, status: { lastScheduleTime: scheduledAt } };
  const job = { metadata: { name: jobName, uid: jobUid, creationTimestamp: scheduledAt,
    annotations: { 'batch.kubernetes.io/cronjob-scheduled-timestamp': scheduledAt },
    ownerReferences: [{ controller: true, kind: 'CronJob', name: 'renovate', uid: cronUid }] },
  status: { startTime: scheduledAt, completionTime: complete && !failed ? '2026-10-25T04:25:00Z' : undefined,
    conditions: complete ? [{ type: failed ? 'Failed' : 'Complete', status: 'True',
      lastTransitionTime: '2026-10-25T04:25:00Z' }] : [] } };
  const pod = { metadata: { name: `${jobName}-example`, uid: podUid,
    creationTimestamp: scheduledAt,
    ownerReferences: [{ controller: true, kind: 'Job', name: jobName, uid: jobUid }] },
  status: { phase: complete ? failed ? 'Failed' : 'Succeeded' : 'Running',
    startTime: scheduledAt } };
  const log = marker ? [
    '2026-10-25T04:00:35.762380358Z  INFO: Renovate started',
    '2026-10-25T04:01:00.930994843Z  INFO: Autodiscovered repositories',
    '  "repositories": ["private/name"]',
  ].join('\n') : '2026-10-25T04:00:35Z  ERROR: App token failed\n';
  const resources = [cron, { kind: 'JobList', metadata: { resourceVersion: '102' },
    items: [job, { metadata: { name: 'other-job', uid: 'other', ownerReferences: [] } }] },
  { kind: 'PodList', metadata: { resourceVersion: '103' }, items: [pod] }];
  let reads = 0;
  const request = async (endpoint) => {
    if (endpoint.includes('/log?')) return Buffer.from(log);
    return Buffer.from(JSON.stringify(resources[reads++]));
  };
  return { request, reads: () => reads };
}

test('keeps a conservative discovery-completion marker and only CronJob-owned identities', async () => {
  const source = fixture();
  const result = await collector.collect(source.request, () => '2026-10-25T04:30:00Z', false);
  assert.equal(source.reads(), 3);
  assert.equal(result.jobs.length, 1);
  assert.equal(result.jobs[0].uid, jobUid);
  assert.equal(result.jobs[0].scheduledAt, scheduledAt);
  assert.equal(result.jobs[0].phase, 'succeeded');
  assert.deepEqual({ concurrencyPolicy: result.cronjob.concurrencyPolicy,
    startingDeadlineSeconds: result.cronjob.startingDeadlineSeconds,
    successfulJobsHistoryLimit: result.cronjob.successfulJobsHistoryLimit,
    failedJobsHistoryLimit: result.cronjob.failedJobsHistoryLimit },
  { concurrencyPolicy: 'Forbid', startingDeadlineSeconds: 900,
    successfulJobsHistoryLimit: 3, failedJobsHistoryLimit: 3 });
  assert.equal(result.pods[0].uid, podUid);
  assert.equal(result.pods[0].log.discoveryCompletedAt, '2026-10-25T04:01:00.930994Z');
  assert.equal(result.pods[0].log.globalStartedAt, '2026-10-25T04:00:35.762380Z');
  assert.equal(JSON.stringify(result).includes('private/name'), false);
});

test('a failed Job before discovery has no fabricated discovery marker', async () => {
  const source = fixture({ failed: true, marker: false });
  const result = await collector.collect(source.request, () => '2026-10-25T04:30:00Z', false);
  assert.equal(result.jobs[0].phase, 'failed');
  assert.equal(result.jobs[0].finishedAt, '2026-10-25T04:25:00Z');
  assert.equal(result.pods[0].log.discoveryCompletedAt, null);
});

test('multiple discovery-completion markers are ambiguous', () => {
  const log = Buffer.from('2026-10-25T04:01:00Z  INFO: Autodiscovered repositories\n' +
    '2026-10-25T04:02:00Z  INFO: Autodiscovered repositories\n');
  assert.equal(collector.logMarkers(log).discoveryCompletedAt, null);
  assert.equal(collector.logMarkers(log).discoveryMarkerCount, 2);
});

test('a paginated Kubernetes list cannot certify an exhaustive snapshot', async () => {
  const source = fixture();
  let requests = 0;
  const request = async (endpoint) => {
    const body = await source.request(endpoint);
    if (++requests === 2) {
      const list = JSON.parse(body);
      list.metadata.continue = 'next-page';
      return Buffer.from(JSON.stringify(list));
    }
    return body;
  };
  await assert.rejects(() => collector.collect(request, () => scheduledAt, false),
    /incomplete-kubernetes-list/);
});

test('writes only private immutable logs and snapshots', async () => {
  const root = fs.mkdtempSync(path.join(os.tmpdir(), 'renovate-schedule-'));
  fs.chmodSync(root, 0o700);
  try {
    const output = path.join(root, 'private', 'schedule');
    const source = fixture();
    const result = await collector.collect(source.request,
      () => '2026-10-25T04:30:00Z', true, output);
    const log = path.join(output, result.pods[0].log.file);
    const snapshots = fs.readdirSync(path.join(output, 'snapshots'));
    assert.equal(snapshots.length, 1);
    assert.equal(fs.statSync(log).mode & 0o777, 0o600);
    assert.equal(fs.statSync(path.join(output, 'snapshots', snapshots[0])).mode & 0o777, 0o600);
    assert.equal(fs.statSync(output).mode & 0o777, 0o700);
    assert.match(fs.readFileSync(log, 'utf8'), /private\/name/);
    assert.equal(fs.readFileSync(path.join(output, 'snapshots', snapshots[0]), 'utf8')
      .includes('private/name'), false);
  } finally {
    fs.rmSync(root, { recursive: true, force: true });
  }
});
