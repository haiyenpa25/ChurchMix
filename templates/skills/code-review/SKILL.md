---
name: code-review
description: Review a branch, commit, pull request, git diff, or set of changed files for correctness, regressions, security, maintainability, API compatibility, and missing tests.
---
<!-- hainguyencoder:template=skills/code-review version=1.0.0 -->

# Professional Code Review

## Review order

1. Understand the requested behavior.
2. Read the diff (`git diff`, `git diff --staged`, or the named commit range).
3. Read enough surrounding code to understand contracts.
4. Inspect affected tests and callers.
5. Review in this priority order: correctness → data loss → security → concurrency → backward compatibility → error handling → performance → missing tests → maintainability → style.

## Finding format

For each material issue include: severity, exact location (file:line), failure scenario, why it matters, smallest viable fix.

Avoid style-only findings already enforced by formatter/linter.
Do not manufacture findings to produce output. If no material issue is found, say so explicitly and name any residual verification gap.

For larger reviews, write results to `.ai/reviews/` using `.ai/REVIEW_TEMPLATE.md`.
