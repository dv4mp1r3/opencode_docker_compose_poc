FROM node:22-slim

ARG UID=1000
ARG GID=1000

RUN npm install -g opencode-ai @opencode-ai/plugin && \
    groupmod -g "${GID}" node && \
    usermod -u "${UID}" -g "${GID}" node && \
    mkdir -p /workspace && chown node:node /workspace

WORKDIR /workspace

USER node

ENTRYPOINT ["opencode"]
