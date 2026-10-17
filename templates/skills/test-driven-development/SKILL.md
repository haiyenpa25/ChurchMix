---
name: test-driven-development
description: Disciplined Red-Green-Refactor development cycle. Writes failing tests before production code and verifies regression safety.
---
<!-- hainguyencoder:template=skills/test-driven-development version=1.1.0 -->

# Test-Driven Development (TDD)

Use this skill when implementing new features, business rules, API endpoints, bug fixes, or utility functions.
**Writing code without tests or writing tests after the fact leads to unverified assumptions and high regression risk.**

---

## The Red-Green-Refactor Cycle

```
[ RED ]         Write the smallest failing test covering the requirement. Run it to confirm failure.
  │
  ▼
[ GREEN ]       Write the absolute minimum production code required to make the test pass.
  │
  ▼
[ REFACTOR ]    Clean up code structure, eliminate duplication, improve naming, while keeping tests green.
  │
  ▼
[ VERIFY ]      Run the full repository verification suite (`scripts/verify.mjs`).
```

---

## Step-by-Step Procedure

### 1. RED Phase — The Test Comes First
- Identify the smallest observable behavior unit (e.g., input validation, edge case, boundary condition).
- Write the automated test in the project's native test framework:
  - Node: `node:test` or `jest`/`vitest`
  - Laravel / PHP: `php artisan test` or `vendor/bin/phpunit`
  - Python: `pytest`
- **Run the test immediately**: Verify that it actually **fails**, and fails for the expected reason (e.g., function not found or assertion mismatch, not a syntax error in the test file itself).

### 2. GREEN Phase — Make It Pass Minimally
- Write only enough code to satisfy the failing test.
- Do not anticipate future requirements or write premature abstractions.
- Run the test again: Confirm that it **passes**.

### 3. REFACTOR Phase — Improve With a Safety Net
- With passing tests serving as a safety net:
  - Remove code duplication (DRY).
  - Clarify variable and function names.
  - Apply guard clauses to reduce nesting.
  - Ensure type safety and error boundary handling.
- Re-run the tests after each refactoring step to confirm no regression.

### 4. Repeat For Next Case
- Move to the next behavior or edge case (empty array, null input, boundary number, network error, unauthorized request).
- Once all acceptance criteria are covered, run the full verification gate:
  ```bash
  node scripts/verify.mjs
  ```
