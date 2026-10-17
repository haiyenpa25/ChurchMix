---
trigger: glob
globs:
  - "**/*.php"
---
<!-- hainguyencoder:template=rules/php.md version=1.0.0 -->

# PHP Engineering Rules

- Follow PSR-12 formatting and PSR-4 autoloading where the project uses Composer.
- Use `declare(strict_types=1);` in new files when the project already does or has no conflicting convention.
- Add parameter and return types to new or materially changed functions.
- Naming: classes `PascalCase`, methods/variables `camelCase`, constants `UPPER_SNAKE_CASE`.
- Database: always use PDO/mysqli prepared statements or the framework query builder. Never concatenate request data into SQL.
- Output: escape with `htmlspecialchars($value, ENT_QUOTES, 'UTF-8')` (or the template engine's escaping) for every user-controlled value.
- Never trust `$_GET`, `$_POST`, `$_COOKIE`, `$_SERVER`, or `$_FILES` without validation.
- Passwords: `password_hash()` / `password_verify()` only.
- Keep business logic out of view files; separate request handling, logic, and rendering.
- Do not use `@` error suppression or `extract()` on request data.
- Store configuration and credentials in `.env`/config files excluded from Git, not in source.
