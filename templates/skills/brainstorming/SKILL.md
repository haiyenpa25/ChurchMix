---
name: brainstorming
description: Interactive Socratic requirements elicitation and design exploration before coding. Breaks complex features into clear specs with user confirmation.
---
<!-- hainguyencoder:template=skills/brainstorming version=1.1.0 -->

# Brainstorming & Requirements Elicitation

Use this skill whenever starting a new feature, substantial modification, architectural refactor, or ambiguous user request.
**Never jump straight into writing code without first understanding the true intent and constraints.**

---

## The Workflow

```
Clarify Intent ──> Explore Options & Tradeoffs ──> Chunked Spec ──> User Sign-Off ──> Implementation Plan
```

### 1. Socratic Inquiry
- Ask clarifying questions about user intent, target persona, performance requirements, and edge cases.
- Frame questions with clear multiple-choice options or recommendations when possible to minimize cognitive load.
- Identify integration points and data models early.

### 2. Propose Alternatives & Trade-offs
- Present 2-3 architectural approaches when non-obvious trade-offs exist (e.g., synchronous vs asynchronous, relational schema vs JSON column, server-side vs client-side state).
- State pros and cons of each approach clearly.
- Recommend the simplest maintainable approach that satisfies the requirements (YAGNI).

### 3. Chunked Specification
- Present the agreed spec in digestible sections:
  1. **Goal & Scope**: What is in-scope and explicitly out-of-scope.
  2. **Data & Schema**: Entities, fields, relationships, migrations.
  3. **Interface / API**: Endpoints, payloads, UI states.
  4. **Verification Criteria**: How we know it works (test cases, acceptance criteria).
- Keep each chunk under 30-40 lines so the user can actually read and review it without cognitive overload.

### 4. Explicit Confirmation
- Explicitly ask the user to approve the spec before writing code or making large file changes.
- Once approved, proceed to implementation planning (`.ai/plans/`) and Test-Driven Development (TDD).
