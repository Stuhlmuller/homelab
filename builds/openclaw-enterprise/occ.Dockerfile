FROM cgr.dev/chainguard/static:latest@sha256:c12f0107f8afb0bbc1b0eff96ff8675e85a10c6083d039b777c51fef5c27420f
# checkov:skip=CKV_DOCKER_2:One-shot occ CLI; command exit status is the health signal and build.sh verifies --version without a service endpoint.
COPY occ /occ
USER 65532
ENTRYPOINT ["/occ"]
