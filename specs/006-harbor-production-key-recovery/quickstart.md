# Local checks and future approval commands

Preparation only; these signing/recovery commands have NOT been executed live.

Run now with inert fixtures only:
```sh
python3 -I scripts/ci/harbor-tailscale-production-sign-test.py
```

After separate source publication/review/merge and fresh preview, the exact
proposed signing invocation, also exercised with mocked external operations:
```sh
nix develop --command python3 -I scripts/harbor-tailscale-production-sign.py \
  --execute --allow-new-delegated-authority --identity apply --generation 2 \
  --expires-at 2027-01-25T02:58:13Z \
  --signer-authority tlpub:257f1bcd25b8e90f63ce1fdced5e9232f8c79d9cf01f8e40806d636d4819ca1a
```

This WOULD create one persistent delegated authority and append one protected
production cache record. It is NOT approval to execute. Requires clean signed
currentmain,approved actor,the exact installed CLI and valid pinned provider key.
Existing apply capability includes cluster-admin and ingress/operatorTCP443.

For approved local reconciliation after an uncertain outcome, same pins with
--recover instead of --execute --allow-new-delegated-authority. Recovery never
signs. Missing/partial output,unpropagated/changed trust or cache conflict stops;
retain receipts and request exact recovery/retirement review. Never clear intent
or rerun execute. No command here publishes a secret or revokes an authority.

Only after receipt/public-authority review can a separate approval authorize
homelab-production/TAILSCALE_AUTH_KEY installation. Protected mirror dispatch,
backup/isolated restore evidence and1752 deployment remain independent gates.
