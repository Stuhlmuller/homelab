# CLI contract

```sh
python3 -I scripts/harbor-tailscale-production-sign.py \
  --identity apply --generation 2 --expires-at 2027-01-25T02:58:13Z \
  --signer-authority tlpub:257f1bcd25b8e90f63ce1fdced5e9232f8c79d9cf01f8e40806d636d4819ca1a
```

Default:read-only preview; no lock/cache/receipt writes.
--execute --allow-new-delegated-authority:explicitly gated one signing attempt.
--recover:only reconcile existing production receipt/capture; never sign.
Unknown identities/mismatched pins,actor,CLI/source/trust fail closed.

stdout:nonsecret JSON fields mode,identity,generation,expiry,signer/authority,
status,secret_installationfalse and old_authorities_removedfalse. No private
raw/wrapped key,provider output,CLI stderr or pending receipt content.

Exceptions/failures:fixed diagnostics only; nonzero exit retains evidence.
No retry/reset/retire/install/dispatch option exists. Existing intent blocks
execute even if current netmap has no new authority. Recovery errors cannot
prove no remote mutation. State is private0600/0700 with exclusive cache lock.
