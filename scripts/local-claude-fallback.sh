#!/bin/bash
set -euo pipefail

WORKDIR="${1:-$PWD}"
PROMPT_FILE="${2:-}"
SYSTEM_PROMPT="${WHIP_CLAUDE_SYSTEM_PROMPT:-You are being used as a fallback pressure-test and debate engine for OpenClaw. Be concrete, skeptical, and concise. Provide options, tradeoffs, risks, and a recommendation.}"
PERMISSION_MODE="${WHIP_CLAUDE_PERMISSION_MODE-bypassPermissions}"

if [[ -z "$PROMPT_FILE" || ! -f "$PROMPT_FILE" ]]; then
  echo "usage: $0 <workdir> <prompt_file>" >&2
  exit 2
fi

if ! command -v claude >/dev/null 2>&1; then
  echo "claude CLI not found on PATH" >&2
  exit 127
fi

cd "$WORKDIR"
if [[ -n "$PERMISSION_MODE" ]]; then
  exec claude --print --permission-mode "$PERMISSION_MODE" --output-format text --append-system-prompt "$SYSTEM_PROMPT" "$(cat "$PROMPT_FILE")"
else
  exec claude --print --output-format text --append-system-prompt "$SYSTEM_PROMPT" "$(cat "$PROMPT_FILE")"
fi
