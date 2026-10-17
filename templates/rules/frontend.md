---
trigger: glob
globs:
  - "**/*.tsx"
  - "**/*.jsx"
  - "**/*.vue"
  - "**/*.html"
  - "**/*.css"
  - "**/*.scss"
---
<!-- hainguyencoder:template=rules/frontend.md version=1.1.0 -->

# Frontend & Visual Identity Rules

- **Design Tokens First**: Before creating or modifying UI components or styling, ALWAYS read `DESIGN.md` in the project root. Adhere strictly to its color tokens, typography scales, rounded corners, and spacing.
- **Anti-Slop & Anti-Default (Taste)**: Never default to lazy AI design patterns:
  - Do NOT use generic purple-cyan gradients on dark backgrounds.
  - Do NOT generate 3 identical generic feature cards with meaningless icons.
  - Do NOT add endless distracting micro-animations. Motion must be purposeful and subtle (150–200ms transitions).
  - Use generous, intentional whitespace (`spacing.lg` / `spacing.xl`) and clear visual hierarchy.
- **Accessibility & Contrast**: Every text element must achieve WCAG AA contrast against its background (minimum 4.5:1 for body text, 3:1 for large text). Every interactive element must have a visible `:focus-visible` ring.
- **Live Browser Verification**: When running a local web server, verify changes using Chrome DevTools MCP (inspect console errors and network requests) or Playwright MCP (visual snapshot and click testing) rather than guessing.
- Use semantic HTML (`header`, `main`, `nav`, `button` for actions, `a` for navigation).
- Every interactive element is keyboard accessible and has an accessible name; images have meaningful `alt`.
- Keep components small and focused; lift state only as far as needed.
- In React: follow the Rules of Hooks, give list items stable `key`s, avoid unnecessary `useEffect` for derived state.
- Never render untrusted HTML (`dangerouslySetInnerHTML`, `innerHTML`) without sanitization.
- Layouts must be responsive (mobile first) and respect `prefers-reduced-motion` for animations.
- Give interactive elements unique, descriptive `id`s or test ids for automated testing.


