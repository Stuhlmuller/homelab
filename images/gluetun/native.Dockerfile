FROM --platform=linux/amd64 ghcr.io/qdm12/gluetun:v3.41.3@sha256:fa19cc76b2af13d57a8d3dc3066f2ada061b1c761b8aecf989b3877c0486e027 AS native-build

# checkov:skip=CKV_DOCKER_3:This offline SDK stage needs root to install signed APKs; the final scratch target only exports files and is never run or deployed.
USER 0
WORKDIR /build
COPY inputs/ /build/inputs/
COPY inputs.sha256 native-inputs.json native-build.sh /build/

# All source archives and signed SDK APKs are fetched and hashed before this
# stage. The base image supplies the pinned Alpine APK trust keys.
RUN --network=none /bin/sh /build/native-build.sh

# Export only the two native programs and their build/license evidence. The
# compiler, development headers, SDK APK database and source trees stay behind.
# checkov:skip=CKV_DOCKER_2:The scratch target is a file artifact exporter with no runnable process to health-check; the separate runtime image retains its healthcheck.
FROM scratch AS artifacts
COPY --from=native-build /out/ /
