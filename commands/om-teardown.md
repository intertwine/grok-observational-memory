---
description: Remove Observational Memory wiring from Grok Build — hook file, managed AGENTS.md block, and state directory.
---

# /om-teardown

Cleanly remove everything `/om-setup` wired. Memory data itself is never
touched.

## Confirm intent (required)

Before running anything, tell the user what will be removed and what stays:

**Removed:**

1. `~/.grok/hooks/grok-observational-memory.json` (the plugin's hook file)
2. The managed Observational Memory block in `~/.grok/AGENTS.md` — only the
   block; all other content in that file is preserved byte-for-byte. The
   file is deleted only if the block was its sole content.
3. `~/.local/state/grok-observational-memory/` (script copies, throttle and
   lock state)

**Kept:**

- The `om` CLI and ALL memory data (observations, reflections, profile)
- om-core's native hook file `~/.grok/hooks/observational-memory.json`
  (remove separately with `om uninstall --grok` if desired)
- The installed plugin itself (remove with `grok plugin uninstall
  observational-memory`)

Ask: **"Remove Observational Memory wiring? (yes/no)"** — only continue on
an explicit yes.

## Run teardown

Prefer the stable state-dir copy; fall back to the installed plugin:

```bash
TEARDOWN="$HOME/.local/state/grok-observational-memory/bin/teardown.sh"
if [ ! -x "$TEARDOWN" ]; then
  for dir in "$HOME"/.grok/installed-plugins/*/; do
    if grep -qs '"name": *"observational-memory"' "$dir.grok-plugin/plugin.json"; then
      TEARDOWN="${dir}scripts/teardown.sh"; break
    fi
  done
fi
sh "$TEARDOWN"
```

The script is idempotent — re-running it on an already-clean system is safe.
Note: if `OM_GROK_PLUGIN_DISABLE=1` is set, the script skips itself; unset
that variable first to tear down.

## Verify zero residue

```bash
test ! -e "$HOME/.grok/hooks/grok-observational-memory.json" && echo "hook file: gone"
grep -cF "OBSERVATIONAL MEMORY" "$HOME/.grok/AGENTS.md" 2>/dev/null || echo "no sentinels (or file absent)"
test ! -d "$HOME/.local/state/grok-observational-memory" && echo "state dir: gone"
```

Expect: hook file gone, zero sentinel lines (or AGENTS.md absent), state dir
gone. If teardown warned about a malformed block, tell the user to open
`~/.grok/AGENTS.md` and delete the sentinel lines manually — the script
refuses to guess at a damaged block.

## Summary

Report what was removed and remind the user:

- Their memory data is intact; `om recall` and `om search` still work from
  any terminal.
- Re-enable any time with `/om-setup` (re-runs converge).
- Optional follow-ups: `om uninstall --grok` (native checkpoint wiring),
  `grok plugin uninstall observational-memory` (the plugin itself; note Grok
  may leave the stale name in `[plugins].enabled` in `~/.grok/config.toml`).
