# Native Trivy SPDX fixtures

Generated with checksum-verified Trivy 0.72.0 (`trivy_0.72.0_macOS-ARM64.tar.gz`, SHA-256 `88f208680dc05da2b459e19b4f5aa2b4dc7c2117892ba4aab2ae63baba330016`). The SPDX files preserve native output with a final newline added by the repository hook; archive paths are public test scratch paths, not credential locations.

Sources: Alpine 3.23.3 Linux arm64 image configuration `sha256:1ab49c19c53ebca95c787b482aeda86d1d681f58cdf19278c476bcaf37d96de1`; BusyBox exact Linux amd64 child `sha256:1cfa4e2b09e127b9c4ed43578d3f3c18e7d44ea47b9ea98475c0cbe9086525f8`. Images were copied without credentials to Docker archives with skopeo.

```sh
trivy image --cache-dir /path/to/private/cache --format spdx-json \
  --skip-db-update --skip-java-db-update --input image.tar --output image.spdx.json
```

This command generates inventory only; it does not establish a zero-CVE result. The receipt separately requires Harbor vulnerability success. Alpine has 16 reachable library packages. This BusyBox has only its container root and must fail coverage.

- alpine SPDX SHA-256: `f1ebaa08bd521301d2e21f82c9c258ab288e4c9af1487752ad9a896be70824c1`

- busybox SPDX SHA-256: `6361e3ad1d5f740d3525a2464cdae3c51885879cc7aba5dd21e8caa98e774c89`
