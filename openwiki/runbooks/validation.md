---
type: runbook
title: "Validation"
description: "Canonical validation runbook and focused Terragrunt, Kubernetes render, policy, secret-scan, and live readiness checks."
tags: ["runbook", "validation", "operations"]
---

# Validation

Canonical runbook: [`docs/validation-runbook.md`](../../docs/validation-runbook.md)

Run the smallest gate that proves the change before mutation. Terragrunt HCL,
rendered Kubernetes sources, Conftest policy, secret scanning, and focused live
readiness checks remain the normal layers.

See [Validation Gates](../operations/validation-gates.md).
