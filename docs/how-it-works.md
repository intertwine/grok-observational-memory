# How It Works

This page explains the plumbing: which channels exist on Grok Build, why this plugin uses the ones it uses, and the safety rules every script follows. All runtime claims were live-verified against Grok Build 0.2.50.

## Context channels on Grok

There are three candidate ways to feed memory into a Grok session. Only one works well:

1. **Hook stdout** — does not work. Grok discards hook stdout. There is no `additionalContext` machinery in the 0.2.50 binary; a SessionStart hook that prints context injects nothing and only burns time. This was live-verified, not assumed.
2. **Project `.grok/rules/*.md`** — works, but writing memory into every project would dirty user repos and risk committing personal memory. Rejected.
3. **Global `~/.grok/AGENTS.md`** — works, and it is user-global, which matches OM's user-level memory model. This is the channel the plugin uses. (Note: `~/.grok/rules/` is *not* read by Grok; only the global `AGENTS.md` file is.)

So the plugin maintains a managed, sentinel-delimited block inside `~/.grok/AGENTS.md`, generated from bounded `om context`. Everything outside the sentinels is preserved byte-for-byte.

## The one-session lag

Grok reads `AGENTS.md` **before** it runs SessionStart hooks. In text form:

```text
session N starts
  1. grok reads ~/.grok/AGENTS.md          <- sees the block from session N-1
  2. grok fires SessionStart hooks
       -> context-refresh.sh rewrites the block (fresh, but session N already read it)
  ... session N runs ...
       -> every prompt: throttled checkpoints observe the session,
          and context-refresh.sh --throttle 900 re-rewrites the block
          at most every 15 minutes
session N ends
  3. grok fires SessionEnd hooks (when delivered; see below)
       -> context-refresh.sh rewrites the block again
       -> checkpoint.sh runs om grok-checkpoint

session N+1 starts
  1. grok reads ~/.grok/AGENTS.md          <- sees memory "as of session N"
```

The lag is one session, by design and unavoidable on 0.2.50. Refreshing at SessionStart, on a 15-minute throttle during the session, and at SessionEnd keeps the worst case small.

One honest wrinkle, found in live testing: headless sessions (`grok -p`) never deliver SessionEnd to user-level hooks on 0.2.50. That is exactly why the throttled per-prompt refresh exists — even if SessionEnd never fires, the block still converges while you work.

## The managed block, hardened

`context-refresh.sh` follows a strict write procedure:

- `om context` runs **before** the target file is read; its envelope is captured into a 0600 temp file under the private state dir and parsed with python3. It is never echoed.
- Content is sanitized: any line in the memory content that matches a sentinel is neutralized, so memory text can never open or close the managed block.
- The file is validated: exactly one BEGIN line followed by one END line. Anything else (zero, duplicates, reversed) fails closed — the file is left untouched.
- Writes are atomic: temp file in the target directory, fsync, rename. Fresh creates get mode 600; existing permissions are preserved.
- A mkdir-based lock (with stale reclaim) serializes concurrent refreshes.
- If `~/.grok/AGENTS.md` is a symlink, the script writes through to the real file so the rename never silently replaces the link.
- The refresh is cwd-agnostic on purpose: no `--cwd`, no `--task`. A global file gets global context; project-specific routing comes from `/recall` and the skill.
- If a user deletes the block, normal refreshes do not recreate it — that user has opted out until they re-run `/om-setup` (only setup passes `--init`).
- "Plugin gone" degrade: if Grok's plugin registry parses, matches the known 0.2.50 schema (a `repos` map whose entries carry a `plugins` map), and no longer lists the plugin, the block content is replaced with a one-line removal notice instead of going stale forever. A missing, unreadable, or unrecognized-schema registry (e.g. after a grok upgrade reshapes this undocumented file) never triggers the degrade — positive schema evidence is required before working context is replaced.

## Fail-closed contract

Every hook-path script (`context-refresh.sh`, `checkpoint.sh`, `run-hook`) obeys the same rules:

- The kill switch `OM_GROK_PLUGIN_DISABLE=1` is the **first** check, before anything else runs.
- On any failure: exit 0, leave the target untouched, and emit only short one-line breadcrumbs to stderr. A single run emits at most one *failure* breadcrumb; spec-mandated sync-exposure warnings (symlinked `AGENTS.md`, `~/.grok` inside a git work tree) can add a line or two on top.
- Memory content never goes to stdout or stderr. Breadcrumbs are diagnostics only.
- Hooks never block the session: `om grok-checkpoint` runs in a fully detached background subshell.

`setup.sh` and `teardown.sh` are different: they are command-invoked installers, so they exit non-zero on hard failure (a silent failed setup would be worse). They still never print memory content.

## Privacy and scope governance

- The block's content comes from `om context`, which already enforces OM scope governance and budgets. `scope=local` reflection entries never leave the host — and `~/.grok/AGENTS.md` is a host-local file, so the channel is consistent with that rule.
- Every block carries a fixed warning line: "Contains personal memory derived from your sessions — do not commit or sync this file."
- Dotfile-sync exposure check: if `~/.grok/AGENTS.md` is a symlink (dotfiles-repo pattern) or `~/.grok` is inside a git work tree, setup refuses to proceed without an explicit acknowledgment (`--ack-sync-risk` non-interactively), and every refresh emits a warning breadcrumb.
- `context-refresh.sh` sources no provider env — `om context` needs no LLM keys. Provider env (`~/.config/observational-memory/env`) is sourced only by `checkpoint.sh`, where reflection-side work may need it.

## Forward-compat hooks.json

The plugin ships `hooks/hooks.json` registering the same events through `scripts/run-hook`. On Grok 0.2.50 this file is **inventoried but never executed** — session hooks load only from user-level sources like `~/.grok/hooks/*.json`, not from plugins. That is why `/om-setup` writes a user-level hook file: it is the wiring that actually fires.

The plugin-delivered hooks exist for the day xAI wires the plugin hooks adapter. When that happens, `run-hook` prevents double-firing deterministically: if `GROK_PLUGIN_ROOT` is set and the user-level hook file registers the same event, the user-level wiring owns it and `run-hook` exits 0. If the event cannot be determined but the user-level file exists, it suppresses conservatively rather than risk a double fire.

This is also why the plugin version is 0.9.0: 1.0.0 is reserved for when the plugin hooks adapter goes live and the forward-compat layer is validated against it.

## Stable paths: surviving `grok plugin update`

The hook file never points into the plugin install directory (which `grok plugin update` re-clones under a new hash). Instead, `/om-setup` copies the scripts to `~/.local/state/grok-observational-memory/bin/` and bakes those absolute paths into the hook file. The commands are self-guarding — `if [ -x <path> ]; then exec <path>; fi; exit 0` — so a wiped state dir degrades to a silent no-op, never a hook error. Re-running `/om-setup` re-copies and re-resolves.

## Dedup vs `om install --grok`

om-core's own `om install --grok` writes a **native** hook file, `~/.grok/hooks/observational-memory.json`, which handles checkpointing. The plugin and the native wiring coexist by a simple ownership split:

- **SessionStart belongs to the plugin.** Setup strips any SessionStart entry from the native file, because its stdout-based context injection is a no-op on Grok (see channel facts above). The plugin's `context-refresh.sh` is the working replacement. `/memory-status` detects if a later bare `om install --grok` re-adds the native SessionStart.
- **Checkpoint events belong to the native file when it has them.** At runtime, `checkpoint.sh` does a structured check of the native file: if it registers the same event, the plugin script exits 0 and lets native wiring checkpoint. One checkpointer wins, regardless of what any setup-time editing did.

Teardown removes only the plugin's wiring. The native file is om-core's; remove it with `om uninstall --grok`.
