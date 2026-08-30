{
  description = "Development shell for operating the homelab";

  inputs = {
    nixpkgs.url = "github:NixOS/nixpkgs/nixos-unstable";
  };

  outputs =
    { nixpkgs, ... }:
    let
      systems = [
        "aarch64-darwin"
        "aarch64-linux"
        "x86_64-darwin"
        "x86_64-linux"
      ];

      forEachSystem = nixpkgs.lib.genAttrs systems;
    in
    {
      devShells = forEachSystem (
        system:
        let
          pkgs = import nixpkgs {
            inherit system;
          };
          basePackages = with pkgs; [
            actionlint
            age
            argocd
            awscli2
            bash
            cloudflared
            conftest
            coreutils
            curl
            findutils
            gh
            git
            gitleaks
            gnugrep
            gnused
            gnutar
            gzip
            jq
            k9s
            kubernetes-helm
            kubectl
            kustomize
            miniupnpc
            nixVersions.latest
            opentofu
            openssh
            pre-commit
            ripgrep
            shellcheck
            shfmt
            sops
            talosctl
            terragrunt
            # Temporary scanner-only security pin; see validation-gates.md and #888.
            (
              (trivy.override {
                buildGoModule = buildGoModule.override {
                  go = go_1_26.overrideAttrs (
                    finalAttrs: _: {
                      version = "1.26.7";
                      src = fetchurl {
                        url = "https://go.dev/dl/go${finalAttrs.version}.src.tar.gz";
                        hash = "sha256-DtJOrHVRBQhbif6cq8J0K5GgrXuUtZ0602SRjryJVq0=";
                      };
                    }
                  );
                };
              }).overrideAttrs
              (
                finalAttrs: _: {
                  version = "0.74.0";
                  src = fetchFromGitHub {
                    owner = "aquasecurity";
                    repo = "trivy";
                    tag = "v${finalAttrs.version}";
                    hash = "sha256-OXOT8qwqh8Gy+IJcvBza5nai5bvNMcAMeeT+b2zuWDg=";
                  };
                  vendorHash = "sha256-ajXgC6CCw0IaS/e3k0wGNIUOs9mTBIEuV21ZnwZj7SQ=";
                }
              )
            )
            unzip
            yamllint
            yq-go
          ];
          checkovPackages = pkgs.lib.optionals (system != "x86_64-darwin") [
            pkgs.checkov
          ];
        in
        {
          default = pkgs.mkShell {
            packages = basePackages ++ checkovPackages;
          };
        }
      );
    };
}
