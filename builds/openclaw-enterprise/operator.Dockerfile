FROM docker.io/library/python:3.13-bookworm@sha256:073ffebb96ae4d0ed73ccad59f08c47bd84af8a79f5258130f8458ac50ad9ff4

ENV PYTHONDONTWRITEBYTECODE=1
COPY --chmod=0555 bin/kubectl bin/yq /usr/local/bin/
COPY --chmod=0444 scripts/openclaw-enterprise.py scripts/openclaw-enterprise-startup.py scripts/openclaw-enterprise-bind-installation.py /opt/homelab/scripts/
COPY --chmod=0444 scripts/config/openclaw-enterprise.json /opt/homelab/scripts/config/openclaw-enterprise.json
COPY --chmod=0444 clusters/homelab/apps/openclaw-enterprise/installation.yaml clusters/homelab/apps/openclaw-enterprise/values.yaml /opt/homelab/clusters/homelab/apps/openclaw-enterprise/
COPY --chmod=0444 operator-source.sha /opt/homelab/operator-source.sha

USER 10001:10001
WORKDIR /opt/homelab
ENTRYPOINT ["python3", "-I", "/opt/homelab/scripts/openclaw-enterprise.py"]
