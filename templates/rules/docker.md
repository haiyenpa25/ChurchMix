---
trigger: glob
globs:
  - "**/Dockerfile"
  - "**/docker-compose*.yml"
  - "**/compose*.yml"
  - "**/.env.example"
---
<!-- hainguyencoder:template=rules/docker.md version=1.0.0 -->

# Docker Rules

- Host ports must match `PROJECT_CONTEXT.md`; never change them without updating that file and asking the user.
- Pin image tags to a major/minor version (e.g. `mysql:8.4`), never `latest`.
- Credentials come from `.env` (ignored by Git); `.env.example` holds placeholders only.
- Use named volumes for database data; never `docker compose down -v` without explicit approval (it deletes data).
- Keep images small: multi-stage builds, `.dockerignore`, no secrets baked into layers.
- Run app containers as a non-root user when practical.
