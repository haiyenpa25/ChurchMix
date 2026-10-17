---
trigger: glob
globs:
  - "app/**/*.php"
  - "routes/**/*.php"
  - "database/**/*.php"
  - "config/**/*.php"
  - "resources/views/**/*.blade.php"
  - "tests/**/*.php"
---
<!-- hainguyencoder:template=rules/laravel.md version=1.0.0 -->

# Laravel Rules

- Follow Laravel conventions first (naming, folder structure, Eloquent relationships, resource controllers).
- Validate input with Form Requests or `$request->validate()`; never use unvalidated `$request->all()` for mass assignment.
- Protect models with `$fillable` (preferred) or `$guarded`.
- Authorize with Policies/Gates; do not rely on hiding UI elements.
- Keep controllers thin; move non-trivial domain logic into actions/services only when it is reused or complex.
- Avoid N+1 queries: eager-load relations (`with()`) for lists.
- Schema changes only through migrations; never edit a migration that may already have run in another environment — add a new one.
- Use `config()` in code, `env()` only inside config files.
- Prefer Pest/PHPUnit feature tests for HTTP behavior; use `RefreshDatabase` in tests.
- Run `php artisan` commands rather than editing generated files by hand.
