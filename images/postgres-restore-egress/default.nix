{ pkgs }:
pkgs.pkgsStatic.stdenv.mkDerivation {
  pname = "restore-egress-tools";
  version = "1";
  src = ../..;
  dontConfigure = true;
  buildPhase = ''
    $CC -std=c11 -O2 -Wall -Wextra -Werror -static \
      images/postgres-restore-egress/launcher.c -o restore-no-network
    $CC -std=c11 -O2 -Wall -Wextra -Werror -static \
      scripts/ci/restore-egress/probe.c -o restore-network-probe
  '';
  installPhase = ''
    install -Dm555 restore-no-network $out/bin/restore-no-network
    install -Dm555 restore-network-probe $out/bin/restore-network-probe
  '';
}
