// Temporary, read-only Kubernetes evidence collector for SC-001.
// Raw logs and snapshots stay on the private acceptance ledger.
const fs = require('node:fs');
const path = require('node:path');
const https = require('node:https');
const crypto = require('node:crypto');

const namespace = 'automation';
const cronName = 'renovate';
const ledger = '/ledger/private/schedule';
const tokenFile = '/var/run/secrets/kubernetes.io/serviceaccount/token';
const caFile = '/var/run/secrets/kubernetes.io/serviceaccount/ca.crt';
const maxMetadata = 4 * 1024 * 1024;
const maxLog = 8 * 1024 * 1024;

function digest(bytes) {
  return crypto.createHash('sha256').update(bytes).digest('hex');
}

function utc(value) {
  if (typeof value !== 'string' || !/^\d{4}-\d{2}-\d{2}T\d{2}:\d{2}:\d{2}(?:\.\d{1,9})?Z$/.test(value) ||
      !Number.isFinite(Date.parse(value))) throw new Error('invalid-time');
  // Kubernetes log timestamps can have nanoseconds; the evaluator accepts microseconds.
  return value.replace(/\.(\d{6})\d+Z$/, '.$1Z');
}

function owner(resource, kind, name, uid) {
  return resource?.metadata?.ownerReferences?.some((reference) =>
    reference.controller === true && reference.kind === kind &&
    reference.name === name && reference.uid === uid) === true;
}

function logMarkers(bytes) {
  let globalStartedAt = null;
  let discoveryCompletedAt = null;
  let globalCount = 0;
  let discoveryCount = 0;
  for (const line of bytes.toString('utf8').split('\n')) {
    const match = /^(\d{4}-\d\d-\d\dT\d\d:\d\d:\d\d(?:\.\d{1,9})?Z)\s+INFO: (Renovate started|Autodiscovered repositories)(?:\s|$)/.exec(line);
    if (!match) continue;
    const at = utc(match[1]);
    if (match[2] === 'Renovate started') {
      globalCount += 1;
      globalStartedAt = at;
    } else {
      discoveryCount += 1;
      discoveryCompletedAt = at;
    }
  }
  return {
    globalStartedAt: globalCount === 1 ? globalStartedAt : null,
    discoveryCompletedAt: discoveryCount === 1 ? discoveryCompletedAt : null,
    globalMarkerCount: globalCount,
    discoveryMarkerCount: discoveryCount,
  };
}

function checkedDirectory(directory) {
  fs.mkdirSync(directory, { recursive: true, mode: 0o700 });
  const info = fs.lstatSync(directory);
  if (!info.isDirectory() || info.isSymbolicLink() || info.uid !== process.getuid() ||
      (info.mode & 0o077) !== 0) throw new Error('unsafe-ledger-directory');
}

function writeExclusive(file, bytes) {
  fs.writeFileSync(file, bytes, { flag: 'wx', mode: 0o600, flush: true });
}

function saveLog(file, bytes) {
  if (!fs.existsSync(file)) {
    writeExclusive(file, bytes);
    return;
  }
  const info = fs.lstatSync(file);
  if (!info.isFile() || info.isSymbolicLink() || info.uid !== process.getuid() ||
      (info.mode & 0o077) || info.size !== bytes.length ||
      digest(fs.readFileSync(file)) !== digest(bytes)) throw new Error('changed-private-log');
}

function apiRequest(endpoint, maximum, token, ca) {
  return new Promise((resolve, reject) => {
    const request = https.request(`https://10.96.0.1${endpoint}`, {
      method: 'GET', ca, servername: 'kubernetes.default.svc',
      headers: { Authorization: `Bearer ${token}`, Host: 'kubernetes.default.svc', Accept: '*/*' },
    }, (response) => {
      if (response.statusCode !== 200) {
        response.resume();
        reject(new Error('kubernetes-api-response'));
        return;
      }
      const chunks = [];
      let size = 0;
      let tooLarge = false;
      response.on('data', (part) => {
        size += part.length;
        if (size > maximum) {
          tooLarge = true;
          request.destroy(new Error('kubernetes-response-too-large'));
          return;
        }
        chunks.push(part);
      });
      response.on('end', () => {
        if (tooLarge) reject(new Error('kubernetes-response-too-large'));
        else resolve(Buffer.concat(chunks));
      });
      response.on('error', reject);
    });
    request.setTimeout(15000, () => request.destroy(new Error('kubernetes-api-timeout')));
    request.on('error', reject);
    request.end();
  });
}

function metadataDocument(bytes) {
  let result;
  try { result = JSON.parse(bytes); } catch { throw new Error('invalid-kubernetes-json'); }
  if (!result || typeof result !== 'object') throw new Error('invalid-kubernetes-json');
  return result;
}

function listDocument(bytes, kind) {
  const result = metadataDocument(bytes);
  if (result.kind !== kind || !Array.isArray(result.items) ||
      typeof result.metadata?.resourceVersion !== 'string' || result.metadata?.continue) {
    throw new Error('incomplete-kubernetes-list');
  }
  return result;
}

function jobRecord(job) {
  const conditions = job.status?.conditions || [];
  const complete = conditions.some((condition) => condition.type === 'Complete' && condition.status === 'True');
  const failed = conditions.some((condition) => condition.type === 'Failed' && condition.status === 'True');
  return {
    name: job.metadata.name,
    uid: job.metadata.uid,
    scheduledAt: job.metadata.annotations?.['batch.kubernetes.io/cronjob-scheduled-timestamp'] || null,
    createdAt: job.metadata.creationTimestamp,
    startedAt: job.status?.startTime || null,
    finishedAt: complete ? job.status?.completionTime || null :
      failed ? conditions.find((condition) => condition.type === 'Failed' && condition.status === 'True')?.lastTransitionTime || null : null,
    phase: complete ? 'succeeded' : failed ? 'failed' : 'active',
  };
}

function podRecord(pod, log = null) {
  return {
    name: pod.metadata.name,
    uid: pod.metadata.uid,
    jobUid: pod.metadata.ownerReferences.find((item) => item.controller === true && item.kind === 'Job').uid,
    createdAt: pod.metadata.creationTimestamp,
    phase: pod.status?.phase || 'Unknown',
    startedAt: pod.status?.startTime || null,
    containerStartedAt: pod.status?.containerStatuses?.find((item) => item.name === 'renovate')?.state?.running?.startedAt || null,
    log,
  };
}

async function collect(request, now = () => new Date().toISOString(), write = true, outputRoot = ledger) {
  const startedAt = now();
  const base = `/apis/batch/v1/namespaces/${namespace}`;
  const cron = metadataDocument(await request(`${base}/cronjobs/${cronName}`, maxMetadata));
  if (cron.kind !== 'CronJob' || cron.metadata?.name !== cronName || !cron.metadata?.uid) {
    throw new Error('wrong-cronjob');
  }
  const jobs = listDocument(await request(`${base}/jobs`, maxMetadata), 'JobList');
  const pods = listDocument(await request(`/api/v1/namespaces/${namespace}/pods`, maxMetadata), 'PodList');
  const selectedJobs = jobs.items.filter((job) => owner(job, 'CronJob', cronName, cron.metadata.uid));
  const selectedPods = pods.items.filter((pod) => selectedJobs.some((job) =>
    owner(pod, 'Job', job.metadata.name, job.metadata.uid)));
  if (selectedJobs.some((job) => !/^renovate-\d+$/.test(job.metadata?.name || '') || !job.metadata?.uid) ||
      selectedPods.some((pod) => !pod.metadata?.uid || !pod.metadata?.name)) {
    throw new Error('invalid-job-identity');
  }

  const logs = new Map();
  if (write) {
    checkedDirectory(path.dirname(path.dirname(outputRoot)));
    checkedDirectory(path.dirname(outputRoot));
    checkedDirectory(outputRoot);
    checkedDirectory(path.join(outputRoot, 'logs'));
    checkedDirectory(path.join(outputRoot, 'snapshots'));
  }
  for (const pod of selectedPods) {
    const phase = pod.status?.phase;
    let log = null;
    if (phase === 'Running' || phase === 'Succeeded' || phase === 'Failed') {
      const endpoint = `/api/v1/namespaces/${namespace}/pods/${encodeURIComponent(pod.metadata.name)}/log?container=renovate&timestamps=true`;
      const bytes = await request(endpoint, maxLog);
      if (bytes.length === 0 && phase !== 'Running') throw new Error('terminal-pod-log-empty');
      if (!/^[0-9a-f-]{36}$/.test(pod.metadata.uid)) throw new Error('invalid-pod-uid');
      const filename = `${pod.metadata.uid}-${digest(bytes)}.log`;
      if (write) saveLog(path.join(outputRoot, 'logs', filename), bytes);
      log = { file: `logs/${filename}`, sha256: digest(bytes), bytes: bytes.length,
        ...logMarkers(bytes) };
      logs.set(pod.metadata.uid, log);
    }
  }
  const snapshot = {
    schema: 1,
    startedAt,
    finishedAt: now(),
    cronjob: {
      uid: cron.metadata.uid,
      resourceVersion: cron.metadata.resourceVersion,
      generation: cron.metadata.generation,
      schedule: cron.spec?.schedule,
      timeZone: cron.spec?.timeZone,
      suspend: cron.spec?.suspend === true,
      concurrencyPolicy: cron.spec?.concurrencyPolicy ?? null,
      startingDeadlineSeconds: cron.spec?.startingDeadlineSeconds ?? null,
      successfulJobsHistoryLimit: cron.spec?.successfulJobsHistoryLimit ?? null,
      failedJobsHistoryLimit: cron.spec?.failedJobsHistoryLimit ?? null,
      lastScheduleTime: cron.status?.lastScheduleTime || null,
    },
    jobsResourceVersion: jobs.metadata.resourceVersion,
    podsResourceVersion: pods.metadata.resourceVersion,
    jobs: selectedJobs.map(jobRecord),
    pods: selectedPods.map((pod) => podRecord(pod, logs.get(pod.metadata.uid) || null)),
  };
  if (write) {
    const name = `${startedAt.replace(/[:.]/g, '-')}-${crypto.randomUUID()}.json`;
    writeExclusive(path.join(outputRoot, 'snapshots', name), `${JSON.stringify(snapshot)}\n`);
  }
  return snapshot;
}

async function main() {
  const token = fs.readFileSync(tokenFile, 'utf8').trim();
  const ca = fs.readFileSync(caFile);
  if (!token || !ca.length) throw new Error('missing-service-account');
  const snapshot = await collect((endpoint, maximum) => apiRequest(endpoint, maximum, token, ca));
  console.log(JSON.stringify({ mode: 'schedule-snapshot', jobs: snapshot.jobs.length,
    pods: snapshot.pods.length, finishedAt: snapshot.finishedAt }));
}

if (require.main === module) main().catch(() => {
  console.error('schedule-snapshot-failed');
  process.exitCode = 1;
});

module.exports = { collect, logMarkers, owner, utc, jobRecord };
