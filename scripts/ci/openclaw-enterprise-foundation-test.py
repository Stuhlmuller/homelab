#!/usr/bin/env python3
"""Check the dormant Enterprise namespace and secret boundary."""

import json
import shlex
import subprocess
import tempfile
import unittest
from pathlib import Path


ROOT = Path(__file__).resolve().parents[2]
FOUNDATION = ROOT / "clusters/homelab/apps/openclaw-enterprise-foundation"
STORE = ROOT / "clusters/homelab/apps/external-secrets/cluster-secret-store.yaml"


def documents(yaml_text):
    return json.loads(subprocess.run(
        ["yq", "ea", "-o=json", "-I=0", "[.]", "-"], input=yaml_text,
        text=True, check=True, capture_output=True).stdout)


class FoundationContract(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        rendered = subprocess.check_output(
            ["kubectl", "kustomize", str(FOUNDATION)], text=True)
        cls.resources = {(item["kind"], item["metadata"]["name"]): item
                         for item in documents(rendered)}

    def test_existing_namespace_is_adoptable_but_not_policy_owned(self):
        agent = self.resources["Namespace", "openclaw-agents"]["metadata"]
        self.assertEqual(agent["annotations"]["openclaw.dev/namespace-lifecycle"], "external")
        for name in ("openclaw-system", "openclaw-agents"):
            metadata = self.resources["Namespace", name]["metadata"]
            self.assertEqual(metadata["annotations"]["argocd.argoproj.io/sync-wave"], "-10")
            labels = metadata["labels"]
            for mode in ("enforce", "audit", "warn"):
                self.assertEqual(labels[f"pod-security.kubernetes.io/{mode}"], "restricted")
            self.assertNotIn("istio.io/dataplane-mode", labels)
        policies = [item for (kind, _), item in self.resources.items()
                    if kind == "NetworkPolicy"]
        self.assertEqual({item["metadata"]["name"] for item in policies}, {
            "openclaw-system-default-deny-ingress", "occ-postgres-ingress",
            "occ-postgres-restore-drill-isolation"})
        self.assertTrue(all(item["metadata"]["namespace"] == "openclaw-system"
                            for item in policies))
        self.assertEqual(self.resources["NetworkPolicy", "openclaw-system-default-deny-ingress"]["spec"],
                         {"podSelector": {}, "policyTypes": ["Ingress"]})
        ingress = self.resources["NetworkPolicy", "occ-postgres-ingress"]["spec"]
        self.assertEqual(ingress["podSelector"], {"matchLabels": {"app.kubernetes.io/name": "occ-postgres"}})
        self.assertEqual(ingress["ingress"], [{"from": [{"podSelector": {
            "matchLabels": {"app.kubernetes.io/name": "openclaw-enterprise"},
            "matchExpressions": [{"key": "app.kubernetes.io/component", "operator": "In",
                                  "values": ["api", "worker", "initialization"]}]}},
            {"podSelector": {"matchLabels": {"app.kubernetes.io/name": "occ-postgres-backup"}}}],
            "ports": [{"protocol": "TCP", "port": 5432}]}])
        self.assertEqual(self.resources["NetworkPolicy", "occ-postgres-restore-drill-isolation"]["spec"],
                         {"podSelector": {"matchLabels": {
                             "app.kubernetes.io/name": "occ-postgres-restore-drill"}},
                          "policyTypes": ["Ingress", "Egress"]})

    def test_postgres_is_retained_tls_only_and_waits_for_local_claim(self):
        service = self.resources["Service", "occ-postgres"]["spec"]
        self.assertEqual(service["clusterIP"], "10.96.0.51")
        workload = self.resources["StatefulSet", "occ-postgres"]["spec"]
        self.assertEqual(workload["replicas"], 1)
        self.assertEqual(workload["persistentVolumeClaimRetentionPolicy"], {
            "whenDeleted": "Retain", "whenScaled": "Retain"})
        claim = workload["volumeClaimTemplates"][0]
        self.assertEqual(claim["metadata"]["name"], "occ-postgres")
        self.assertEqual(claim["spec"], {"accessModes": ["ReadWriteOnce"],
                                         "storageClassName": "openclaw-enterprise-postgres-local",
                                         "resources": {"requests": {"storage": "10Gi"}}})
        pod = workload["template"]["spec"]
        self.assertNotIn("nodeSelector", pod)
        self.assertFalse(pod["automountServiceAccountToken"])
        self.assertEqual(pod["securityContext"]["runAsUser"], 999)
        container = pod["containers"][0]
        digest = "afc7e2d441324c0388fa80c3d24f733b4194a4eb7f47dd8ee2b08eb1a24a647c"
        image = ("harbor.stinkyboi.com/mirror/docker.io/library/postgres:"
                 f"{digest}@sha256:{digest}")
        self.assertEqual(container["image"], image)
        self.assertIn("ssl=on", container["args"])
        self.assertIn("ssl_min_protocol_version=TLSv1.3", container["args"])
        self.assertIn("hba_file=/etc/occ-postgres/pg_hba.conf", container["args"])
        self.assertIn("password_encryption=scram-sha-256", container["args"])
        self.assertEqual(container["securityContext"]["readOnlyRootFilesystem"], True)
        hba = self.resources["ConfigMap", "occ-postgres-hba"]["data"]["pg_hba.conf"]
        self.assertIn("hostnossl all all 0.0.0.0/0 reject", hba)
        self.assertIn("hostssl all occ_admin 0.0.0.0/0 reject", hba)
        self.assertIn("hostssl openclaw_enterprise occ_app 10.244.0.0/16 scram-sha-256", hba)
        self.assertNotIn("host all all 0.0.0.0/0 trust", hba)
        bootstrap = next(item for (kind, name), item in self.resources.items()
                         if kind == "ConfigMap" and name.startswith("occ-postgres-bootstrap-"))
        self.assertEqual(bootstrap["data"]["database-bootstrap.sql"],
                         (FOUNDATION / "database-bootstrap.sql").read_text())
        sql = bootstrap["data"]["database-bootstrap.sql"]
        self.assertIn("CREATE SCHEMA IF NOT EXISTS occ AUTHORIZATION occ_migrator", sql)
        self.assertIn("CREATE SCHEMA IF NOT EXISTS drizzle AUTHORIZATION occ_migrator", sql)
        self.assertIn("GRANT CONNECT, CREATE ON DATABASE openclaw_enterprise TO occ_migrator", sql)
        self.assertNotIn("GRANT SELECT, INSERT, UPDATE, DELETE ON TABLES", sql)
        self.assertTrue(sql.rstrip().endswith(
            "COMMENT ON DATABASE openclaw_enterprise IS 'occ-bootstrap-v1';"))
        readiness = container["readinessProbe"]["exec"]["command"][2]
        self.assertIn("shobj_description(oid, 'pg_database') = 'occ-bootstrap-v1'", readiness)
        self.assertIn("| grep -qx 1", readiness)
        self.assertEqual(next(volume["configMap"]["name"] for volume in pod["volumes"]
                              if volume["name"] == "bootstrap"), bootstrap["metadata"]["name"])
        jobs = {name: item for (kind, name), item in self.resources.items() if kind == "Job"}
        self.assertEqual(set(jobs), {"occ-operations-journal-probe"})
        self.assertTrue(jobs["occ-operations-journal-probe"]["spec"]["suspend"])

    def test_postgres_cert_renewal_invalidates_health_probes_until_restart(self):
        container = self.resources["StatefulSet", "occ-postgres"]["spec"]["template"]["spec"]["containers"][0]
        start = container["command"]
        self.assertEqual(start[:2], ["/bin/sh", "-ec"])
        self.assertEqual(start[3], "postgres-tls-snapshot")
        self.assertIn('exec /usr/local/bin/docker-entrypoint.sh postgres "$@"', start[2])
        self.assertNotIn("lifecycle", container)
        with tempfile.TemporaryDirectory() as directory:
            cert = Path(directory) / "tls.crt"
            key = Path(directory) / "tls.key"
            marker = Path(directory) / "startup-tls.sha256"
            entrypoint = Path(directory) / "docker-entrypoint.sh"
            rotate = Path(directory) / "rotate-during-start"
            cert.write_text("original certificate")
            key.write_text("original key")
            entrypoint.write_text(
                "#!/bin/sh\nset -eu\n"
                f"test -s {shlex.quote(str(marker))}\n"
                'test "$1" = postgres && test "$2" = -c\n'
                f"if test -e {shlex.quote(str(rotate))}; then "
                f"printf renewed-during-start > {shlex.quote(str(key))}; fi\n")
            entrypoint.chmod(0o700)

            def localize(script):
                return (script.replace("/run/postgres-tls/tls.crt", str(cert))
                        .replace("/run/postgres-tls/tls.key", str(key))
                        .replace("/tmp/occ-postgres-startup-tls.sha256", str(marker))
                        .replace("/usr/local/bin/docker-entrypoint.sh", str(entrypoint)))

            def restart():
                subprocess.run(["/bin/sh", "-ec", localize(start[2]),
                                start[3], *container["args"]], check=True)

            def probe_result(name):
                command = container[name]["exec"]["command"]
                self.assertEqual(command[:2], ["/bin/sh", "-ec"])
                check, separator, postgres = command[2].partition("\n")
                self.assertTrue(separator and "psql" in postgres and "SELECT 1" in postgres)
                return subprocess.run(["/bin/sh", "-ec", localize(check)],
                                      capture_output=True, text=True).returncode

            restart()
            for name in ("readinessProbe", "livenessProbe"):
                self.assertEqual(probe_result(name), 0)
            key.write_text("renewed key")
            for name in ("readinessProbe", "livenessProbe"):
                self.assertNotEqual(probe_result(name), 0)
            restart()
            for name in ("readinessProbe", "livenessProbe"):
                self.assertEqual(probe_result(name), 0)
            cert.write_text("renewed certificate")
            for name in ("readinessProbe", "livenessProbe"):
                self.assertNotEqual(probe_result(name), 0)
            restart()
            for name in ("readinessProbe", "livenessProbe"):
                self.assertEqual(probe_result(name), 0)
            rotate.touch()
            restart()
            for name in ("readinessProbe", "livenessProbe"):
                self.assertNotEqual(probe_result(name), 0)

    def test_tenant_roles_follow_fixed_oce_release(self):
        expected = {
            "openclaw-enterprise-worker": ("worker", "worker"),
            "openclaw-enterprise-api-secrets": ("api", "api"),
            "openclaw-enterprise-api-configuration": ("api", "configuration"),
        }
        roles = {name: item for (kind, name), item in self.resources.items()
                 if kind == "RoleBinding"}
        self.assertEqual(set(roles), set(expected))
        for name, (account, suffix) in expected.items():
            role = roles[name]
            self.assertEqual(role["metadata"]["namespace"], "openclaw-agents")
            self.assertEqual(role["roleRef"], {
                "apiGroup": "rbac.authorization.k8s.io", "kind": "ClusterRole",
                "name": f"oce-openclaw-tenant-{suffix}"})
            self.assertEqual(role["subjects"], [{
                "kind": "ServiceAccount", "name": f"openclaw-enterprise-{account}",
                "namespace": "openclaw-system"}])

    def test_postgres_ca_is_private_retained_and_matches_verified_url(self):
        root = self.resources["Certificate", "occ-postgres-root"]
        self.assertEqual(root["metadata"]["namespace"], "openclaw-system")
        self.assertEqual(root["metadata"]["annotations"]["argocd.argoproj.io/sync-options"],
                         "Prune=false")
        self.assertEqual(root["spec"]["secretName"], "occ-postgres-root")
        self.assertTrue(root["spec"]["isCA"])
        self.assertEqual(root["spec"]["privateKey"]["rotationPolicy"], "Never")
        self.assertEqual(root["spec"]["issuerRef"], {
            "name": "occ-postgres-selfsigned", "kind": "Issuer"})
        ca = self.resources["Issuer", "occ-postgres-ca"]
        self.assertEqual(ca["spec"]["ca"]["secretName"], "occ-postgres-root")
        server = self.resources["Certificate", "occ-postgres-server"]
        self.assertEqual(server["spec"]["secretName"], "occ-postgres-server-tls")
        self.assertEqual(server["spec"]["dnsNames"], [
            "occ-postgres.openclaw-system.svc.cluster.local"])
        self.assertEqual(server["spec"]["issuerRef"], {
            "name": "occ-postgres-ca", "kind": "Issuer"})
        self.assertEqual(server["spec"]["usages"], ["server auth"])

    def test_secret_projections_are_exact_and_rotation_is_declared(self):
        expected = {
            "occ-postgres-admin": ("openclaw-system", "password", "postgres-admin-password"),
            "occ-postgres-migrator": ("openclaw-system", "password", "postgres-migrator-password"),
            "occ-postgres-app": ("openclaw-system", "password", "postgres-app-password"),
            "occ-postgres-backup": ("openclaw-system", "password", "postgres-backup-password"),
            "occ-auth": ("openclaw-system", "secret", "session-auth-secret"),
            "occ-private-gateway-key": ("openclaw-system", "occ", "gateway-api-key"),
            "occ-model-api-key": ("openclaw-agents", "api-key", "model-api-key"),
        }
        secrets = {name: item for (kind, name), item in self.resources.items()
                   if kind == "ExternalSecret"}
        database = secrets.pop("occ-database")
        self.assertEqual(set(secrets), set(expected))
        for name, (namespace, key, parameter) in expected.items():
            secret = secrets[name]
            self.assertEqual(secret["metadata"]["namespace"], namespace)
            self.assertEqual(secret["metadata"]["annotations"], {
                "homelab.stuhlmuller.dev/generated-secret-revision": "v1"})
            spec = secret["spec"]
            self.assertEqual(spec["refreshPolicy"], "OnChange")
            self.assertEqual(spec["secretStoreRef"], {
                "kind": "ClusterSecretStore", "name": "aws-ssm"})
            self.assertEqual(spec["target"], {
                "name": name, "creationPolicy": "Owner", "deletionPolicy": "Retain"})
            self.assertEqual(spec["data"], [{
                "secretKey": key,
                "remoteRef": {"key": f"/homelab/openclaw-enterprise/{parameter}"}}])
        spec = database["spec"]
        self.assertEqual(database["metadata"]["namespace"], "openclaw-system")
        self.assertEqual(database["metadata"]["annotations"], {
            "homelab.stuhlmuller.dev/generated-secret-revision": "v1"})
        self.assertEqual(spec["refreshPolicy"], "OnChange")
        self.assertEqual(spec["secretStoreRef"], {
            "kind": "ClusterSecretStore", "name": "aws-ssm"})
        self.assertEqual(spec["data"], [
            {"secretKey": "app_password", "remoteRef": {
                "key": "/homelab/openclaw-enterprise/postgres-app-password"}},
            {"secretKey": "migrator_password", "remoteRef": {
                "key": "/homelab/openclaw-enterprise/postgres-migrator-password"}},
        ])
        target = spec["target"]
        self.assertEqual({key: target[key] for key in
                          ("name", "creationPolicy", "deletionPolicy")}, {
            "name": "occ-database", "creationPolicy": "Owner", "deletionPolicy": "Retain"})
        template = target["template"]
        self.assertEqual((template["engineVersion"], template["type"]), ("v2", "Opaque"))
        self.assertEqual(template["data"], {
            key: (f"postgresql://{role}:{{{{ .{source} }}}}"
                  "@occ-postgres.openclaw-system.svc.cluster.local:5432/openclaw_enterprise"
                  "?sslmode=verify-full&sslrootcert=/etc/openclaw/database-ca/tls.crt")
            for key, role, source in (
                ("application-url", "occ_app", "app_password"),
                ("migration-url", "occ_migrator", "migrator_password"),
            )
        })
        store = documents(STORE.read_text())[0]
        allowed = store["spec"]["conditions"][0]["namespaces"]
        self.assertLessEqual({"openclaw-system", "openclaw-agents"}, set(allowed))
        config = json.loads((ROOT / "scripts/config/openclaw-enterprise.json").read_text())
        self.assertFalse(config["activationEnabled"])


if __name__ == "__main__":
    unittest.main()
