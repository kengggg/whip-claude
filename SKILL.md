---
name: whip-claude
description: Interpret phrases like "whip Claude", "use Claude ultrathink", "debate with Claude", "keep Claude in check", or "pressure-test this with Claude" as a request to run the current task through a deterministic Claude pressure-test workflow. Use a fixed runner, fixed retry budget, structured logs, ACP first, and local Claude CLI fallback when ACP stalls.
user-invocable: true
metadata: {"openclaw":{"emoji":"🥊","requires":{"bins":["bash","python3","claude"]}}}
---

Use this when the user wants Claude used as a pressure-testing partner for planning, architecture, coding approach, research framing, or critique.

Execution source of truth:
- `{baseDir}/scripts/runner.py` is the deterministic executor.
- `{baseDir}/scripts/local-claude-fallback.sh` is the deterministic local fallback rail.
- `{baseDir}/scripts/acp-cycle.sh` is the ACP convenience wrapper around the runner.
- `references/` files explain intent and prompt shape, but the runner controls the workflow.

Deterministic mode rules:
- If the user explicitly says `architecture`, use `architecture` mode.
- If the user explicitly says `coding`, use `coding` mode.
- If the user explicitly says `critique`, use `critique` mode.
- Otherwise default to `debate` mode.
- Do not infer mode beyond those explicit tokens. Default instead.

Deterministic workflow:
1. Extract the task and write it to a temporary task file outside the skill directory when possible.
2. Run:
   `python3 {baseDir}/scripts/runner.py init --skill-dir {baseDir} --task-file <task-file> --mode <mode> --prefer-rail acp`
   or use the smoother wrapper:
   `{baseDir}/scripts/acp-cycle.sh prep --task-file <task-file> --mode <mode>`
3. Attempt Claude via ACP exactly once.
4. After the ACP attempt, prefer automatic ingestion when a stream log or raw output file is available:
   `python3 {baseDir}/scripts/runner.py ingest-acp --run-dir <run-dir> --file <path>`
   or use the smoother wrapper:
   `{baseDir}/scripts/acp-cycle.sh finish --run-dir <run-dir> --file <path>`
5. Use manual override only when needed:
   `python3 {baseDir}/scripts/runner.py mark-acp --run-dir <run-dir> --status <success|stale|error|empty> [--response-file <path>]`
6. Follow the runner's `next_step` exactly:
   - `done` → read the final response file and summarize it for the user
   - `cli_call` → run `python3 {baseDir}/scripts/runner.py run-cli --run-dir <run-dir>`
   - `follow_up` → run `python3 {baseDir}/scripts/runner.py follow-up --run-dir <run-dir>`
   - `failed` → tell the user Claude did not produce a usable answer
7. Never exceed the runner budget:
   - 1 ACP attempt
   - 1 CLI attempt
   - 1 follow-up round
8. Never paste raw Claude output directly. The host agent summarizes it in its own voice.

ACP staleness rules:
- Treat ACP as stale when a stall/no-output event appears.
- Treat ACP as stale when no useful output arrives after about 60 seconds on a straightforward analysis task.
- Treat ACP as stale when the run finishes without a substantive answer.

Guardrails:
- If the user explicitly says not to use Claude, do not use this skill.
- If there is no clear target, ask one short clarification question.
- Prefer ACP first, but never let a sticky ACP session block the whole task.
- Respect the runner's branch decisions instead of improvising a different workflow.
- Raw internal signals and raw Claude transcripts stay internal.
