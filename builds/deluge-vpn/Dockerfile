FROM docker.io/library/python:3.14.7-alpine3.23@sha256:218761489de417a6eb0808e264cbdd7043ec6659fe5a61898815e9848536541d

RUN apk add --no-cache ca-certificates iproute2 nftables wireguard-tools-wg
WORKDIR /opt/deluge-vpn
COPY --chmod=0444 network.py health.py ./

LABEL org.opencontainers.image.source="https://github.com/Stuhlmuller/homelab" \
      org.opencontainers.image.licenses="Apache-2.0" \
      org.opencontainers.image.description="Fail-closed WireGuard routing and health for Deluge"

# Kubernetes grants elevated network privileges explicitly to the routing containers.
USER 65534:65534
