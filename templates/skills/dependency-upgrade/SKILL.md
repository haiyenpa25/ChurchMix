---
name: dependency-upgrade
description: Upgrade one or more dependencies (npm, Composer, pip) while minimizing compatibility risk, reviewing release notes or migrations, updating lockfiles, and verifying tests/build.
---
<!-- hainguyencoder:template=skills/dependency-upgrade version=1.0.0 -->

# Dependency Upgrade

1. Identify current and target versions.
2. Classify the upgrade: patch, minor, or major.
3. For major upgrades, read breaking changes and migration notes before editing.
4. Change the minimum necessary manifest/lockfile entries (`package.json`, `composer.json`, `requirements.txt`/`pyproject.toml`).
5. Update code/config only where required.
6. Run affected tests, lint/types, and build.
7. Review the lockfile diff for unexpected dependency churn.
8. Summarize behavior changes and remaining risks.
