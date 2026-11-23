# Draft delivery scheduling correction

User requests homelab CI/CD deployment. Publication prerequisite PR1851 is
awaiting its last required CI gate. Application source and local validation are
complete, including latest-main integration. Allow T031 source review and draft
PR creation after T030 so consumer CI can run independently; T003 remains a hard
prerequisite for ready state and T032 consuming merge. This aligns with plan's
publication-before-consuming-merge boundary. No runtime, image, authentication,
policy or functional acceptance gate changes. No task checkbox changes.

Next separate read-only analysis: verify this dependency correction against
spec/plan/tasks. Then perform T031 source review/draft delivery while continuing
PR1851, without claiming pending publication or deployment success. Current
watch49913 remainssoleowner. No new PR or dispatch from this scheduling pass.
