# whip-claude

A deterministic OpenClaw skill for pressure-testing a task with Claude.

It is designed for cases where you want a repeatable workflow instead of a fuzzy “ask Claude and see what happens” loop.

Why the name? Because sometimes you do not need to ask Claude politely and accept the first silk-wrapped answer like it just descended from the mountain. Sometimes you need to put Claude back to work, poke the weak spots, and make it earn the recommendation. Think less “mystical oracle” and more “gifted but slippery porch intern” who is absolutely not leaving until the tradeoffs, risks, and failure modes are written down in full sentences.

## What it does

- recognizes requests like `whip Claude`
- runs a fixed workflow with a fixed retry budget
- prefers Claude via ACP first
- falls back to local Claude CLI when ACP stalls
- records per-run state and JSONL logs

## Design goal

This skill does **not** try to make Claude's words deterministic.
It makes the **workflow** deterministic:

- explicit mode selection
- explicit state machine
- explicit fallback ladder
- explicit retry budget
- explicit logs

## Modes

Allowed modes:
- `debate`
- `architecture`
- `coding`
- `critique`

Deterministic selection rule:
- if the user explicitly says `architecture`, use `architecture`
- if the user explicitly says `coding`, use `coding`
- if the user explicitly says `critique`, use `critique`
- otherwise default to `debate`

## Files

- `SKILL.md` — machine-facing trigger and execution contract
- `references/modes.md` — mode meanings
- `references/prompt-template.md` — prompt shape and budget notes
- `scripts/runner.py` — deterministic state machine
- `scripts/acp-cycle.sh` — small ACP convenience wrapper
- `scripts/local-claude-fallback.sh` — local Claude CLI fallback

Optional clipboard helpers for `acp-cycle.sh --clip`:
- `pbcopy` (macOS)
- `wl-copy` (Wayland)
- `xclip` or `xsel` (X11)
- `clip.exe` (WSL / Windows interop)

## Prerequisites

Required on PATH:
- `bash`
- `python3` (Python 3.9+)
- `claude`

Expected runtime:
- OpenClaw with ACP support if you want the ACP-first path
- local Claude CLI installed and authenticated if you want fallback reliability

Python dependencies:
- none beyond Python standard library

Supported Python baseline:
- Python 3.9+

## Quick use

### Deterministic ACP cycle

1. Create a task file
2. Prepare a run:

```bash
bash skills/whip-claude/scripts/acp-cycle.sh prep --task-file /path/to/task.txt --mode debate
```

3. Paste the generated prompt into your ACP Claude flow
4. Finish the run from an ACP output file or stream log:

```bash
bash skills/whip-claude/scripts/acp-cycle.sh finish --run-dir /path/to/run-dir --file /path/to/acp-output.txt
```

5. Follow the returned `next_step`

### Direct runner usage

```bash
python3 skills/whip-claude/scripts/runner.py --help
```

Subcommands:
- `init`
- `mark-acp`
- `ingest-acp`
- `run-cli`
- `follow-up`
- `status`

## Environment knobs

### `WHIP_CLAUDE_TIMEOUT_SECONDS`
Overrides the local Claude CLI timeout for all modes.

### `WHIP_CLAUDE_TIMEOUT_<MODE>_SECONDS`
Per-mode timeout override, where `<MODE>` is one of:

- `DEBATE`
- `ARCHITECTURE`
- `CODING`
- `CRITIQUE`

Current built-in defaults:

```text
debate        420
architecture  360
coding        420
critique      300
```

### `WHIP_CLAUDE_SYSTEM_PROMPT`
Overrides the fallback system prompt passed to local Claude CLI.

### `WHIP_CLAUDE_PERMISSION_MODE`
Overrides Claude CLI `--permission-mode`.
Default:

```text
bypassPermissions
```

Set it to an empty string if you want to omit the flag entirely.

## Runtime outputs

At runtime the skill writes under:

- `state/runs/<run-id>/state.json`
- `state/runs/<run-id>/run.jsonl`

These are runtime artifacts and should not normally be committed.
If you want to clear old local runs, deleting `state/runs/` is safe.

## What this skill deliberately does not do

- it does not auto-send to ACP
- it does not poll/watch ACP sessions for you
- it does not let LLM judgment decide workflow branches
- it does not make Claude output deterministic

## Open-source notes

This skill is meant to be portable across OpenClaw setups that have:
- compatible OpenClaw skill loading
- Python 3 available
- Claude CLI available

If your environment differs, adjust shell paths and permission mode policy first.
