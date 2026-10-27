FROM docker.io/library/python:3.13-bookworm@sha256:a3799099b64fd333f262768c7a64733f6e4edb7bc569813710a100214bdcf278

ENV PYTHONDONTWRITEBYTECODE=1
COPY --chmod=0555 bin/kubectl bin/yq /usr/local/bin/
COPY --chmod=0444 scripts/openclaw-enterprise.py /opt/homelab/scripts/openclaw-enterprise.py
COPY --chmod=0444 clusters/homelab/apps/openclaw-enterprise/installation.yaml clusters/homelab/apps/openclaw-enterprise/values.yaml /opt/homelab/clusters/homelab/apps/openclaw-enterprise/
COPY --chmod=0444 operator-source.sha /opt/homelab/operator-source.sha

USER 10001:10001
WORKDIR /opt/homelab
ENTRYPOINT ["python3", "-I", "/opt/homelab/scripts/openclaw-enterprise.py"]
