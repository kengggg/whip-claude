# Whip Claude Prompt Template

The runner is the source of truth for execution. This file explains the intended prompt shape.

## Core prompt shape

```text
Ultrathink. Pressure-test this in {mode} mode.

Task:
{task}

What I need from you:
- options
- tradeoffs
- risks
- recommendation

Mode rules:
- mode-specific deterministic bullet list

Rules:
- do not be agreeable by default
- attack the strongest-looking answer at least once
- be concrete, not hand-wavy
- if something is uncertain, say what would resolve it
```

## Budget

The deterministic runner enforces:
- 1 ACP attempt
- 1 CLI fallback attempt
- 1 follow-up round

## Principle

Claude can be creative in the answer.
The workflow should not be creative.
