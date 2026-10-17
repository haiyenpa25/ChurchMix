---
trigger: glob
globs:
  - "**/*.ts"
  - "**/*.tsx"
  - "**/*.js"
  - "**/*.jsx"
  - "**/*.mjs"
---
<!-- hainguyencoder:template=rules/typescript.md version=1.0.0 -->

# TypeScript / JavaScript Rules

- Prefer TypeScript with `strict` mode for new code when the project uses TypeScript.
- Avoid `any`. Prefer `unknown`, generics, discriminated unions, or validated boundary types (e.g. zod schemas).
- Do not use non-null assertions (`!`) merely to silence the compiler unless the invariant is proven.
- Prefer exhaustive handling for discriminated unions.
- Naming: `camelCase` variables/functions, `PascalCase` types/classes/components, `UPPER_SNAKE_CASE` true constants.
- Use `const` by default, `let` only when reassigned; never `var`.
- Always handle promise rejections; no floating promises.
- Use `===`/`!==`.
- Follow the repository's existing module/import conventions (ESM vs CJS, path aliases).
- Validate external data (API responses, env vars, form input) at the boundary.
