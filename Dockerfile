FROM node:22-slim

ARG UID=1000
ARG GID=1000

RUN apt-get update && \
    apt-get install -y --no-install-recommends \
        git ca-certificates ripgrep \
        g++ make \
        golang-go \
        python3 python3-pyflakes \
        curl && \
    rm -rf /var/lib/apt/lists/* && \
    npm install -g opencode-ai && \
    groupmod -g "${GID}" node && \
    usermod -u "${UID}" -g "${GID}" node && \
    mkdir -p /workspace && chown node:node /workspace && \
    mkdir -p /home/node/.local/share/opencode/log && \
    chown -R node:node /home/node/.local

WORKDIR /workspace

USER node

ENTRYPOINT ["opencode"]
