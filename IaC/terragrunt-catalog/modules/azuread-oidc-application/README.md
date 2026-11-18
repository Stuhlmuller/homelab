# Application registration with SSO parameters

Preserves the root resource addresses of the previous generated configuration.
The application implementation comes from the repository-owned catalog at
`19df2cb291eef0084cafb85bed644dcdb082108c`, with the same provider versions.
The module owns application, password, owner lookup and parameter resources.
The shared Terragrunt root owns state encryption and its persisted metadata alias.
Live identity declarations own names, redirect URLs, roles and parameter contracts.

Examples live in `IaC/homelab/us-west-2/apps/grafana/identity.hcl` and
`IaC/homelab/us-west-2/apps/octelium/identity.hcl`.
Moving these resources into a child module would change their state addresses.
