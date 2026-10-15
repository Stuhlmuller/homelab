FROM cgr.dev/chainguard/go:latest@sha256:9c148ea8c9eec4e1112df074de3176b8811c9e3450e1bfb643a880c0ef5209b6 AS build
USER 0
WORKDIR /src/upstream/src
COPY upstream/ /src/upstream/
COPY homelab-build/original-manager.go /src/original-manager.go
COPY homelab-build/csrf-compat_test.go ./homelabcompat/csrf_test.go
COPY homelab-build/token-trust_test.go ./homelabcompat/token-trust_test.go
RUN go mod download && go mod verify
RUN go run github.com/go-swagger/go-swagger/cmd/swagger@v0.33.1 generate server \
    --template-dir=../tools/swagger/templates --exclude-main \
    --additional-initialism=CVE --additional-initialism=GC --additional-initialism=OIDC \
    -f ../api/v2.0/swagger.yaml -A harbor --target server/v2.0
RUN --network=none cp pkg/artifact/manager.go /src/patched-manager.go \
    && cp /src/original-manager.go pkg/artifact/manager.go \
    && if go test ./pkg/artifact -run 'TestManager/TestCreateIdenticalRepeatedChild' -count=1 >/tmp/baseline.log 2>&1; then exit 1; fi \
    && grep -F 'duplicate key violates unique_reference' /tmp/baseline.log \
    && cp /src/patched-manager.go pkg/artifact/manager.go \
    && go test ./pkg/artifact -run TestManager -count=1 \
    && go test ./server/middleware/csrf ./homelabcompat -count=1 \
    && go list -deps ./core >/tmp/core-packages \
    && if grep -E '^(golang.org/x/crypto/openpgp($|/)|github.com/(docker|distribution)/distribution(/v3)?/registry/(proxy|handlers|storage)($|/))' /tmp/core-packages; then exit 1; fi \
    && CGO_ENABLED=0 go build -buildvcs=false -trimpath \
       -ldflags '-X github.com/goharbor/harbor/src/pkg/version.ReleaseVersion=v2.15.4 -X github.com/goharbor/harbor/src/pkg/version.GitCommit=0a6bf30d54e779962ad5b862fc67e3e9f6b010d8' \
       -o /out/harbor_core ./core

FROM docker.io/goharbor/harbor-core:v2.15.4@sha256:7d2ba5304a729887cdec7cb222a82b500278423de230ae5150c386a6c332b112
LABEL org.opencontainers.image.source="https://github.com/Stuhlmuller/homelab" \
      org.opencontainers.image.licenses="Apache-2.0" \
      org.opencontainers.image.description="Harbor core with byte-preserving identical child relation handling"
COPY --from=build --chown=10000:10000 --chmod=0755 /out/harbor_core /harbor/harbor_core
# Match upstream's loopback-only HTTP/self-signed HTTPS health probe.
HEALTHCHECK CMD curl --fail -s http://localhost:8080/api/v2.0/ping || curl -k --fail -s https://localhost:8443/api/v2.0/ping || exit 1
