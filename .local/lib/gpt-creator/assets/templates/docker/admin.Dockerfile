# Admin (Vue 3) development Dockerfile
FROM node:20-alpine

RUN apk add --no-cache util-linux curl

ENV PNPM_VERSION=10.17.1 \
    PNPM_HOME=/usr/local/share/pnpm

RUN npm install -g pnpm@${PNPM_VERSION} && \
    mkdir -p /opt/pnpm-store && \
    chmod -R 775 /opt/pnpm-store && \
    pnpm config set store-dir /opt/pnpm-store --global

ENV PATH="${PATH}:${PNPM_HOME}:/workspace/node_modules/.bin"

WORKDIR /workspace
COPY package.json pnpm-lock.yaml* ./
RUN if [ -f pnpm-lock.yaml ]; then \
      pnpm install --frozen-lockfile --unsafe-perm --prefer-offline --engine-strict=false --reporter=append-only; \
    elif [ -f package.json ]; then \
      pnpm install --unsafe-perm --prefer-offline --engine-strict=false --reporter=append-only; \
    fi || true

WORKDIR /workspace/apps/admin

EXPOSE 5173
CMD ["sh", "-c", "while true; do sleep 3600; done"]
