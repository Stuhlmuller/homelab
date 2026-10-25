import { createHash } from "node:crypto";
import { spawnSync } from "node:child_process";
import { readFile } from "node:fs/promises";
import https from "node:https";

const namespace = "openclaw-system";
const expectedCheckSha = "d6919627a375f708d4d7e8142aff8bbc783c0a0565254c4372b83b7a306ffd13";
const required = (name) => {
  const value = process.env[name];
  if (!value) throw new Error(`${name} is required`);
  return value;
};
const installationSecret = required("OCE_INSTALLATION_SECRET");
const installationSha = required("OCE_INSTALLATION_SHA256");
const postgresIP = required("OCE_POSTGRES_CLUSTER_IP");
const adminEmail = required("OCE_BOOTSTRAP_ADMIN_EMAIL");
const apiHost = required("KUBERNETES_SERVICE_HOST");
const apiPort = Number(required("KUBERNETES_SERVICE_PORT"));
const token = (await readFile("/var/run/secrets/kubernetes.io/serviceaccount/token", "utf8")).trim();
const ca = await readFile("/var/run/secrets/kubernetes.io/serviceaccount/ca.crt");

function sha256(bytes) {
  return createHash("sha256").update(bytes).digest("hex");
}

function request(path, allowMissing = false) {
  return new Promise((resolve, reject) => {
    const call = https.request({
      hostname: apiHost,
      port: apiPort,
      path,
      method: "GET",
      ca,
      headers: { Authorization: `Bearer ${token}` },
      timeout: 5000,
    }, (response) => {
      let body = "";
      response.setEncoding("utf8");
      response.on("data", (chunk) => {
        body += chunk;
        if (body.length > 2_000_000) call.destroy(new Error("Kubernetes response too large"));
      });
      response.on("end", () => {
        if (allowMissing && response.statusCode === 404) return resolve(null);
        if (response.statusCode !== 200) return reject(new Error(`Kubernetes ${path} returned HTTP ${response.statusCode}`));
        try { resolve(JSON.parse(body)); } catch { reject(new Error(`Kubernetes ${path} returned invalid JSON`)); }
      });
    });
    call.on("timeout", () => call.destroy(new Error(`Kubernetes ${path} timed out`)));
    call.on("error", reject);
    call.end();
  });
}

function requireSecretKey(secret, key) {
  if (!secret || typeof secret.data?.[key] !== "string" || secret.data[key] === "") {
    throw new Error(`Secret ${secret?.metadata?.name ?? "unknown"} lacks ${key}`);
  }
}

async function run() {
  if (adminEmail.endsWith(".invalid")) throw new Error("bootstrap administrator email is still a placeholder");
  const script = await readFile("/scripts/check-installation.mjs");
  if (sha256(script) !== expectedCheckSha) throw new Error("pinned upstream installation check differs");
  const candidate = await readFile("/etc/openclaw/installation/installation.yaml");
  if (sha256(candidate) !== installationSha) throw new Error("mounted Installation bytes differ from reviewed checksum");

  const startup = await request(`/api/v1/namespaces/${namespace}/secrets/${installationSecret}`);
  if (startup.immutable !== true || startup.metadata?.name !== installationSecret) {
    throw new Error("startup Secret name or immutability differs");
  }
  requireSecretKey(startup, "installation.yaml");
  if (sha256(Buffer.from(startup.data["installation.yaml"], "base64")) !== installationSha) {
    throw new Error("startup Secret bytes differ from reviewed checksum");
  }
  for (const [name, keys] of [
    ["occ-auth", ["secret"]],
    ["occ-database", ["application-url", "migration-url"]],
    ["occ-postgres-root", ["tls.crt"]],
    ["occ-private-gateway-key", ["occ"]],
  ]) {
    const secret = await request(`/api/v1/namespaces/${namespace}/secrets/${name}`);
    for (const key of keys) requireSecretKey(secret, key);
  }

  const pvc = await request(`/api/v1/namespaces/${namespace}/persistentvolumeclaims/occ-bootstrap-admin-password`);
  if (pvc.status?.phase !== "Bound" || pvc.spec?.storageClassName !== "openclaw-enterprise-bootstrap-local") {
    throw new Error("private bootstrap PVC is not Bound to its local class");
  }
  const service = await request(`/api/v1/namespaces/${namespace}/services/occ-postgres`);
  if (service.spec?.clusterIP !== postgresIP) throw new Error("PostgreSQL Service IP differs from reviewed egress destination");
  const slices = await request(`/apis/discovery.k8s.io/v1/namespaces/${namespace}/endpointslices?labelSelector=kubernetes.io%2Fservice-name%3Docc-postgres`);
  if (!slices.items?.some((slice) => slice.endpoints?.some((endpoint) => endpoint.conditions?.ready === true && endpoint.addresses?.length))) {
    throw new Error("PostgreSQL has no ready EndpointSlice address");
  }

  const job = await request(`/apis/batch/v1/namespaces/${namespace}/jobs/oce-initialization`, true);
  if (job && (job.status?.active || !job.status?.conditions?.some((condition) =>
    condition.status === "True" && ["Complete", "Failed"].includes(condition.type)))) {
    throw new Error("previous initialization Job is not terminal");
  }
  const pods = await request(`/api/v1/namespaces/${namespace}/pods?labelSelector=batch.kubernetes.io%2Fjob-name%3Doce-initialization`);
  if (pods.items?.some((pod) => !["Succeeded", "Failed"].includes(pod.status?.phase))) {
    throw new Error("previous initialization Pod is not terminal");
  }

  const check = spawnSync("node", ["/scripts/check-installation.mjs"], {
    cwd: "/app",
    env: { ...process.env, OCC_CONFIG_PATH: "/etc/openclaw/installation/installation.yaml" },
    encoding: "utf8",
    timeout: 45_000,
  });
  if (check.error || check.status !== 0 || !check.stdout?.includes("installation-startup-ready")) {
    throw new Error("pinned upstream startup check failed");
  }
  process.stdout.write("openclaw-enterprise-preflight-ready\n");
}

run().catch((error) => {
  process.stderr.write(`openclaw-enterprise-preflight: ${error.message}\n`);
  process.exitCode = 1;
});
