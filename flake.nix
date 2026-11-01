{
  description = "Development shell for operating the homelab";

  inputs = {
    nixpkgs.url = "github:NixOS/nixpkgs/nixos-unstable";
  };

  outputs =
    { self, nixpkgs, ... }:
    let
      xerjVersion = "1.0.0-rc.96";
      xerjArchives = {
        aarch64-darwin = {
          target = "aarch64-apple-darwin";
          hash = "sha256-UUSRo2AY4osJ35JIeroAPx30QBUR372d/RFTokxGHXs=";
        };
        x86_64-darwin = {
          target = "x86_64-apple-darwin";
          hash = "sha256-eSesQYPMjKftiujdYlgEcr/YUi0Xsi9JaDZUm7JhYsM=";
        };
        aarch64-linux = {
          target = "aarch64-unknown-linux-musl";
          hash = "sha256-MntwU9stFbeWe98OojP2+HfNd+ZJapTrfZRAgRBdcd8=";
        };
        x86_64-linux = {
          target = "x86_64-unknown-linux-musl";
          hash = "sha256-AHuZKUDQLn7qnmVsWcdzka6MfeBptiAIZlZu8SMrM6E=";
        };
      };
      systems = [
        "aarch64-darwin"
        "aarch64-linux"
        "x86_64-darwin"
        "x86_64-linux"
      ];

      forEachSystem = nixpkgs.lib.genAttrs systems;
    in
    {
      packages = forEachSystem (
        system:
        let
          pkgs = import nixpkgs { inherit system; };
          archive = xerjArchives.${system};
        in
        {
          openwiki = pkgs.buildNpmPackage {
            pname = "homelab-openwiki";
            version = "0.7.0";
            src = ./builds/openwiki;
            npmDepsHash = "sha256-jz+cp/j9RCcW+v9idCrdvrXOOo5OXiBUSD26Ld1qQuk=";
            dontNpmBuild = true;
            nativeBuildInputs = [ pkgs.makeWrapper pkgs.patch ];
            installPhase = ''
              runHook preInstall
              mkdir -p "$out/libexec/openwiki" "$out/bin"
              cp -R node_modules "$out/libexec/openwiki/"
              substituteInPlace "$out/libexec/openwiki/node_modules/openwiki/dist/ingestion/code-mode.js" \
                --replace-fail '    await writeCodeModeAgentSnippets(cwd);' \
                '    if (options.createWorkflow) await writeCodeModeAgentSnippets(cwd);'
              patch -d "$out/libexec/openwiki/node_modules/openwiki" -p1 \
                < ${./builds/openwiki/durable-coverage.patch}
              makeWrapper ${pkgs.nodejs}/bin/node "$out/bin/openwiki" \
                --add-flags "$out/libexec/openwiki/node_modules/openwiki/dist/cli/cli.js"
              runHook postInstall
            '';
            meta.mainProgram = "openwiki";
          };
          xerj = pkgs.stdenvNoCC.mkDerivation {
            pname = "xerj";
            version = xerjVersion;
            src = pkgs.fetchurl {
              url = "https://github.com/xerj-org/xerj/releases/download/v${xerjVersion}/xerj-${xerjVersion}-${archive.target}.tar.gz";
              inherit (archive) hash;
            };
            dontStrip = true;
            installPhase = ''
              mkdir -p "$out/bin"
              cp xerj "$out/bin/xerj"
              chmod 755 "$out/bin/xerj"
            '';
            meta.mainProgram = "xerj";
          };
        }
      );

      apps = forEachSystem (
        system:
        let
          pkgs = import nixpkgs { inherit system; };
          validate = pkgs.writeShellApplication {
            name = "validate";
            runtimeInputs = self.devShells.${system}.default.nativeBuildInputs ++ [
              (pkgs.lib.getBin pkgs.postgresql_14)
              (pkgs.lib.getBin pkgs.postgresql_18)
            ];
            text = ''
              (cd IaC && terragrunt stack generate)
              terragrunt hcl fmt --check
              terragrunt hcl validate
              bash scripts/ci/static-checks.sh
              bash scripts/ci/conftest-policies.sh
            '';
          };
        in
        {
          openwiki = {
            type = "app";
            program = "${self.packages.${system}.openwiki}/bin/openwiki";
            meta.description = "Run the pinned OpenWiki MCP with repository agent-policy preservation";
          };
          validate = {
            type = "app";
            program = "${validate}/bin/validate";
            meta.description = "Run local homelab validation";
          };
        }
      );

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
                # mkShell exposes PostgreSQL dev outputs here; restore fixtures
                # also need both server/client bin outputs in the check sandbox.
                nativeBuildInputs = tools ++ [
                  (pkgs.lib.getBin pkgs.postgresql_14)
                  (pkgs.lib.getBin pkgs.postgresql_18)
                ];
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
          openwiki-setup = pkgs.runCommand "homelab-openwiki-setup-test" {
            nativeBuildInputs = [ pkgs.nodejs pkgs.git ];
          } ''
            node ${./scripts/ci/openwiki-package-test.mjs} ${self.packages.${system}.openwiki}
            mkdir "$out"
            printf 'passed\n' > "$out/result"
          '';
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
            markdownlint-cli
            miniupnpc
            nixVersions.latest
            nodejs
            opentofu
            openssh
            openssl
            pre-commit
            postgresql_14
            postgresql_18
            prometheus.cli
            python3
            regctl
            ripgrep
            ruff
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
          xerj = pkgs.mkShell {
            packages = basePackages ++ checkovPackages ++ localePackages ++ [ self.packages.${system}.xerj ];
          };
        }
      );
    };
}
