---
trigger: model_decision
description: Apply to authentication, authorization, sessions, secrets, cryptography, file upload, network access, user input, SQL, shell execution, or other trust-boundary code.
---
<!-- hainguyencoder:template=rules/security.md version=1.0.0 -->

# Security Rules

- Identify the trust boundary before editing.
- Validate and normalize untrusted input; encode output for its context (HTML, SQL, shell, URL).
- Use least privilege.
- Never interpolate user-controlled strings into SQL, shell commands, file paths, or templates.
- Do not log credentials or secrets.
- Keep authorization checks server-side; check ownership on every record access (avoid IDOR).
- Preserve secure defaults (CSRF protection, secure cookies, password hashing with the platform's recommended algorithm).
- When security behavior is ambiguous, prefer explicit denial over silent privilege expansion.
