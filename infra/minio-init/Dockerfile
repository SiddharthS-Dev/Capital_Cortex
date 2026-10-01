# Bucket bootstrap: the digest-pinned mc binary on a base that has a shell (Chainguard images are distroless).
FROM cgr.dev/chainguard/minio-client@sha256:be51ef820151a708a8e140037e3746862a8c1dd5e624f84b404a1d71bcefb167 AS mc
FROM python:3.12-slim-bookworm
COPY --from=mc /usr/bin/mc /usr/local/bin/mc
COPY init.sh /init.sh
ENTRYPOINT ["/bin/sh", "/init.sh"]
