def known($values):
  . as $value | if $values | index($value) then $value else "Unknown" end;

def sync: known(["Synced", "OutOfSync"]);
def health: known(["Healthy", "Progressing", "Degraded", "Suspended", "Missing"]);

select(.kind == "Application" and .metadata.namespace == "argocd" and .metadata.name == "mastodon") |
.status | {
  revision_matches: (.sync.revision == $revision),
  sync: (.sync.status | sync),
  health: (.health.status | health),
  operation: (.operationState.phase | known(["Running", "Succeeded", "Failed", "Error", "Terminating"])),
  conditions: [(.conditions // [])[] | .type | known([
    "ComparisonError", "SyncError", "InvalidSpecError", "SharedResourceWarning", "RepeatedResourceWarning"
  ])] | unique,
  resources: [(.resources // [])[] | select(.status == "OutOfSync" or (.health.status // "Healthy") != "Healthy") | {
    kind: (.kind | known([
      "CronJob", "Deployment", "ExternalSecret", "Job", "PersistentVolumeClaim", "Service", "StatefulSet"
    ])),
    sync: (.status | sync),
    health: (.health.status | health)
  }] | unique
}
