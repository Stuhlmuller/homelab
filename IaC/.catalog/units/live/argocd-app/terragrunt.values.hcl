# Shape-only fixture for `terragrunt hcl validate` on the catalog template.
# Stack generation replaces it with app inputs from IaC/stacks/<app>/stack.hcl.
defaults = {
  repo_url        = "https://example.invalid/fixture.git"
  target_revision = "main"
  source_root     = "fixture"
  manifest = {
    metadata = { labels = {} }
    spec = {
      destination = {}
      syncPolicy = {
        automated = {}
        retry     = { backoff = {} }
      }
    }
  }
}
