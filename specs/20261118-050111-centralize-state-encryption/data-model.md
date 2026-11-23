# Data and Configuration Model

## Shared policy

Root remote_state.encryption map fields: key_provider=aws_kms, kms_key_id=existing root key, region=existing state
region, key_spec=AES_256, encrypted_metadata_alias=key_provider.aws_kms.main, enforced=true. Fallback absent. Produces
one terraform encryption declaration beside existing backend in backend.tf. State and plan both use generated
aes_gcm.default and are enforced.

## Persisted records

Existing ciphertext retains provider metadata indexed by key_provider.aws_kms.main. Generated default provider uses
the alias to address that same metadata. Transition is old configuration → centralized configuration, with identical
key material and record identity. New ciphertext remains compatible with the old provider identity. No storage
migration.

## Input boundaries

Root retains public policy locals but no longer passes them as common module inputs. Modules expose only
resource-facing inputs. Runtime KMS references remain separate from client-side state protection. Retirement synthesis
inherits shared backend generation and contains no independent policy.
