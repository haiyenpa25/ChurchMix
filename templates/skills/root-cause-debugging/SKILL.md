---
name: root-cause-debugging
description: Diagnose failing tests, runtime errors, incorrect behavior, blank pages, HTTP 500s, performance anomalies, build failures, or intermittent issues using evidence-driven debugging.
---
<!-- hainguyencoder:template=skills/root-cause-debugging version=1.0.0 -->

# Root Cause Debugging

Do not begin by randomly modifying code.

1. Reproduce the failure.
2. Capture the exact error, inputs, logs, environment, and failing command. Useful log locations:
   - XAMPP: `C:\xampp\apache\logs\error.log`, `C:\xampp\php\logs\`
   - Laravel: `storage/logs/laravel.log`
   - Docker: `docker compose logs <service>`
3. Reduce the problem to the smallest reproducible scope.
4. Form hypotheses and test them with logs, debugger, tracing, or focused tests.
5. Identify the root cause, not only the symptom.
6. Add a regression test when practical.
7. Apply the smallest safe fix.
8. Remove temporary instrumentation (`var_dump`, `console.log`, `print`).
9. Re-run verification and report the root cause in one or two sentences.
