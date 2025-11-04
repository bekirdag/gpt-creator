# Admin (Vue 3) development Dockerfile
FROM node:20-alpine
RUN corepack enable pnpm && mkdir -p /workspace/apps/admin
WORKDIR /workspace/apps/admin
EXPOSE 5173
CMD ["sh", "-c", "while true; do sleep 3600; done"]

