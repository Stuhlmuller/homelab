{ pkgs }:
pkgs.pkgsStatic.stdenv.mkDerivation {
  pname = "restore-talos-fault";
  version = "1";
  src = ./.;
  dontConfigure = true;
  buildPhase = ''
    $CC -std=c11 -O2 -Wall -Wextra -Werror -static fault.c -o restore-talos-fault
  '';
  installPhase = ''
    install -Dm555 restore-talos-fault $out/bin/restore-talos-fault
  '';
}
