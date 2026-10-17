---
name: code-change-verification
description: Verify a code change using the repository's formatter, linter, type checker/compiler, focused tests, build, and project-specific checks. Use after implementation, refactoring, bug fixes, or before declaring work complete.
---
<!-- hainguyencoder:template=skills/code-change-verification version=1.0.0 -->

# Code Change Verification

## Goal

Establish evidence that the change is correct without running unnecessary checks blindly.

## Procedure

1. Read `.ai/verify.json` for the authoritative commands. If it is empty or stale, inspect `package.json` scripts, `composer.json` scripts, `pyproject.toml`, and CI config, then propose updates to `.ai/verify.json`.
2. Identify the smallest relevant verification scope.
3. Run checks fast-to-slow: format check → lint/static analysis → types/compile → focused tests → broader tests → build.
   - Shortcut: `node scripts/verify.mjs` runs every command in `.ai/verify.json`.
4. If a check fails:
   - determine whether the failure is caused by the current change;
   - fix change-related failures;
   - do not modify unrelated behavior merely to make the pipeline green.
5. Re-run affected checks after fixes.
6. Report: commands executed, passed, failed, skipped (and why). For larger tasks write it to `.ai/verification/` using `.ai/VERIFICATION_TEMPLATE.md`.

## Completion Rule

Never state that verification passed unless the command actually completed successfully.
