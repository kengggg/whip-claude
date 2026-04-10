# Whip Claude Modes

This file explains the deterministic mode meanings.

## Allowed modes

- **debate**: default mode for generic pressure-testing and decision comparison
- **architecture**: explicit system, workflow, interface, or state-machine design work
- **coding**: implementation planning, code-approach review, and verification critique
- **critique**: attacking an existing answer, proposal, draft, or implementation

## Deterministic selection rule

Use only explicit tokens from the user request:
- contains `architecture` -> `architecture`
- contains `coding` -> `coding`
- contains `critique` -> `critique`
- otherwise -> `debate`

Do not add extra inference layers. If the user does not say a mode explicitly, default to `debate`.
