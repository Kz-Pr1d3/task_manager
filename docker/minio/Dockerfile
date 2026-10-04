# Локальный образ MinIO: бинарник с GitHub (официальные registry закрыты).
# Сборка: docker compose build minio

ARG MINIO_VERSION=RELEASE.2025-09-07T16-13-09Z
ARG TARGETARCH=amd64

FROM alpine:3.20 AS download
ARG MINIO_VERSION
ARG TARGETARCH
RUN apk add --no-cache curl ca-certificates \
    && curl -fL -o /minio \
      "https://github.com/minio/minio/releases/download/${MINIO_VERSION}/minio.linux-${TARGETARCH}.${MINIO_VERSION}" \
    && chmod +x /minio

FROM alpine:3.20
RUN apk add --no-cache ca-certificates curl \
    && adduser -D -u 1000 minio \
    && mkdir -p /data \
    && chown minio:minio /data
COPY --from=download /minio /usr/bin/minio
USER minio
EXPOSE 9000 9001
VOLUME ["/data"]
ENTRYPOINT ["minio"]
CMD ["server", "/data", "--console-address", ":9001"]
