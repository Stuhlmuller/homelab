FROM ghcr.io/actions/actions-runner:2.338.0@sha256:4ffadc0002b2581327e06101fc8c06cd189232baf79fe561fac9caeb76f5e807

USER root
RUN apt-get update \
    && apt-get install -y --no-install-recommends iptables python3 python3-venv procps openssh-client xz-utils \
    && rm -rf /var/lib/apt/lists/* \
    && install -d -o runner -g docker /opt/hostedtoolcache
ENV RUNNER_TOOL_CACHE=/opt/hostedtoolcache
USER runner
