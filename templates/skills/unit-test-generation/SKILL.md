---
name: unit-test-generation
description: Add or improve focused automated tests for changed behavior, public functions, bug regressions, boundary conditions, and failure paths.
---
<!-- hainguyencoder:template=skills/unit-test-generation version=1.0.0 -->

# Unit Test Generation

1. Understand the behavior before writing tests.
2. Test observable behavior over implementation details.
3. Reuse the existing test framework, fixtures, factories, and naming style. If none exists, propose one appropriate to the stack (Vitest/Jest, PHPUnit/Pest, pytest) and ask before adding it.
4. Cover relevant cases: happy path, boundary values, empty/missing input, invalid input, expected failures, bug regression, async/concurrency edge cases.
5. Mock network/database/filesystem only for unit tests; never mock the unit under test.
6. Use Arrange / Act / Assert when it improves clarity.
7. Run the new tests and the surrounding suite; report results honestly.

Do not pursue arbitrary 100% coverage at the cost of meaningful tests.
