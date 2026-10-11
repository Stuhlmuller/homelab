# Data Model: Actions Controls

| Entity | Key fields | Constraint |
| --- | --- | --- |
| Workflow trigger | Workflow filename, event, branch/path filters | Required PR context producers keep an applicable PR event. |
| Required context | Exact context, integration ID, ruleset ID | All seven declared contexts appear on a representative protected PR. |
| Environment | Name, reviewer rule, branch policy | Only `homelab-plan` reviewer changes; credentials and `homelab-production` remain intact. |
| Dispatch | Workflow, expected SHA, branch guard | Existing exact-main-SHA and permission boundaries remain. |

Transitions: optional PR/schedule event present → absent after workflow merge; plan reviewer present → absent after github-iac reconcile. A failed required-context verification blocks completion, not merge-rule weakening.
