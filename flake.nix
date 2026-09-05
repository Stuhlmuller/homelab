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
            lua5_1
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
