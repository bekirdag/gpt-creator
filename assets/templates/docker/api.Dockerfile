# API (NestJS) development Dockerfile
FROM node:20-alpine
RUN corepack enable pnpm && mkdir -p /workspace/apps/api
WORKDIR /workspace/apps/api
EXPOSE 3000
CMD ["sh", "-c", "while true; do sleep 3600; done"]

