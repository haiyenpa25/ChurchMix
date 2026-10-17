---
trigger: model_decision
description: Apply when changing database schemas, migrations, indexes, constraints, seeders, or data backfills.
---
<!-- hainguyencoder:template=rules/database-migrations.md version=1.0.0 -->

# Database Change Rules

For every schema change:
- consider backward compatibility and existing data;
- consider lock duration and table size;
- have a rollback or roll-forward strategy;
- separate destructive cleanup (drop column/table) from additive migration;
- inspect generated SQL when an ORM hides important details;
- add indexes for new foreign keys and frequent filters;
- never drop or rewrite real data merely to satisfy local development;
- never run destructive SQL (`DROP`, `TRUNCATE`, mass `DELETE`/`UPDATE` without `WHERE`) without explicit user approval.
