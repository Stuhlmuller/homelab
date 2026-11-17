# T043 saved-plan provider binding

Separate cutover convergence found DNS value/address validation did not bind the
compiled plan's provider to the administrator identity used for live reads.
AppendedT043 HIGH partial FR008/013/019; no spec/plan change. Added negative cases
first (8 failures), then required the plan DNS resource's referenced provider to
be root/default tailscale0.29.2 at the official registry, with exactly the two
existing administrator OAuth file constant expressions. Reject aliases, child
module providers, different credentials, endpoint/tailnet/API-key overrides,
unknown expressions, missing config and version drift. No credential values read.

Consulted official OpenTofu JSON-format provider/expression sections at
<https://opentofu.org/docs/internals/json-format/> (local upstream/opentofu-json-format.html).
Provider map keys are explicitly opaque: resolve the resource's key and validate
the referenced provider, rather than requiring a literal key name. Added positive
opaque-key fixture and alias/module negatives. All15 cutover tests pass;
git diff --check passes. Logs adguard-provider-red.log/adguard-provider-final.log.
Actual administrator saved-plan inspection remains liveT038; fixture success is
not proof of a live plan. Current source provider expressions were traced in the
operator unit. T043 complete; next separate scoped provider-binding convergence,
then rollbackT025/T026 and remainingclient/recovery work. No livechanges/Notion.
