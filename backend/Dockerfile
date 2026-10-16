# syntax=docker/dockerfile:1
# The Oja Loom API: Python standard library only (no pip packages) + Litestream for continuous database backup.
FROM python:3.12-slim-bookworm

# Litestream is pinned to an exact version AND checked against a SHA-256, so a changed or tampered download fails the build.
ARG LITESTREAM_VERSION=0.5.17
ARG LITESTREAM_SHA256_AMD64=cfb371176d164437ae869f8351cfde49bd1804ae71c61923f75c9cba9c9c006d
ARG LITESTREAM_SHA256_ARM64=f8ca4a050095c1efbda2c4365172e61bf9d955ea0d9ac42f448b52e51819baa5
ARG TARGETARCH

RUN set -eux; \
    apt-get update; apt-get install -y --no-install-recommends ca-certificates curl; \
    case "${TARGETARCH:-amd64}" in \
      amd64) arch=x86_64; sha="$LITESTREAM_SHA256_AMD64" ;; \
      arm64) arch=arm64;  sha="$LITESTREAM_SHA256_ARM64" ;; \
      *) echo "unsupported architecture: ${TARGETARCH}" >&2; exit 1 ;; \
    esac; \
    curl -fsSL -o /tmp/litestream.tgz "https://github.com/benbjohnson/litestream/releases/download/v${LITESTREAM_VERSION}/litestream-${LITESTREAM_VERSION}-linux-${arch}.tar.gz"; \
    echo "${sha}  /tmp/litestream.tgz" | sha256sum -c -; \
    tar -xzf /tmp/litestream.tgz -C /usr/local/bin litestream; \
    rm /tmp/litestream.tgz; \
    apt-get purge -y curl; apt-get autoremove -y; rm -rf /var/lib/apt/lists/*; \
    litestream version

# an unprivileged user owns the data folder; the application itself never runs as root
RUN useradd --system --uid 10001 --home-dir /nonexistent --shell /usr/sbin/nologin ojaloom \
 && mkdir -p /data /app && chown ojaloom:ojaloom /data

ENV PYTHONUNBUFFERED=1 PYTHONDONTWRITEBYTECODE=1 OJALOOM_DATA_DIR=/data OJALOOM_ENV=production PORT=8000
WORKDIR /app
COPY --chown=root:root ojaloom_server.py entrypoint.sh /app/
COPY litestream.yml /etc/litestream.yml
RUN chmod 0555 /app/entrypoint.sh && chmod 0444 /app/ojaloom_server.py /etc/litestream.yml

USER ojaloom
VOLUME ["/data"]
EXPOSE 8000
HEALTHCHECK --interval=30s --timeout=5s --start-period=60s --retries=3 \
  CMD python3 -c "import urllib.request,os;urllib.request.urlopen('http://127.0.0.1:%s/health'%os.environ.get('PORT','8000'),timeout=4)" || exit 1
ENTRYPOINT ["/app/entrypoint.sh"]
