#!/bin/bash
set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "$0")" && pwd)"
SKILL_DIR="$(cd "$SCRIPT_DIR/.." && pwd)"
RUNNER="$SCRIPT_DIR/runner.py"

usage() {
  cat >&2 <<'EOF'
usage:
  acp-cycle.sh prep --task-file <path> [--mode debate|architecture|coding|critique] [--clip]
  acp-cycle.sh prompt --run-dir <dir>
  acp-cycle.sh finish --run-dir <dir> --file <acp-output-file>
EOF
  exit 2
}

copy_to_clipboard() {
  local file="$1"
  if command -v pbcopy >/dev/null 2>&1; then
    pbcopy < "$file"
    return 0
  fi
  if command -v wl-copy >/dev/null 2>&1; then
    wl-copy < "$file"
    return 0
  fi
  if command -v xclip >/dev/null 2>&1; then
    xclip -selection clipboard < "$file"
    return 0
  fi
  if command -v xsel >/dev/null 2>&1; then
    xsel --clipboard --input < "$file"
    return 0
  fi
  if command -v clip.exe >/dev/null 2>&1; then
    clip.exe < "$file"
    return 0
  fi
  return 1
}

json_get() {
  local key="$1"
  python3 -c 'import json, sys; print(json.loads(sys.stdin.read())[sys.argv[1]])' "$key"
}

cmd_prep() {
  local task_file=""
  local mode="debate"
  local clip="false"

  while [[ $# -gt 0 ]]; do
    case "$1" in
      --task-file)
        task_file="$2"
        shift 2
        ;;
      --mode)
        mode="$2"
        shift 2
        ;;
      --clip)
        clip="true"
        shift
        ;;
      *)
        usage
        ;;
    esac
  done

  [[ -z "$task_file" ]] && usage
  [[ ! -f "$task_file" ]] && { echo "task file not found: $task_file" >&2; exit 2; }

  local init_json
  init_json="$(python3 "$RUNNER" init --skill-dir "$SKILL_DIR" --task-file "$task_file" --mode "$mode" --prefer-rail acp)"
  local run_dir prompt_file
  run_dir="$(printf '%s' "$init_json" | json_get run_dir)"
  prompt_file="$(printf '%s' "$init_json" | json_get base_prompt_file)"

  printf '%s\n' "$init_json"
  echo "Prompt file: $prompt_file" >&2

  if [[ "$clip" == "true" ]]; then
    if copy_to_clipboard "$prompt_file"; then
      echo "Copied prompt to clipboard." >&2
    else
      echo "No supported clipboard tool found; prompt not copied." >&2
    fi
  else
    echo "Use: $0 prompt --run-dir $run_dir" >&2
  fi
}

cmd_prompt() {
  local run_dir=""
  while [[ $# -gt 0 ]]; do
    case "$1" in
      --run-dir)
        run_dir="$2"
        shift 2
        ;;
      *)
        usage
        ;;
    esac
  done
  [[ -z "$run_dir" ]] && usage
  cat "$run_dir/base-prompt.txt"
}

cmd_finish() {
  local run_dir=""
  local file=""
  while [[ $# -gt 0 ]]; do
    case "$1" in
      --run-dir)
        run_dir="$2"
        shift 2
        ;;
      --file)
        file="$2"
        shift 2
        ;;
      *)
        usage
        ;;
    esac
  done
  [[ -z "$run_dir" || -z "$file" ]] && usage
  python3 "$RUNNER" ingest-acp --run-dir "$run_dir" --file "$file"
}

sub="${1:-}"
[[ -z "$sub" ]] && usage
shift

case "$sub" in
  prep) cmd_prep "$@" ;;
  prompt) cmd_prompt "$@" ;;
  finish) cmd_finish "$@" ;;
  *) usage ;;
esac
