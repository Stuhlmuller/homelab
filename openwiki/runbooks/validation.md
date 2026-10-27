---
type: runbook
title: "Validation"
description: "Canonical validation runbook and focused Terragrunt, Kubernetes render, policy, secret-scan, and live readiness checks."
tags: ["runbook", "validation", "operations"]
verified:
  - by: openwiki/0.7.0
    at: 2026-10-27T21:30:24.345Z
sources:
  - id: openwiki-source-3e9842ef0fb82f94aa54b1a9
    resource: repo://docs/validation-runbook.md
---

# Validation

Canonical runbook: [`docs/validation-runbook.md`](../../docs/validation-runbook.md)

Run the smallest gate that proves the change before mutation. Terragrunt HCL,
rendered Kubernetes sources, Conftest policy, secret scanning, and focused live
readiness checks remain the normal layers.

See [Validation Gates](../operations/validation-gates.md).
