#!/usr/bin/env bash
# gpt-creator aliases.sh — helpful shortcuts and environment variables for development

# Add gpt-creator bin to PATH (if not already added)
export PATH="$PATH:${GC_PROJECT_ROOT}/bin"

# Common aliases
alias gc="gpt-creator"                # shortcut to the main CLI
alias gcup="gpt-creator run compose-up" # start the Docker stack
alias gclogs="gpt-creator run logs"    # tail logs for all services
alias gcstop="gpt-creator run stop"    # stop the Docker stack

# Useful commands
alias gcbuild="pnpm build --frozen-lockfile" # Build using pnpm (full build)
alias gcdev="pnpm dev"   # Start the development server
alias gcstatus="docker-compose ps"  # Docker status
alias gctail="docker-compose logs -f"   # Docker logs (follow)

# Optional: set up bash auto-completion (if available in the shell)
if command -v complete >/dev/null 2>&1; then
  complete -C "gpt-creator --complete" gpt-creator
fi
