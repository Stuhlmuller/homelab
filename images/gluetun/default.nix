{ pkgs }:
let
  # Keep the application and scanner on the same explicit compiler patch.
  go = pkgs.go_1_26.overrideAttrs (
    finalAttrs: _: {
      version = "1.26.7";
      src = pkgs.fetchurl {
        url = "https://go.dev/dl/go${finalAttrs.version}.src.tar.gz";
        hash = "sha256-DtJOrHVRBQhbif6cq8J0K5GgrXuUtZ0602SRjryJVq0=";
      };
    }
  );
  buildGoModule = pkgs.buildGoModule.override { inherit go; };
  source = pkgs.fetchFromGitHub {
    owner = "passteque";
    repo = "gluetun";
    rev = "3d1e20c5551e9cae1f9d938dc7b7214a6987f27e";
    hash = "sha256-75iE2fk74oDqRDhwsL2D6T/+4NO5pnQkXMRUl4ptSJk=";
  };
in
{
  inherit go;
  trivy = (pkgs.trivy.override { inherit buildGoModule; }).overrideAttrs (
    finalAttrs: _: {
      version = "0.74.0";
      src = pkgs.fetchFromGitHub {
        owner = "aquasecurity";
        repo = "trivy";
        tag = "v${finalAttrs.version}";
        hash = "sha256-OXOT8qwqh8Gy+IJcvBza5nai5bvNMcAMeeT+b2zuWDg=";
      };
      vendorHash = "sha256-ajXgC6CCw0IaS/e3k0wGNIUOs9mTBIEuV21ZnwZj7SQ=";
    }
  );
  binary =
    (buildGoModule {
      pname = "gluetun-candidate";
      version = "3.41.3-homelab.1";
      src = source;
      patches = [ ./dependencies.patch ];
      vendorHash = "sha256-fpntb3TC04QTJmduY97GKaI6JQl1bHX+WE8+U8qlQ/E=";
      subPackages = [ "cmd/gluetun" ];
      env.CGO_ENABLED = "0";
      # The deployed target is Linux/amd64. Darwin only cross-builds it; the
      # upstream tests and runtime fixtures are required on native Linux CI.
      doCheck = pkgs.stdenv.hostPlatform.system == "x86_64-linux";
      postBuild = ''
        if [ -d "$GOPATH/bin/linux_amd64" ]; then
          mv "$GOPATH/bin/linux_amd64/gluetun" "$GOPATH/bin/gluetun"
          rmdir "$GOPATH/bin/linux_amd64"
        fi
      '';
      ldflags = [
        "-s"
        "-w"
        "-X main.version=v3.41.3-homelab.1"
        "-X main.commit=3d1e20c5551e9cae1f9d938dc7b7214a6987f27e"
        "-X main.created=reproducible-build"
      ];
      checkPhase = ''
        runHook preCheck
        export GOFLAGS=''${GOFLAGS//-trimpath/}
        go test ./internal/configuration/... ./internal/wireguard/... \
          ./internal/healthcheck/... ./internal/provider/airvpn/...
        runHook postCheck
      '';
      postInstall = ''
        mv "$out/bin/gluetun" "$out/bin/gluetun-entrypoint"
      '';
      meta = {
        description = "Pinned Gluetun release with repository-owned dependency updates";
        homepage = "https://github.com/passteque/gluetun";
        license = pkgs.lib.licenses.mit;
        mainProgram = "gluetun-entrypoint";
      };
    }).overrideAttrs
      (previous: {
        env = previous.env // {
          GOOS = "linux";
          GOARCH = "amd64";
        };
      });
}
