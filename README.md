# Grok Observational Memory

First-class Observational Memory for Grok Build.

This plugin gives the `grok` CLI persistent, user-level memory. It observes your sessions, reflects durable facts, and feeds compact startup context back into every new session. It is the Grok analog of `intertwine/hermes-observational-memory` and shares the same local-first memory store used by Claude Code, Codex, OpenCode, Kimi Code CLI, Cowork, and Hermes.

The plugin wraps the `om` CLI ([observational-memory](https://github.com/intertwine/observational-memory)). It never reimplements memory logic.

## Requirements

- Grok Build (`grok` CLI). Designed and verified against the 0.2.50 runtime behavior (context channels, hook execution, and registry shape were live-probed on 0.2.50).
- `observational-memory>=0.9,<0.10` (`om` on your PATH). Install with `uv tool install observational-memory` or `pipx install observational-memory`.
- `python3` (already present wherever `om` runs).
- macOS or Linux. Windows works through WSL.

## Install

Install from the repo:

```sh
grok plugin install intertwine/grok-observational-memory --trust
```

`--trust` is required: hooks only run from trusted plugins.

The CLI installer takes a Git URL, GitHub shorthand (`user/repo`), or local path — not a bare plugin name. Once the plugin is accepted into the marketplace, you can also install it from the marketplace tab inside the Grok TUI (`Ctrl+L`).

## First Run

Inside a Grok session, run:

```text
/om-setup
```

Setup is consent-gated and idempotent. It walks through:

1. Check that `om` is on your PATH and inside the supported version range (`>=0.9,<0.10`).
2. Ask you to acknowledge a sync risk if `~/.grok/AGENTS.md` is a symlink or `~/.grok` sits inside a git work tree (memory must not leave this host).
3. Run `om install --grok` for native checkpoint wiring.
4. Copy hook scripts to `~/.local/state/grok-observational-memory/bin/` and write the user-level hook file `~/.grok/hooks/grok-observational-memory.json`.
5. Write the initial managed memory block into `~/.grok/AGENTS.md`.

Nothing is wired until you run `/om-setup`. Remove everything with `/om-teardown`.

## What It Adds

| Surface | Name | What it does |
| --- | --- | --- |
| Command | `/om-setup` | Guided, consent-gated bootstrap of hooks and the managed context block. |
| Command | `/om-teardown` | Full removal: hook file, managed block, state dir. |
| Command | `/recall` | `om recall` over your memory: `/recall <query>`. |
| Command | `/memory-status` | Wiring health: hook file, block freshness, native-hook drift, `om status` and `om doctor` summary. |
| Skill | `observational-memory` | Teaches Grok when and how to recall memory (`om recall`, `om search`, recall handles). |
| Hooks | `SessionStart`, `SessionEnd`, `UserPromptSubmit` (15-min throttle) | Refresh the managed context block in `~/.grok/AGENTS.md` from bounded `om context`. |
| Hooks | `SessionEnd`, `UserPromptSubmit`, `PreCompact` | Throttled `om grok-checkpoint` so sessions get observed. |

## How Context Injection Works on Grok

Grok Build (verified on 0.2.50) discards hook stdout — there is no `additionalContext` machinery in the binary. So this plugin does not inject context through hooks. Instead it maintains a sentinel-delimited managed block in `~/.grok/AGENTS.md`, a file Grok actually reads:

```text
<!-- BEGIN OBSERVATIONAL MEMORY (managed by grok-observational-memory; edits inside will be overwritten) -->
<!-- last refreshed 2026-06-12T17:00:00Z -->
Contains personal memory derived from your sessions — do not commit or sync this file.

...bounded om context output...
<!-- END OBSERVATIONAL MEMORY -->
```

Everything outside the sentinels is yours and is preserved byte-for-byte.

Honest caveat: Grok reads `AGENTS.md` before SessionStart hooks run. So the context a session sees is the block as of the previous refresh — a one-session lag. The block is re-refreshed at session end and on a 15-minute throttle while you work, so in practice each session starts with memory from your previous session. Details in [docs/how-it-works.md](docs/how-it-works.md).

## vs Grok Native Memory

Grok Build has its own memory features. Observational Memory does not replace, wrap, or read them — it is an independent peer. `om status` and `om doctor` treat Grok native memory as just another thing on the host, not something to manage. Run both if you like; they do not interfere with each other.

What OM adds on top: one shared, inspectable, local-first memory store across all your agents (Claude Code, Codex, OpenCode, Kimi, Grok, Cowork, Hermes), plain Markdown you can read and audit, and explicit recall (`/recall`, `om search`).

## Configuration

| Variable | Default | Purpose |
| --- | --- | --- |
| `OM_GROK_PLUGIN_DISABLE` | `0` | Kill switch. `1` makes every plugin script exit immediately. First check in every script. |
| `OM_GROK_CHECKPOINT_INTERVAL_SECONDS` | `900` | Minimum seconds between throttled checkpoints (`UserPromptSubmit`, `PreCompact`). `SessionEnd` always checkpoints. |

Fixed paths:

| Path | Purpose |
| --- | --- |
| `~/.local/state/grok-observational-memory/` | Plugin state: baked script copies, locks, throttle stamps. Removed by `/om-teardown`. |
| `~/.grok/hooks/grok-observational-memory.json` | User-level hook file written by `/om-setup`. |
| `~/.grok/AGENTS.md` | Holds the managed context block. |
| `~/.config/observational-memory/env` | OM provider env, sourced only by the checkpoint script. |

## Validation

After `/om-setup`:

```sh
om doctor
ls ~/.grok/hooks/grok-observational-memory.json
grep -c "BEGIN OBSERVATIONAL MEMORY" ~/.grok/AGENTS.md   # expect: 1
om recall --query "current work" --limit 3
```

Then start a session, end it, and start another: the second session's context includes the block refreshed at the first session's end.

## Uninstall

Order matters. Run the plugin teardown **first**, while the command still exists:

```text
/om-teardown
```

Then remove the plugin:

```sh
grok plugin uninstall observational-memory
```

Caveats:

- `grok plugin uninstall` removes the install dir and registry entry but can leave a stale name in `[plugins].enabled` in `~/.grok/config.toml`. Remove it by hand if `grok` complains.
- If you uninstalled the plugin first, the slash command is gone, but the teardown script copy survives. Run it directly:

```sh
sh ~/.local/state/grok-observational-memory/bin/teardown.sh
```

Teardown never touches `om` itself, your memory data, or om-core's native hook file (`om uninstall --grok` handles that one).

## Docs

- [docs/how-it-works.md](docs/how-it-works.md) — context channels, the one-session lag, fail-closed contract, privacy.
- [docs/troubleshooting.md](docs/troubleshooting.md) — dangling hooks, stale blocks, locks, kill switch.
- [docs/maintainers.md](docs/maintainers.md) — pre-submission live checklist, marketplace sha pinning.
- [CHANGELOG.md](CHANGELOG.md)

## License

MIT, Copyright (c) 2026 Intertwine Systems. See [LICENSE](LICENSE).
