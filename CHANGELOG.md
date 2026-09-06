# Changelog

## 0.1.3 - 2026-09-05

- Final unmaintained legacy release with retirement and migration notices.
- Retain the OM 0.10 family and existing opt-in runtime behavior; no automatic
  shutdown of other users' installations and no future compatibility promises.

## 0.1.2 - 2026-08-03

- Accept the Observational Memory v0.10 release line (`>=0.10,<0.11`).
- Keep the existing Grok setup and hook behavior unchanged while OM adds the optional native-memory bridge.

## 0.1.1 - 2026-07-01

- Update the supported `observational-memory` range to `>=0.9,<0.10` for the OM v0.9.0 release line.
- Refresh docs to include OpenCode and Kimi Code CLI in the shared OM host set.

## 0.1.0 — 2026-06-13

Initial release.

- Consent-gated `/om-setup`: verifies `om` (`>=0.8,<0.9`), runs `om install --grok`, copies hook scripts to the stable state dir (`~/.local/state/grok-observational-memory/bin/`), writes the user-level hook file `~/.grok/hooks/grok-observational-memory.json` with self-guarding absolute-path commands, and writes the initial managed block. Idempotent; re-runs converge.
- Managed context block in `~/.grok/AGENTS.md`, rebuilt from bounded `om context` at SessionStart, at SessionEnd, and on a 15-minute throttle per prompt (headless sessions never deliver SessionEnd on 0.2.50, so the throttled refresh keeps the block converging): atomic writes, sentinel sanitization and validation, byte-for-byte preservation of user content, fail-closed on any error, "last refreshed" stamp plus do-not-sync warning, plugin-gone degrade notice.
- Throttled `om grok-checkpoint` on SessionEnd / UserPromptSubmit / PreCompact (`OM_GROK_CHECKPOINT_INTERVAL_SECONDS`, default 900s; SessionEnd always checkpoints), with runtime dedup against om-core's native Grok hook file.
- `/om-teardown`: removes the hook file, splices only the managed block out of `AGENTS.md`, removes the state dir. Leaves om, memory data, and the native om hook file alone.
- Kill switch `OM_GROK_PLUGIN_DISABLE=1` as the first check in every script; POSIX sh, shellcheck-clean; no memory content ever printed.
- Privacy guards: sync-exposure acknowledgment when `~/.grok/AGENTS.md` is symlinked or `~/.grok` is in a git work tree; provider env sourced only by the checkpoint path.

Forward-compat caveat: the shipped `hooks/hooks.json` is inventoried but **not executed** by Grok Build 0.2.50 — the live wiring is the user-level hook file written by `/om-setup`. The plugin hooks (routed through `scripts/run-hook`, with deterministic self-suppression against the user-level file) activate automatically if a future Grok version wires its plugin hooks adapter. This is an early (0.x) release on purpose: Grok's plugin system is days old and that forward-compat path can't be exercised until the adapter lands, so the plugin's surface may still change. A 1.0.0 will follow once the surface is stable and proven in real use.
