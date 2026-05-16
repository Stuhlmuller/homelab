{
  description = "Homelab infrastructure development and operations environment";

  inputs = {
    nixpkgs.url = "github:NixOS/nixpkgs/nixos-unstable";
    flake-utils.url = "github:numtide/flake-utils";
  };

  outputs =
    { nixpkgs, flake-utils, ... }:
    flake-utils.lib.eachDefaultSystem (
      system:
      let
        pkgs = import nixpkgs { inherit system; };
        python = pkgs.python3.withPackages (
          ps: with ps; [
            boto3
            botocore
            pre-commit
            pyyaml
          ]
        );
        commonPackages = with pkgs; [
          actionlint
          ansible
          awscli2
          bash
          consul
          coreutils
          curl
          findutils
          git
          gnugrep
          gnutar
          gzip
          nomad
          opentofu
          python
          terragrunt
          unzip
        ];
        app =
          name: text:
          {
            type = "app";
            program = "${pkgs.writeShellApplication {
              inherit name text;
              runtimeInputs = commonPackages;
            }}/bin/${name}";
          };
        terragruntWorkingDir = "terraform/live/homelab";
      in
      {
        devShells.default = pkgs.mkShell {
          packages = commonPackages;
          env = {
            TG_TF_PATH = "tofu";
            ANSIBLE_PLAYBOOK = "${python}/bin/ansible-playbook";
          };
        };

        apps = {
          default = app "homelab-validate" ''
            exec ./scripts/validate.sh "$@"
          '';
          validate = app "homelab-validate" ''
            exec ./scripts/validate.sh "$@"
          '';
          lint = app "homelab-lint" ''
            terragrunt hcl fmt --check --working-dir ${terragruntWorkingDir}
            nomad fmt -check nomad/jobs
            tofu fmt -check -recursive terraform
            ./scripts/validate-terraform.sh
            ./scripts/validate-nomad.sh
            python3 -m unittest discover -s tests -p 'test_*.py'
            python3 scripts/run_policy_fixtures.py
            ./scripts/validate-skills.sh
            ./scripts/validate-ansible-layout.sh
            ./scripts/validate-ansible.sh
          '';
          test = app "homelab-test" ''
            python3 -m unittest discover -s tests -p 'test_*.py'
            python3 scripts/run_policy_fixtures.py
            ./scripts/validate-skills.sh
            ./scripts/validate-ansible-layout.sh
          '';
          survey = app "homelab-survey" ''
            exec ./scripts/survey-cluster.sh "$@"
          '';
          format = app "homelab-format" ''
            terragrunt hcl fmt --working-dir ${terragruntWorkingDir}
            nomad fmt nomad/jobs
            tofu fmt -recursive terraform
          '';
          format-check = app "homelab-format-check" ''
            terragrunt hcl fmt --check --working-dir ${terragruntWorkingDir}
            nomad fmt -check nomad/jobs
            tofu fmt -check -recursive terraform
          '';
          validate-terraform = app "homelab-validate-terraform" ''
            exec ./scripts/validate-terraform.sh "$@"
          '';
          validate-nomad = app "homelab-validate-nomad" ''
            exec ./scripts/validate-nomad.sh "$@"
          '';
          validate-structure = app "homelab-validate-structure" ''
            python3 -m unittest discover -s tests -p 'test_*.py'
            python3 scripts/run_policy_fixtures.py
            ./scripts/validate-skills.sh
            ./scripts/validate-ansible-layout.sh
          '';
          validate-policy = app "homelab-validate-policy" ''
            exec python3 scripts/run_policy_fixtures.py "$@"
          '';
          validate-skills = app "homelab-validate-skills" ''
            exec ./scripts/validate-skills.sh "$@"
          '';
          ansible-syntax = app "homelab-ansible-syntax" ''
            exec ./scripts/validate-ansible.sh "$@"
          '';
          bootstrap = app "homelab-bootstrap" ''
            exec ansible-playbook -i ansible/inventories/production/hosts.yml ansible/playbooks/bootstrap.yml "$@"
          '';
          reconcile-tailscale = app "homelab-reconcile-tailscale" ''
            exec ansible-playbook -i ansible/inventories/production/hosts.yml ansible/playbooks/reconcile-tailscale.yml "$@"
          '';
          bootstrap-rolling = app "homelab-bootstrap-rolling" ''
            exec ./scripts/bootstrap-rolling.sh "$@"
          '';
          plan = app "homelab-plan" ''
            tf_path="''${TG_TF_PATH:-tofu}"
            exec terragrunt run --all --tf-path "''${tf_path}" plan --working-dir ${terragruntWorkingDir} "$@"
          '';
          apply = app "homelab-apply" ''
            tf_path="''${TG_TF_PATH:-tofu}"
            exec terragrunt run --all --non-interactive --tf-path "''${tf_path}" apply --working-dir ${terragruntWorkingDir} "$@"
          '';
          validate-ssm = app "homelab-validate-ssm" ''
            exec ./scripts/validate-aws-ssm.sh "$@"
          '';
          validate-kms = app "homelab-validate-kms" ''
            exec ./scripts/validate-aws-kms.sh "$@"
          '';
          validate-live-cluster = app "homelab-validate-live-cluster" ''
            exec ./scripts/validate-live-cluster.sh "$@"
          '';
          validate-live-workloads = app "homelab-validate-live-workloads" ''
            exec ./scripts/validate-live-workloads.sh "$@"
          '';
          validate-live = app "homelab-validate-live" ''
            ./scripts/validate-aws-ssm.sh
            ./scripts/validate-aws-kms.sh
            ./scripts/validate-live-cluster.sh
            ./scripts/validate-live-workloads.sh
          '';
          unlock-state = app "homelab-unlock-state" ''
            if [[ "$#" -eq 2 ]]; then
              exec ./scripts/unlock-terragrunt-unit.sh "$1" "$2"
            fi
            if [[ -n "''${UNIT:-}" && -n "''${LOCK_ID:-}" ]]; then
              exec ./scripts/unlock-terragrunt-unit.sh "''${UNIT}" "''${LOCK_ID}"
            fi
            echo "usage: nix run .#unlock-state -- <terragrunt-unit-path> <lock-id>" >&2
            exit 2
          '';
          deploy-live = app "homelab-deploy-live" ''
            exec ./scripts/deploy-live.sh "$@"
          '';
        };

        checks.validate = pkgs.runCommand "homelab-validate" { nativeBuildInputs = commonPackages; } ''
          cd ${./.}
          ./scripts/validate.sh
          touch "$out"
        '';
      }
    );
}
