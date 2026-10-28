#!/usr/bin/env python3
"""Keep the staged SC-001 assembler Job private, offline, and inert."""

from pathlib import Path
import unittest


APP = Path(__file__).resolve().parents[2] / "clusters/homelab/apps/renovate"


class ScheduleJob(unittest.TestCase):
    def test_job_is_suspended_and_has_only_the_generated_output_mount_writable(self):
        job = (APP / "acceptance-schedule-assemble-job.yaml").read_text()
        policy = (APP / "acceptance-schedule-assemble-networkpolicy.yaml").read_text()
        kustomization = (APP / "kustomization.yaml").read_text()
        self.assertIn("kind: Job", job)
        self.assertRegex(job, r"(?m)^  suspend: true$")
        self.assertIn("automountServiceAccountToken: false", job)
        self.assertIn("serviceAccountName: renovate", job)
        self.assertIn("sidecar.istio.io/inject: \"false\"", job)
        self.assertIn("readOnlyRootFilesystem: true", job)
        self.assertIn("runAsUser: 12021", job)
        self.assertIn("kubernetes.io/hostname: acer", job)
        self.assertRegex(job, r"image: docker\.io/library/python:3\.13-bookworm@sha256:[0-9a-f]{64}")
        self.assertIn("command: [python3, -I, -B, /usr/local/bin/renovate-acceptance-schedule-assemble.py]", job)
        self.assertIn("REPLACE_WITH_REVIEWED_UTC_HOUR", job)
        self.assertRegex(job, r"mountPath: /schedule\n\s+subPath: private/schedule\n\s+readOnly: true")
        self.assertRegex(job, r"mountPath: /assembled\n\s+subPath: private/schedule/assembled")
        self.assertEqual(job.count("claimName: renovate-acceptance-ledger"), 1)
        self.assertNotRegex(job, r"(?m)^\s+(?:secretName:|env:|envFrom:|hostAliases:)")
        self.assertNotIn("claimName: renovate-cache", job)
        self.assertNotIn("- acceptance-schedule-assemble-job.yaml", kustomization)
        self.assertIn("- acceptance-schedule-assemble-networkpolicy.yaml", kustomization)
        for source in ("renovate-acceptance-schedule.py",
                       "renovate-acceptance-schedule-assemble.py"):
            self.assertIn(f"- {source}", kustomization)
            self.assertIn(f"subPath: {source}", job)
            self.assertTrue((APP / source).is_file())
        self.assertIn("policyTypes: [Ingress, Egress]", policy)
        self.assertIn("app.kubernetes.io/name: renovate-acceptance-schedule-assemble", policy)
        self.assertRegex(policy, r"(?m)^  ingress: \[\]$")
        self.assertRegex(policy, r"(?m)^  egress: \[\]$")
        self.assertNotRegex(policy, r"(?m)^\s+- to:")


if __name__ == "__main__":
    unittest.main()
