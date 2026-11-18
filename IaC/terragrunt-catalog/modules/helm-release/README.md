# Helm release

Root module copied from the repository-owned catalog at
`19df2cb291eef0084cafb85bed644dcdb082108c`. Resource configuration, inputs,
outputs and provider constraints are unchanged; state encryption is generated
by the shared Terragrunt root. Keeping `helm_release.this` at the root preserves
the existing bootstrap state address.

The bootstrap Argo CD unit demonstrates usage. Do not wrap this module in a
child module without an explicit state-address migration.
