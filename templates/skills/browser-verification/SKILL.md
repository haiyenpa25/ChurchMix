---
name: browser-verification
description: Comprehensive web verification using Chrome DevTools MCP and Playwright MCP to inspect live console, network, and UI behavior.
---
<!-- hainguyencoder:template=skills/browser-verification version=1.1.0 -->

# Browser Verification & Live Diagnostics

Use this skill whenever working on web applications, frontend components, APIs rendered in browser views, or full-stack features.
**Never assume a web page works just because the build command succeeded. Inspect runtime behavior in a live browser.**

---

## Tool Capabilities

### 1. Chrome DevTools MCP (`chrome-devtools-mcp`)
- **Console Inspection**: Reads runtime exceptions, `console.error`, unhandled promise rejections, and deprecation warnings.
- **Network Tab**: Inspects failed HTTP requests, 404 assets, 500 API responses, CORS blocking, and slow response payloads.
- **Performance Traces**: Identifies UI blocking bottlenecks and heavy re-renders.

### 2. Playwright MCP (`@playwright/mcp`)
- **Semantic Interaction**: Clicks buttons, fills form inputs, triggers dropdowns, and verifies navigation paths.
- **Accessibility Snapshots**: Inspects the semantic accessibility tree without fragile CSS selectors.
- **Screenshots**: Captures visual proof of component rendering and responsiveness.

---

## Step-by-Step Procedure

### 1. Ensure Local Server is Active
- Look up the assigned port in `PROJECT_CONTEXT.md` (e.g. `http://localhost:8123` or custom port).
- Verify the server is running or start it using the command specified in `PROJECT_CONTEXT.md`.

### 2. Navigate & Observe
- Navigate to the page using the MCP navigation tool.
- Wait for network idle and initial DOM hydration.

### 3. Verify Console & Network Logs
- Check console output: **Ensure zero uncaught errors or syntax faults**.
- Check network requests: **Ensure all static assets (CSS, JS, images) and API calls return HTTP 200/201/204, not 404 or 500**.
- If a CORS error or API error appears, identify whether the backend headers or endpoint URL is misconfigured.

### 4. Semantic Interaction & Form Verification
- Perform the user journey:
  - Fill input fields with valid data and submit -> verify success state.
  - Fill input fields with invalid data -> verify client-side validation errors are clearly displayed.
- Test keyboard navigation (Tab through interactive elements, check visible `:focus-visible` ring).

### 5. Document Verification Evidence
- Record the test URL, console health, and key findings in `.ai/verification/` using the verification template.
