#!/usr/bin/env bash
# shellcheck shell=bash
# docker.sh — Docker helpers for gpt-creator

if [[ -n "${GC_LIB_DOCKER_SH:-}" ]]; then return 0; fi
GC_LIB_DOCKER_SH=1

# Docker-compose helper
docker_compose() {
  local compose_file="${1:-docker-compose.yml}"
  shift || true
  docker-compose -f "$compose_file" "$@"
}

# Pull a Docker image
docker_pull() {
  local image="$1"
  docker pull "$image"
}

# Build and run a Docker container
docker_build_run() {
  local dockerfile="${1:-Dockerfile}"
  local context="${2:-.}"
  local container_name="${3:-container}"
  docker build -f "$dockerfile" "$context" -t "$container_name"
  docker run --rm "$container_name"
}

# Clean up stopped containers
docker_cleanup() {
  docker container prune -f
}

# Docker health check (check if container is healthy)
docker_health_check() {
  local container="$1"
  docker inspect --format '{{.State.Health.Status}}' "$container" || die "Health check failed: $container"
}
