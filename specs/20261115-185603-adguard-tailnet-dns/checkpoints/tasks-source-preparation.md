# Task dependency correction: prepare source during publication

The plan delivery sequence and quickstart require successful publication before
consuming manifests merge. They do not require publication before writing or
testing unmerged source. The initial tasks graph unnecessarily made T004–007
source preparation wait for the whole publisher. Align the graph with the
existing intent; no requirement, design, runtime gate or task description changes.

T002 now precedes T004–007 source; T003 and T030 jointly precede T031 review,
then T032 protected consuming merge. T033–040 runtime/signing/DNS/client checks
retain their order. T003 stays open. All 40 task lines and their checkboxes are
byte-for-byte preserved (only T001/T002 complete); no source implementation or
application/DNS mutation occurred in this task correction.

Validation: setup_tasks resolves the existing feature/template; no extension
hooks; IDs/checklists/requirements mappings and all story criteria preserved.
Story tasks remain US1=8, US2=5, US3=4, US4=4, with shared/final tasks=19.
MVP still needs direct filtering plus private admin/recovery, followed by actual
client acceptance for the requested DNS outcome. Parallelism means source work
while the existing publication runs, not another writer or another publisher.

Next separate stage: read-only speckit-analyze on the corrected task dependency
graph. If clean, implement T004–007 while monitoring publisher43777917412.
Do not merge any consuming source until successful complete-pull evidence.
