#!/bin/sh
set -eu

cd /build
test "$(uname -m)" = x86_64
test "$(apk --print-arch)" = x86_64
sha256sum -c inputs.sha256

# Local files retain normal Alpine signature verification. No repository or
# network fallback may change this dependency set during compilation.
apk add --no-network --no-cache --no-progress --repositories-file /dev/null /build/inputs/*.apk
apk info -v > /build/installed-packages.txt
grep -Fx 'libcrypto3-3.5.8-r0' /build/installed-packages.txt
grep -Fx 'libssl3-3.5.8-r0' /build/installed-packages.txt

metadata=/out/usr/share/homelab-gluetun/native
mkdir -p /out/usr/sbin "$metadata/licenses"
cp native-inputs.json "$metadata/inputs.json"
cp inputs.sha256 "$metadata/input-sha256sums.txt"
LC_ALL=C sort /build/installed-packages.txt > "$metadata/build-packages.txt"
cc --version > "$metadata/compiler.txt"

build_openvpn() (
    family=$1
    archive=$2
    epoch=$3
    regenerate=$4
    directory="/build/openvpn-$family"
    mkdir -p "$directory"
    tar -xzf "/build/inputs/$archive" -C "$directory" --strip-components=1
    cd "$directory"

    # Fixed build inputs, not caller overrides. SOURCE_DATE_EPOCH comes from
    # the checksum-pinned source archive and stabilizes compiler date macros.
    export LC_ALL=C TZ=UTC SOURCE_DATE_EPOCH="$epoch"
    export CFLAGS='-Os -fomit-frame-pointer -fno-plt -fstack-clash-protection -Wformat -Werror=format-security -fstack-protector-strong -ffile-prefix-map=/build=.'
    export CPPFLAGS='-D_FORTIFY_SOURCE=2'
    export LDFLAGS='-Wl,--as-needed,-O1,--sort-common -Wl,-z,relro,-z,now'
    if [ "$regenerate" = yes ]; then
        autoreconf -vif
    fi

    # Preserve the native Alpine APKBUILD options. iproute2 also keeps 2.6 DCO
    # disabled, matching the existing runtime contract. Both builds use the
    # SDK's shared LZ4, retaining compression without embedding another copy.
    ./configure \
        --build=x86_64-alpine-linux-musl \
        --host=x86_64-alpine-linux-musl \
        --prefix=/usr \
        --mandir=/usr/share/man \
        --sysconfdir=/etc/openvpn \
        --enable-iproute2 \
        --enable-x509-alt-username
    for feature in ENABLE_CRYPTO_OPENSSL ENABLE_LZO ENABLE_LZ4 ENABLE_IPROUTE ENABLE_X509ALTUSERNAME; do
        grep -Fx "#define $feature 1" config.h
    done
    if grep -Eq '^#define ENABLE_DCO 1$' config.h; then
        echo 'Unexpected OpenVPN DCO feature' >&2
        exit 1
    fi
    make -j2

    binary="/out/usr/sbin/openvpn$family"
    cp src/openvpn/openvpn "$binary"
    chmod 755 "$binary"
    strip --strip-unneeded "$binary"
    "$binary" --version > "$metadata/openvpn$family.version.txt"
    ./config.status --config > "$metadata/openvpn$family.configure.txt"
    readelf -h "$binary" > "$metadata/openvpn$family.elf.txt"
    readelf -d "$binary" |
        sed -n 's/.*Shared library: \[\([^]]*\)\].*/\1/p' |
        LC_ALL=C sort > "$metadata/openvpn$family.needed.txt"
    for library in libc.musl-x86_64.so.1 libssl.so.3 libcrypto.so.3 liblzo2.so.2 liblz4.so.1; do
        grep -Fx "$library" "$metadata/openvpn$family.needed.txt"
    done
    grep -Eq 'Type:[[:space:]]+DYN' "$metadata/openvpn$family.elf.txt"
    grep -F 'OpenSSL 3.5.8' "$metadata/openvpn$family.version.txt"

    mkdir -p "$metadata/licenses/openvpn$family"
    cp COPYING COPYRIGHT.GPL AUTHORS "$metadata/licenses/openvpn$family/"
)

build_openvpn 2.5 openvpn-2.5-68e18e528197733663ab84fb3b70d7dba7732f24.tar.gz 1785762789 yes
build_openvpn 2.6 openvpn-2.6.22.tar.gz 1785944193 no
grep -F 'OpenVPN 2.5.11 ' "$metadata/openvpn2.5.version.txt"
grep -F 'OpenVPN 2.6.22 ' "$metadata/openvpn2.6.version.txt"
grep -Fx 'libcap-ng.so.0' "$metadata/openvpn2.6.needed.txt"
(cd /out && sha256sum usr/sbin/openvpn2.5 usr/sbin/openvpn2.6) > "$metadata/binary-sha256sums.txt"
