let
  lock = builtins.fromJSON (builtins.readFile ./flake.lock);
  pkgs = import (builtins.fetchTree lock.nodes.nixpkgs.locked) {
    system = "x86_64-linux";
  };
in
pkgs.buildEnv {
  name = "cordium-runner-tools";
  pathsToLink = [ "/bin" ];
  paths = with pkgs; [
    actionlint
    awscli2
    bash
    cosign
    curl
    gh
    git
    gitleaks
    go_1_25
    jq
    kubectl
    kubernetes-helm
    kustomize
    nixVersions.latest
    nodejs_24
    openssh
    opentofu
    python313
    regctl
    ripgrep
    shellcheck
    skopeo
    sops
    terragrunt
    yq-go
  ];
}
