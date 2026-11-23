FROM docker.io/nixos/nix:2.34.6@sha256:e2fe74e96e965653c7b8f16ac64d1e56581c63c84d7fa07fb0692fd055cd06b0 AS nix-tools
WORKDIR /build
COPY flake.lock nix-packages.nix ./
# Copy the closure just built in this stage, including locally built unsigned paths.
RUN mkdir -p /opt/runner \
    && nix --extra-experimental-features 'nix-command flakes' build \
       --out-link /opt/runner/tools --file nix-packages.nix \
    && nix --extra-experimental-features nix-command copy --no-check-sigs \
       --to 'local?root=/runner-root' "$(readlink -f /opt/runner/tools)"

FROM ghcr.io/actions/actions-runner:2.338.0@sha256:4ffadc0002b2581327e06101fc8c06cd189232baf79fe561fac9caeb76f5e807
# checkov:skip=CKV_DOCKER_2:Disposable command-driven Workspace runs one JIT job; cordium-runner.py bounds execution and verifies cleanup, with no persistent service endpoint.

USER root
RUN apt-get update \
    && apt-get install -y --no-install-recommends iptables python3 python3-venv procps openssh-client xz-utils \
    && rm -rf /var/lib/apt/lists/* \
    && install -d -o runner -g docker /opt/hostedtoolcache
COPY --from=nix-tools --chown=runner:docker /runner-root/nix /nix
COPY --from=nix-tools /opt/runner /opt/runner
# The disposable runner owns its local store. The Workspace provides isolation.
RUN install -d /etc/nix \
    && printf '%s\n' 'experimental-features = nix-command flakes' \
       'build-users-group =' 'sandbox = false' > /etc/nix/nix.conf \
    && ln -s /opt/runner/tools /nix/var/nix/gcroots/ci-tools
ENV PATH="/opt/runner/tools/bin:${PATH}" \
    NIX_SSL_CERT_FILE=/etc/ssl/certs/ca-certificates.crt \
    RUNNER_TOOL_CACHE=/opt/hostedtoolcache
USER runner
