"""Bazel test outputs are keyed by the exact Nix derivation and cache policy."""

def _nix_checks_repository(ctx):
    inputs = ctx.getenv("HOMELAB_BAZEL_CHECKS")
    if not inputs:
        fail("Run nix run .#bazel-offline to resolve the Nix check inputs.")
    recipes = json.decode(ctx.read(ctx.path(inputs)))
    for name, recipe in recipes.items():
        ctx.file(name, "\n".join(recipe) + "\n")
    ctx.file("BUILD.bazel", "exports_files(%s)\n" % repr(sorted(recipes.keys())))

nix_checks_repository = repository_rule(
    implementation = _nix_checks_repository,
)

def _nix_check_test(ctx):
    launcher = ctx.actions.declare_file(ctx.label.name + ".sh")
    ctx.actions.expand_template(
        template = ctx.file._launcher,
        output = launcher,
        substitutions = {"@RECIPE@": ctx.file.recipe.short_path},
        is_executable = True,
    )
    return [DefaultInfo(
        executable = launcher,
        runfiles = ctx.runfiles(files = [ctx.file.recipe]),
    )]

nix_check_test = rule(
    implementation = _nix_check_test,
    test = True,
    attrs = {
        "recipe": attr.label(allow_single_file = True, mandatory = True),
        "_launcher": attr.label(default = "//bazel:run-nix-check.sh", allow_single_file = True),
    },
)
