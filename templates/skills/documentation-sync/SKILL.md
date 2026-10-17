---
name: documentation-sync
description: Update README, PROJECT_CONTEXT.md, API docs, examples, configuration docs, migration notes, or developer documentation so it accurately matches the implemented code.
---
<!-- hainguyencoder:template=skills/documentation-sync version=1.0.0 -->

# Documentation Sync

1. Determine what behavior, configuration, port, or command changed.
2. Search existing documentation for affected sections (README, PROJECT_CONTEXT.md, `.env.example`, docs/).
3. Update only relevant docs. In `PROJECT_CONTEXT.md`, edit only outside the `HNC:BEGIN`/`HNC:END` block — that block is managed by HAINGUYENCODER.
4. Ensure command examples are executable and paths/names are current.
5. Remove stale or contradictory instructions.
6. Do not document planned behavior as if it already exists.
