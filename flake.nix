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
          octeliumPackage =
            let
              version = "0.39.0";
              sources = {
                x86_64-linux = {
                  platform = "linux-amd64";
                  hash = "sha256-FzHbR38Oy9Puug5fud8fqxr8f78a76/Qb9ZqN91bu0w=";
                };
                aarch64-linux = {
                  platform = "linux-arm64";
                  hash = "sha256-VlzV35zR4UqMGtDHhJUhxtyLoSy+ixTMY5W+Bioi+k0=";
                };
                x86_64-darwin = {
                  platform = "darwin-amd64";
                  hash = "sha256-5/qUb/2iKTboIciG6PvEfXBmDdXL/yB7/I82eR9nXeM=";
                };
                aarch64-darwin = {
                  platform = "darwin-arm64";
                  hash = "sha256-paSdiKZKqDPffwhdZ2y/TT/J/lNYfmBoGYYKqVzBTwI=";
                };
              };
              source =
                sources.${system}
                  or (throw "Unsupported Octelium platform for ${system}");
            in
            pkgs.stdenv.mkDerivation {
              pname = "octelium";
              inherit version;
              sourceRoot = ".";

              src = pkgs.fetchurl {
                url = "https://github.com/octelium/octelium/releases/download/v${version}/octelium-${source.platform}.tar.gz";
                inherit (source) hash;
              };

              installPhase = ''
                runHook preInstall
                install -Dm755 octelium "$out/bin/octelium"
                runHook postInstall
              '';
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
            gnupg
            gnugrep
            gnused
            gnutar
            gzip
            httpie
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
            unzip
            yamllint
            yq-go
            octeliumPackage
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
