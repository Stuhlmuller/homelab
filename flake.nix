{
  description = "Development shell for operating the homelab";

  inputs = {
    nixpkgs.url = "github:NixOS/nixpkgs/nixos-unstable";
  };

  outputs =
    { self, nixpkgs, ... }:
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
      checks = forEachSystem (
        system:
        let
          pkgs = import nixpkgs { inherit system; };
          # A complete tracked tree keeps fixtures and configuration in the key.
          source = builtins.path {
            path = ./.;
            name = "homelab-source";
            filter = path: _type: builtins.baseNameOf path != ".git";
          };
          tools = self.devShells.${system}.default.nativeBuildInputs;
          check =
            name: command:
            pkgs.runCommand name
              {
                nativeBuildInputs = tools;
                __darwinAllowLocalNetworking = true;
              }
              ''
                export HOME="$TMPDIR/home"
                mkdir -p "$HOME"
                cp -R ${source} source
                chmod -R u+w source
                cd source
                # Bind fixture tools and their copied helpers to sandbox interpreters.
                while IFS= read -r -d $'\0' fixture; do
                  substituteInPlace "$fixture" \
                    --replace-quiet "/usr/bin/env" "${pkgs.coreutils}/bin/env" \
                    --replace-quiet "/bin/bash" "${pkgs.bash}/bin/bash"
                done < <(find scripts -name '*.py' -print0)
                # Clone-based fixtures need Git objects, never the operator's history.
                git init -q -b main
                git add --all --force
                git -c user.name=Fixture -c user.email=fixture@example.invalid \
                  -c commit.gpgsign=false commit -qm fixture
                ${command}
                mkdir "$out"
                printf 'passed\n' > "$out/result"
              '';
        in
        {
          offline-tests = check "homelab-offline-tests" "bash scripts/ci/offline-checks.sh";
          manifest-policy = check "homelab-manifest-policy" "bash scripts/ci/conftest-policies.sh";
        }
      );

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
            cosign
            curl
            findutils
            gh
            git
            gnupg
            gitleaks
            gnugrep
            gnused
            gnutar
            go_1_25
            gzip
            jq
            k9s
            kubernetes-helm
            kind
            kubectl
            kustomize
            lua5_1
            miniupnpc
            nixVersions.latest
            nodejs
            opentofu
            openssh
            openssl
            pre-commit
            postgresql_14
            prometheus.cli
            python3
            ripgrep
            ruby
            shellcheck
            shfmt
            skopeo
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
          # PostgreSQL restore fixtures require a real non-C locale on Linux.
          localePackages = pkgs.lib.optionals pkgs.stdenv.isLinux [ pkgs.glibcLocales ];
        in
        {
          default = pkgs.mkShell {
            packages = basePackages ++ checkovPackages ++ localePackages;
          };
        }
      );
    };
}
