# Troubleshooting

Quick checks first:

```sh
om doctor
ls ~/.grok/hooks/grok-observational-memory.json
grep -c "BEGIN OBSERVATIONAL MEMORY" ~/.grok/AGENTS.md   # expect: 1
```

Inside a session, `/memory-status` runs the full wiring health report.

## I uninstalled the plugin and things look dangling

If you ran `grok plugin uninstall` **before** `/om-teardown`, the slash commands are gone but the wiring `/om-setup` created remains: the user-level hook file, the managed block, and the state dir.

This is safe by design — the hook commands are self-guarding and the refresh script writes a removal notice into the block once the plugin disappears from Grok's registry. But to clean up properly, either:

- reinstall the plugin and run `/om-setup` (restores a working state), or
- run the teardown script copy that survives in the state dir:

```sh
sh ~/.local/state/grok-observational-memory/bin/teardown.sh
```

Also check `~/.grok/config.toml`: `grok plugin uninstall` can leave the stale plugin name in the `[plugins].enabled` list. Remove it by hand.

## The block says "Observational Memory plugin removed"

The refresh script found Grok's plugin registry intact but missing this plugin, so it replaced the block content with a removal notice instead of letting stale memory linger. Run `/om-setup` to restore (after reinstalling the plugin), or delete the block if you are done with it.

## The block is stale (old "last refreshed" stamp)

The stamp inside the block tells you when it was last rebuilt. If it stops updating:

1. Check the kill switch: `OM_GROK_PLUGIN_DISABLE` must not be `1` in the environment Grok runs in.
2. Check the hook file exists: `ls ~/.grok/hooks/grok-observational-memory.json`.
3. Check the baked scripts exist: `ls ~/.local/state/grok-observational-memory/bin/`. If the state dir was wiped, hooks degrade to silent no-ops — re-run `/om-setup`.
4. Check `~/.grok/disabled-hooks`: Grok persists per-hook disables there. A hook you (or a prompt) disabled once stays disabled.
5. Run the refresh by hand and watch stderr for a breadcrumb:

```sh
sh ~/.local/state/grok-observational-memory/bin/context-refresh.sh
```

Breadcrumbs are one-liners prefixed `observational-memory(grok):` and never contain memory content.

## "malformed OM block" breadcrumb

The file must contain exactly one BEGIN sentinel followed by one END sentinel. If an edit duplicated, deleted, or reordered a sentinel line, refreshes fail closed and leave the file alone. Open `~/.grok/AGENTS.md`, fix the sentinels (or delete the whole block), then re-run `/om-setup` if you deleted it.

## I deleted the block and it never came back

Intentional. A deleted block means you opted out; normal refreshes do not recreate it. Re-run `/om-setup` to opt back in.

## "om not found" breadcrumb / setup fails on PATH

Hooks run with a minimal environment. The scripts look for `om` on PATH and then in the common install locations (`~/.local/bin/om`, `~/.cargo/bin/om`, the uv tools dir). Install om where one of those finds it:

```sh
uv tool install observational-memory
```

Setup also enforces the supported range `>=0.10,<0.11` and refuses anything outside it.

## Checkpoints seem to never run

- `UserPromptSubmit` and `PreCompact` checkpoints are throttled: at most one per `OM_GROK_CHECKPOINT_INTERVAL_SECONDS` (default 900) per session. `SessionEnd` always checkpoints. This is usually not a bug.
- If om-core's native hook file (`~/.grok/hooks/observational-memory.json`) registers the same event, the plugin defers to it on purpose — the native wiring is doing the checkpointing.
- Check `om status` to see whether observations are actually landing.

## Stale lock

Locks live under `~/.local/state/grok-observational-memory/locks/`. They are mkdir-based and self-heal: a refresh lock older than 10 minutes and a checkpoint lock older than 60 minutes are reclaimed automatically. If something is truly wedged (e.g. after a hard reboot mid-write), it is safe to delete the lock directories:

```sh
rm -rf ~/.local/state/grok-observational-memory/locks
```

## Turning everything off fast

```sh
export OM_GROK_PLUGIN_DISABLE=1
```

Every plugin script — refresh, checkpoint, forward-compat dispatcher, even setup — exits immediately while it is set. Note that teardown also respects the kill switch: unset it before running `/om-teardown`.

## Plugin installed but hooks/commands missing

- Hooks require trust. Install with `--trust` or accept the TUI trust prompt.
- A plugin dropped into a project `.grok/plugins/` dir without installing is discovered but defaults to disabled. Use `grok plugin install`, and confirm the name appears in `[plugins].enabled` in `~/.grok/config.toml`.
- Plugin-delivered hooks (`hooks/hooks.json`) are inventoried but not executed on Grok 0.2.50 — that is expected. The live wiring is the user-level hook file written by `/om-setup`. If `grok inspect` shows the plugin hooks but nothing fires, run `/om-setup`.
