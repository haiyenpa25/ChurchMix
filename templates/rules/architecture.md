---
trigger: model_decision
description: Apply when designing modules, introducing abstractions, changing architectural boundaries, adding layers, or performing broad refactors.
---
<!-- hainguyencoder:template=rules/architecture.md version=1.0.0 -->

# Architecture Rules

Before introducing a new abstraction:
1. Identify the concrete duplication, coupling, substitution requirement, or boundary it solves.
2. Prefer adapting an existing project pattern.
3. Avoid "future-proofing" without a current requirement.

For significant architecture changes:
- document affected boundaries in `.ai/decisions/`;
- identify migration/compatibility risks;
- state rejected alternatives briefly;
- keep dependency direction testable;
- use dependency inversion where it reduces real coupling, not merely to increase interface count;
- prefer composition over deep inheritance.
