FROM postgres:14.23-bookworm@sha256:70b9c8977b5fb87bd55c9e29472d778d76d56a6266143d47259da13d78a72afa
COPY --chmod=0555 restore-no-network /usr/local/bin/restore-no-network
USER 65534:65534
# checkov:skip=CKV_DOCKER_2:Disposable Job image; completion is checked instead of a long-running healthcheck.
ENTRYPOINT ["/usr/local/bin/restore-no-network"]
CMD ["/bin/true"]
