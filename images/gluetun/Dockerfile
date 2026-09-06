FROM ghcr.io/qdm12/gluetun:v3.41.3@sha256:fa19cc76b2af13d57a8d3dc3066f2ada061b1c761b8aecf989b3877c0486e027
# SDK packages stay in the builder. Retain the existing shared dependencies
# explicitly before removing the stale APK record for the replaced OpenVPN binary.
COPY inputs/libcrypto3-3.5.8-r0.apk inputs/libssl3-3.5.8-r0.apk /tmp/gluetun-runtime-apks/
RUN --network=none apk add --no-network --no-cache --repositories-file /dev/null \
       /tmp/gluetun-runtime-apks/*.apk iproute2-minimal=6.15.0-r0 \
       lzo=2.10-r5 lz4-libs=1.10.0-r0 libcap-ng=0.8.5-r0 \
    && apk del --no-network --no-cache --repositories-file /dev/null openvpn \
    && mkdir -p /etc/openvpn \
    && rm -rf /tmp/gluetun-runtime-apks
COPY --chmod=0555 gluetun-entrypoint /gluetun-entrypoint
COPY --chmod=0555 native/usr/sbin/openvpn2.5 native/usr/sbin/openvpn2.6 /usr/sbin/
COPY native/usr/share/homelab-gluetun/ /usr/share/homelab-gluetun/
LABEL org.opencontainers.image.source="https://github.com/Stuhlmuller/homelab" \
      org.opencontainers.image.version="3.41.3-homelab.1" \
      io.homelab.gluetun.upstream-revision="3d1e20c5551e9cae1f9d938dc7b7214a6987f27e"
# Gluetun initializes its VPN interfaces and firewall before dropping process users.
# checkov:skip=CKV_DOCKER_3:VPN interface and firewall initialization requires the inherited root identity and NET_ADMIN; deployment capabilities are unchanged.
# checkov:skip=CKV_DOCKER_8:Gluetun must initialize VPN interfaces and firewall as root, preserving the pinned upstream entrypoint contract.
USER root
HEALTHCHECK --interval=5s --timeout=5s --start-period=10s --retries=3 CMD /gluetun-entrypoint healthcheck
ENTRYPOINT ["/gluetun-entrypoint"]
