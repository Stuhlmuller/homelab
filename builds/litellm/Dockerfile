FROM harbor.stinkyboi.com/mirror/ghcr.io/berriai/litellm-database:main-stable@sha256:5a9ff0fd7177372f2ccd8949cb121f67e281f4d13d026af51f9c096c0626f50a

USER 0
# Preserve the reviewed SDK; use signed packages from the image's existing repo.
RUN apk add --no-cache --upgrade \
      glibc-2.44=2.44-r8 glibc-2.44-locale-posix=2.44-r8 \
      ld-linux-2.44=2.44-r8 libcrypt1-2.44=2.44-r8 \
    && apk info -e glibc-2.44=2.44-r8 glibc-2.44-locale-posix=2.44-r8 \
      ld-linux-2.44=2.44-r8 libcrypt1-2.44=2.44-r8

USER 65532:65532
HEALTHCHECK --interval=30s --timeout=5s --start-period=30s --retries=3 \
  CMD ["/app/.venv/bin/python", "-c", "import urllib.request; urllib.request.urlopen('http://127.0.0.1:4000/health/liveliness', timeout=3).read()"]
