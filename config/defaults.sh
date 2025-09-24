#!/usr/bin/env bash
# gpt-creator defaults.sh — default configuration for gpt-creator

# Set default values
: "${GC_NAME:=gpt-creator}"
: "${GC_VERSION:=0.1.0}"
: "${GC_MODEL:=gpt-5-high}"
: "${GC_DEFAULT_API_URL:=http://localhost:3000/api/v1}"
: "${GC_DEFAULT_UI_URL:=http://localhost:5173}"

# Path to project root (default current working directory)
: "${GC_PROJECT_ROOT:=${PWD}}"

# Docker (Compose)
: "${GC_DOCKER_COMPOSE_FILE:=${GC_PROJECT_ROOT}/docker/docker-compose.yml}"

# Codex client
: "${GC_CODEX_BIN:=codex}"

# MySQL connection (default: localhost)
: "${GC_DB_HOST:=127.0.0.1}"
: "${GC_DB_PORT:=3306}"
: "${GC_DB_USER:=root}"
: "${GC_DB_PASSWORD:=${MYSQL_ROOT_PASSWORD:-}}"
: "${GC_DB_NAME:=app}"

# Logging level (DEBUG, INFO, WARN, ERROR)
: "${GC_LOG_LEVEL:=INFO}"

# Path for storing project state
: "${GC_STATE_DIR:=${GC_PROJECT_ROOT}/.gpt-creator}"
