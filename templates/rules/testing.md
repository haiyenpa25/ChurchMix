---
trigger: model_decision
description: Apply when writing, changing, or reviewing automated tests, or when fixing a bug that should get a regression test.
---
<!-- hainguyencoder:template=rules/testing.md version=1.1.0 -->

# Testing & Verification Rules (Anti-Rationalization Standards)

## Core Principles
- **Behavior over Implementation**: Test observable behavior and public contracts, not private internals.
- **The Prove-It Pattern**: When fixing a bug, NEVER modify production code first. Write an automated reproduction test that FAILS, confirm the failure, implement the minimal fix, and verify it PASSES.
- **Reuse Existing Tooling**: Always use the project's native test runner (discover via `package.json`, `phpunit.xml`, `pytest.ini`). Do not invent ad-hoc test mechanisms.
- **Mock Only at Boundaries**: Mock slow/external I/O (3rd-party APIs, email, payment gateways). Never mock the unit under test.
- **Integrity**: Never delete, comment out, or weaken an existing test just to make a suite pass.

## Anti-Rationalization (Strictly Prohibited AI Excuses)
| AI Excuse | Reality & Mandate |
| :--- | :--- |
| *"I will write tests after the code works"* | **Prohibited.** Tests written after the fact test implementation, not behavior. Write tests alongside or before code. |
| *"This change is too simple to need a test"* | **Prohibited.** Simple changes evolve into complex bugs. The test documents the invariant. |
| *"I tested it mentally / manual check is enough"* | **Prohibited.** Mental checks do not persist. Tomorrow's refactor will break it silently. |
| *"It is just a small script / prototype"* | **Prohibited.** Prototypes become production. Guard core behavior immediately. |

## Red Flags to Reject
- Claiming "All tests pass" when no test command was actually executed.
- Submitting code where tests pass on the first run without verifying what was actually asserted.
- Disabling assertions or adding broad try/catch blocks merely to silence errors.

