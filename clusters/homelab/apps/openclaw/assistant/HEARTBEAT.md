# Quiet follow-through

Review completed background work and explicitly recorded follow-ups. Surface
only a meaningful new outcome, a decision the owner needs to make, or a newly
blocked promise. Do not infer old tasks from conversation history.

Before notifying, read memory/homelab-status.json, memory/assistant-tasks.md, and today's note
(memory/YYYY-MM-DD.md, using the current America/Los_Angeles date) only if each
file exists. These are optional records: a missing file means no recorded
status, task, or daily note, not a failed check. Check existence before reading; never
pass an unchecked optional path to cat or batch it with required files. For
example, use `if [ -f "$path" ]; then cat -- "$path"; fi` for each optional
record. Do not create empty notes just to satisfy this check. Report actual
read/permission errors; do not hide them with `|| true`.

Deduplicate
against successful previous notifications and the morning briefing. Do not
launch a second investigation while one is already tracked. The scheduled
health watch owns polling and the improvement job owns maintenance.

If nothing needs the owner's attention, return exactly NO_REPLY. If something
does, give the observation, practical impact, and next action in a few natural
sentences. Never include NO_REPLY in a visible message.
