---
trigger: glob
globs:
  - "**/*.gs"
  - "**/appsscript.json"
  - "**/.clasp.json"
---
<!-- hainguyencoder:template=rules/apps-script.md version=1.0.0 -->

# Google Apps Script Rules

- Use the V8 runtime syntax (`const`/`let`, arrow functions, classes) — check `appsscript.json` has `"runtimeVersion": "V8"`.
- Minimize Spreadsheet service calls: read with one `getValues()`, process in memory, write back with one `setValues()`. Never call `getValue()`/`setValue()` inside loops.
- Respect quotas and the 6-minute execution limit; batch work and use time-driven triggers for long jobs.
- Use `LockService` when multiple users or triggers can write the same sheet concurrently.
- Store secrets in `PropertiesService` (Script Properties), never in code.
- Locate sheets and columns by header name, not hard-coded indexes, when the layout may change.
- Request the narrowest OAuth scopes in `appsscript.json`.
- Escape user data in `HtmlService` templates (`<?= ?>` escapes; `<?!= ?>` does not).
- If the project uses `clasp`, edit locally and `clasp push`; do not edit the same files in the online editor in parallel.
