# syntax=docker/dockerfile:1.7
# Dormant T051/T045 runtime source. Build before private registry credentials;
# publish, scan and pin its immutable Harbor digest before use.
FROM --platform=linux/amd64 docker.io/library/postgres:18.6-bookworm@sha256:afc7e2d441324c0388fa80c3d24f733b4194a4eb7f47dd8ee2b08eb1a24a647c

# The restore helper uses Python's streaming tar parser; this image is
# unpublished and must be pinned by its resulting Harbor digest before use.
RUN apt-get update \
 && apt-get install -y --no-install-recommends python3 jq util-linux \
 && rm -rf /var/lib/apt/lists/*

# FiloSottile/age v1.3.1 official Linux amd64 release asset.
ADD --checksum=sha256:bdc69c09cbdd6cf8b1f333d372a1f58247b3a33146406333e30c0f26e8f51377 https://github.com/FiloSottile/age/releases/download/v1.3.1/age-v1.3.1-linux-amd64.tar.gz /tmp/age-v1.3.1.tar.gz
RUN tar -xzf /tmp/age-v1.3.1.tar.gz -C /tmp age/age age/LICENSE \
 && install -m 0755 /tmp/age/age /usr/local/bin/age \
 && install -D -m 0644 /tmp/age/LICENSE /usr/share/doc/age/LICENSE \
 && test "$(/usr/local/bin/age --version)" = v1.3.1 \
 && rm -rf /tmp/age /tmp/age-v1.3.1.tar.gz

COPY --chmod=0555 builds/openclaw-enterprise-restore/safe-extract.py /usr/local/libexec/occ-safe-extract.py
