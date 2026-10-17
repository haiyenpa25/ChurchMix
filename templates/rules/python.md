---
trigger: glob
globs:
  - "**/*.py"
---
<!-- hainguyencoder:template=rules/python.md version=1.0.0 -->

# Python Rules

- Follow the Python version configured by the repository; PEP 8 naming (`snake_case` functions/variables, `PascalCase` classes).
- Add type hints to new or materially changed public code; prefer built-in generics (`list[str]`, `dict[str, int]`, `X | None`).
- Avoid bare `except:`; catch specific exceptions and never `pass` silently.
- Keep I/O boundaries explicit; prefer small composable functions over unnecessary class hierarchies.
- Validate request data with the framework's schema layer (Pydantic for FastAPI, forms/serializers for Django).
- Use the ORM or parameterized queries; never format SQL with f-strings.
- Use a virtual environment; pin dependencies in `requirements.txt` or `pyproject.toml`.
- Follow Ruff/Black/mypy configuration already present in the repository.
