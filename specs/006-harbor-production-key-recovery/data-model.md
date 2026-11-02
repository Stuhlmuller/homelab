# Production recovery records

Existing provider entry: fixed apply,2,2027-01-25T02:58:13Z,tag,properties and
private raw key. Read from encrypted state; never print or persist raw output.

Existing cache:list of opaque records. Preserve all previous records; append one
apply record only after complete trust/output proof. No other identity operation.

Production receipt ci-production-signing-receipt.json:0600 in0700 directory;
identity,generation,expiry,key fingerprint,source SHA,approved signer,node ID,
trust-before snapshot including metadata and vote weights,cache-before hash,start time,phase and observed completion. If
killed before completion is recorded,recovery supplies its observation as the
upper time bound; provider/Mac/trust/output proof remains mandatory. After verification:
new public authority and expected cache-after hash. Phasecomplete stays retained.

Capture ci-production-signing-output.txt:0600,created exclusively and fsynced
before child runs; stdout goes directly here. Contains private wrapped key.
Never print/upload it. Missing/partial capture makes signing outcome uncertain.

Transitions:intent -> verified -> complete. No state transitions authorize
another signing attempt. Cache-after hash permits completion after interruption
between cache commit and complete receipt. Other cache changes are conflicts.
