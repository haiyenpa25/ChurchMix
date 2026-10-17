# X32 AI Sound Engineer — Mandatory Agent Rules

These rules govern all AI coding agents, automation services, and developers working on ChurchMix:

1. **NEVER send write OSC to a real mixer in development or tests by default.**
   - All tests must execute against `packages/mock_x32/server.py` or isolated fixtures.
   - Hardware connects must always default to `READ_ONLY_MODE = True`.

2. **Every hardware integration starts in `READ_ONLY_MODE = True`.**
   - No parameter mutations are allowed until the operator explicitly switches modes.

3. **All OSC writes must pass through server-side `SafetyGate` whitelist.**
   - Unwhitelisted paths (e.g. `/config/routing/*`, `/outputs/p16/*`, `/main/st/mix/fader` without admin) are strictly denied.

4. **Never touch AES50, P16/Ultranet, routing, scene recall, preamp, phantom power, or main bus without a separate admin maintenance workflow.**

5. **Hard Safety Invariant: DL16 input 11 (Band Talkback) must NEVER route to Main FOH or Matrix FOH.**
   - It is strictly reserved for Ultranet P16 in-ear personal monitors.
   - Any transaction that violates this invariant must immediately abort with an `InvariantViolationError`.

6. **Do not assume physical DL16 input number equals X32 channel or Ultranet slot.**
   - Preamps, channels, and outputs are independent abstraction layers in X32 architecture.

7. **A proposal is never a command.**
   - AI language models and analysis routines only explain, guide, and formulate proposals.
   - They cannot directly generate or dispatch executable OSC mutations without explicit operator approval.
   - **Bounded pre-approval (amended 2026-10-13, owner decision):** an operator explicitly enabling the
     Autopilot (`packages/autopilot`, Safety Engine mode `LIMITED_AUTO`) is the approval for adjustments that stay
     inside the limits in `configs/safety-defaults.yaml` → `autopilot` (hard ceilings in `engine.HARD_CAPS`).
     Allowed autonomously: channel faders of speech mics (±limit around the reference), narrow cut-only notches
     into a free EQ band within a per-channel budget, and the configured livestream bus fader. Never: preamp/trim,
     routing, Main LR, talkback, EQ boosts, overwriting an EQ band in use, raising a level during silence or
     feedback. Every autonomous write still passes the full Safety Gate (rule 11) and is audit-logged; STOP, any
     mode change or auto-disengage stops it immediately; measurements must be valid and mapped to X32 channels
     (simulated data only ever drives the internal mock). Widening any limit requires the owner's decision.

8. **Validate source tap points and measurement clock before DSP inference.**
   - Do not mistake pre-EQ signals for post-EQ signals.
   - Invalidate measurements upon clock drift, sample drops, or buffer overruns.

9. **Never claim zero feedback risk.**
   - Prefer physical microphone positioning, cardioid technique, and proper gain structure over destructive acoustic EQ carving.
   - Feedback notch filters must be surgical ($Q \ge 6.0$, depth $\le -4.5\text{ dB}$).

10. **No auto-boost while channel is silent (Silence Hold invariant).**
    - Never drift faders upward during speaker pauses or silent segments.
    - Freeze immediately on uncertain meter, route change, or feedback risk.

11. **Every mutation must follow the 5-step Safety Transaction Protocol:**
    - (1) Snapshot revision integrity check (SHA-256)
    - (2) Explicit operator authorization
    - (3) Rate-limited writes (minimum 20ms pacing)
    - (4) OSC readback verification
    - (5) Automated rollback to pre-mutation snapshot on any mismatch

12. **Preserve open-source licenses, notices, commit SHAs, and attributions.**
    - Document all third-party references in `docs/licensing-SBOM.md`.

---

# Developer Guide for AI Agents (Codex, Gemini, Claude) and Humans

This file is the single source of truth for every coding agent. `CLAUDE.md` (Claude Code)
and `GEMINI.md` (Gemini CLI) only import this file; Codex reads it directly. Update rules
here, never in the per-tool files.

## Project map
| Path | What lives there |
| --- | --- |
| `apps/api/main.py` | FastAPI app: REST `/api/v1/*`, WebSocket `/ws/live` (~10 Hz telemetry), serves `apps/web` |
| `apps/web/index.html` + `apps/web/js/` + `apps/web/assets/app.css` | Current UI (vanilla ES modules, no build step, no CDN) |
| `apps/api/audio_sources.py` | Analysis audio resolver: source provenance, sample rate, stale/invalid capture rejection |
| `tools/run-api.mjs` | `npm start` launcher for the Python API; optional `--port 8090` |
| `packages/safety_controller/` | `routing.py` (talkback invariant, RoutingGraph), `transaction.py` (SafetyPolicy whitelist + TransactionExecutor), `modes.py` |
| `packages/x32_osc_adapter/` | OSC codec, `X32Client` (read-only by default), snapshots + SHA-256 |
| `packages/mock_x32/server.py` | UDP X32 simulator used by all tests and the default app start |
| `packages/monitoring/` | Signal monitor (peak/RMS, thresholds, events) behind `/api/v1/monitoring/*` |
| `packages/autopilot/` | Autopilot (Lái tự động): speech rider, auto notch, livestream loudness, clip watch; `apps/api/autopilot_routes.py` |
| `packages/x32_osc_adapter/meters.py` | Read-only X32 `/meters` stream (real per-channel input levels) |
| `packages/storage/service_segments.py` | Tiết mục (service segments): named ON/MUTE sets applied via `TransactionExecutor.execute_batch` behind `/api/v1/segments/*`; stored in `data/service_segments.json` |
| `packages/*` (others) | DSP, feedback detector, EQ optimizer, mix assistant, storage, wizards, copilot |
| `configs/safety-defaults.yaml` | Safety limits and `talkback_protection.x32_channel` (the X32 channel carrying DL16 #11) |
| `tests/` | Python `unittest` suites (`test_*.py`) and Node tests (`*.test.js`) |
| `docs/` | Operator manual, architecture, SOPs, `licensing-SBOM.md` |

The unrelated scaffolding tool and previous UI were archived outside the repository on 2026-10-13. See `docs/source-cleanup-2026-10-13.md` for the manifest and recovery path.

## Commands (Windows; use the full Python path — `python` may be the Store alias)
```powershell
$py = "$env:LOCALAPPDATA\Programs\Python\Python312\python.exe"
& $py -m pip install -r requirements.txt
.\start_church_engineer.bat                                   # app + mock X32 on http://127.0.0.1:8080
$env:CHURCHMIX_X32_PORT = "10923"                             # isolate tests from a running app on UDP 10023
& $py -m unittest discover -s tests -p "test_*.py"            # Python suite (must stay green)
npm test                                                      # Node suite
node --check apps/web/js/views/<file>.js                      # quick syntax check for UI modules
```
Run a second server for previews on another port, e.g. `CHURCHMIX_X32_PORT=10931 ... uvicorn apps.api.main:app --port 8091`.

## Definition of done
1. Python and Node suites pass (report counts; never claim green without running them).
2. New behaviour has a test; safety-relevant changes get a regression test in `tests/test_safety_*.py`.
3. UI changes are checked in a browser against the mock (no console errors, no horizontal scroll at 390 px).
4. No write to a real mixer happened (rule 1). Mock or fixtures only.
5. Docs updated when behaviour or commands change (`README.md`, `docs/operator-manual-vi.md`).

## Backend conventions
- Every OSC mutation goes through `TransactionExecutor.execute()` with an approved `Proposal`. Never call `X32Client.send_write()` or toggle `read_only_mode` anywhere else.
- New writable parameters must be added explicitly to `SafetyPolicy.validate_proposal` with limits and a test that rejects out-of-range values.
- Multi-channel changes (e.g. segments) use `TransactionExecutor.execute_batch()` — one snapshot, ordered writes (mutes before unmutes), rollback of the whole batch. Segments only ever write `/ch/NN/mix/on`.
- Never hard-code channel 11 for talkback logic: use `get_talkback_channel()` from `packages/safety_controller/routing.py`.
- Anything the invariant checker needs must be captured in `X32Client.take_full_snapshot()` (see `talkback_routing_paths`). Missing routing data must fail closed.
- When adding a mixer parameter the app reads, add it to `packages/mock_x32/server.py` too, otherwise queries time out in tests.
- Keep API error messages in `HTTPException(detail=...)`; the UI shows `detail` verbatim.

## Frontend conventions (`apps/web/js`)
- No frameworks, bundlers or CDN assets: the FOH laptop is often offline. Styles only from `assets/app.css`, icons only from `js/icons.js`.
- A page is `js/views/<id>.js` exporting `default { mount(root, ctx) { ...; return cleanup; } }`, registered in `js/routes.js`. Cleanup must clear timers, cancel animation frames and call every `store.on(...)` unsubscribe.
- Use `js/api.js` for HTTP, `js/store.js` for the shared WebSocket/status (never open another WebSocket), and helpers in `js/ui.js` (`card`, `callout`, `openDialog`, `confirmDialog`, `withLoading`, `toast`, `renderMarkdown`, `drawCurve`).
- Every mixer write needs explicit confirmation: proposals use `renderProposal()` (confirm → `POST /api/v1/proposals/apply`); direct actions (mute, connect hardware, delete, import) use `confirmDialog()` first. STOP is the only action without a confirm.
- Two audiences: **Simple mode** (`views/home.js`) is for volunteers — plain Vietnamese, one primary action per step, no jargon. **Technical mode** is everything else. Put new expert tools in technical pages; surface only safety-critical signals in Simple mode.
- Live data: mutate existing DOM nodes, draw canvases at most once per animation frame, skip work when `document.hidden`.
- All user-facing text is Vietnamese; code, identifiers and commit messages are English.

## Working together (several agents on one repo)
- Before editing, run `git status`. If files you need have uncommitted changes you did not make, another agent may be mid-task: do not overwrite them. Work on a branch or a `git worktree`, or ask the human.
- Keep changes scoped; one topic per commit. Conventional commits: `feat(scope): ...`, `fix(scope): ...`, `docs: ...`, `test: ...`.
- Do not reformat or rename files outside your task; line endings are LF in the repo (Git may warn about CRLF on Windows — that is expected).
- Never commit `data/*.db`, captured audio, `.env` files or credentials. Pushing to `origin` only when the human asks.
- Record notable decisions in `docs/` (e.g. a dated review file) so the next agent has context.
