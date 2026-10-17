---
name: targeted-refactor
description: Refactor code for readability, maintainability, naming, duplication, complexity, or architectural cleanup while preserving observable behavior and public contracts unless a breaking change is explicitly requested.
---
<!-- hainguyencoder:template=skills/targeted-refactor version=1.0.0 -->

# Targeted Refactor

## Phase 1 — Establish safety

- Identify existing tests; if critical behavior is untested, add characterization tests first.
- Identify public APIs, serialization formats, database contracts, routes, events, and side effects.
- Record behavior that must not change.

## Phase 2 — Diagnose

Look for evidence of: duplicated business logic, mixed responsibilities, excessive nesting, hidden side effects, unclear names, wrong dependency direction, untestable boundaries.

Line counts are heuristics only, not automatic reasons to split code.

## Phase 3 — Refactor

- Make the smallest coherent change, in small steps.
- Extract only when it improves naming, reuse, testing, or separation of concerns.
- Use guard clauses when they improve readability.
- Preserve contracts; avoid formatting churn unrelated to the refactor.

## Phase 4 — Verify

Run relevant tests, types, lint, and build (see `code-change-verification`). Report any behavior or API change explicitly.
