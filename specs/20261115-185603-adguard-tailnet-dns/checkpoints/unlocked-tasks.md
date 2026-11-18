# Unlocked-tailnet task generation

Stage: task generation complete; stop before separate analysis/implementation.

Applied `.agents/skills/speckit-tasks/SKILL.md` after the independent requirements
review recorded CHK001–012 passing in `unlocked-review.md`. The setup helper
resolved this existing feature and `.specify/templates/tasks-template.md`;
spec, plan, research, data model, contract, quickstart and constitution informed
the append. `.specify/extensions.yml` has `hooks: {}`: no before/after hook runs.

Appended T048–T055 to `../tasks.md` without replacing historical tasks or changing
any existing checkbox. Eight new unchecked tasks: US1 two (T048–T049), US2
two (T050–T051), cross-cutting four (T052–T055). The file now has 55 task IDs.
Each appended task has a checkbox, sequential ID, applicable story label and
explicit repository path. No task is marked [P]; shared files and coordinated documentation stay sequential.

FR-020 maps to T048–T049/T052–T055. FR-021 maps to T048–T055 plus existing
T036–T039. SC-007 maps to T048–T051/T053/T055. US1 independently tests mode and
identity collection; US2 tests snapshot rejection and cutover no-apply on drift.
US3/US4 retain private admin and recovery gates. The source MVP includes US1,
US2 binding regressions, documentation and validation before protected delivery.

The appended interpretation explicitly supersedes only the unconditional
signing wording of historical T035 under FR-020/021: never sign when unlocked;
verify the observed mode and identity instead. It does not mark T035 or any
outstanding delivery/acceptance task complete. Mac direct/admin/recovery,
reviewed global cutover and post-cutover normal-client/exit-node evidence remain
actual operational work, not fixture substitutes.

No spec, design or implementation files were edited; no credentials inspected,
production checks run, or live state changed. Next owner: coordinator. Next
step: separate Spec Kit analysis of the amended artifacts and appended tasks;
implementation starts only in its later stage. No background runner is claimed.
