---
description: Diagnose Observational Memory wiring health on Grok Build — hooks, managed block, staleness, and om doctor summary.
---

# /memory-status

Read-only health check of the Observational Memory wiring. **Never print the
contents of the managed memory block or any memory data** — report presence,
counts, timestamps, and pass/fail only.

## Preflight

1. Note whether `OM_GROK_PLUGIN_DISABLE` is set to `1` — if so, every plugin
   script is silently disabled; report this first, it explains everything.
2. Verify `om` is on PATH (`command -v om && om --version`). If missing,
   most checks below still run; flag it and suggest
   `uv tool install observational-memory` (or `pipx`), then `/om-setup`.

## Plan

All checks are read-only shell probes. Run them all even if early ones fail,
then present a single table. No file is modified.

## Commands

### 1. Plugin hook file + dangling scripts

```bash
HOOK_FILE="$HOME/.grok/hooks/grok-observational-memory.json"
test -f "$HOOK_FILE" && echo "hook file: present" || echo "hook file: MISSING"
BIN="$HOME/.local/state/grok-observational-memory/bin"
for s in lib.sh context-refresh.sh checkpoint.sh teardown.sh; do
  test -x "$BIN/$s" || echo "DANGLING: $BIN/$s"
done
```

- Hook file missing → not set up (or torn down): suggest `/om-setup`.
- Hook file present but baked scripts missing/non-executable → **silent
  no-op** (hook commands self-guard with `exit 0`), so memory quietly stops
  refreshing. Fix: re-run `/om-setup` (re-copies scripts).

### 2. Managed AGENTS.md block — present, well-formed, fresh

```bash
AGENTS="$HOME/.grok/AGENTS.md"
grep -cF "BEGIN OBSERVATIONAL MEMORY" "$AGENTS" 2>/dev/null
grep -cF "END OBSERVATIONAL MEMORY" "$AGENTS" 2>/dev/null
grep -o '<!-- last refreshed [^>]*-->' "$AGENTS" 2>/dev/null
grep -cF "Observational Memory plugin removed" "$AGENTS" 2>/dev/null
```

Interpret:

- **0/0 sentinels** → no block: setup never completed or user deleted it
  (deletion is an opt-out; only `/om-setup` recreates it).
- **Exactly 1/1** → well-formed. Compare the `last refreshed` ISO8601 stamp
  to now: older than ~48 hours = **stale** (sessions ran without refresh, or
  no sessions ran — ask the user which).
- **Any other count** → **malformed block**: refresh fails closed and will
  not touch the file. User must hand-repair the sentinel lines or delete the
  whole block and re-run `/om-setup`.
- **Removed-notice line present** → the plugin was uninstalled at some
  point; block is a placeholder. `/om-setup` to restore.
- **Orphaned block**: sentinels present but hook file missing (check 1) →
  block exists but nothing refreshes it; stale context masquerades as fresh.
  Suggest `/om-setup` (rewire) or `/om-teardown` (clean removal).

### 3. Native om hook file — SessionStart re-added?

```bash
python3 - "$HOME/.grok/hooks/observational-memory.json" <<'PY'
import json, sys
try:
    data = json.load(open(sys.argv[1], encoding="utf-8"))
except Exception:
    print("native hook file: absent or unparseable (OK)"); sys.exit(0)
ss = (data.get("hooks") or {}).get("SessionStart") or []
print("native SessionStart: PRESENT (wasted per-session work)" if ss else "native SessionStart: stripped (OK)")
PY
```

Setup strips SessionStart from om-core's native file because Grok discards
hook stdout. A bare `om install --grok` re-run restores it — harmless but
wasteful (`om context` runs and its output is thrown away). Fix: re-run
`/om-setup`.

### 4. Grok-side disablement

```bash
grep -s "observational-memory\|grok-observational-memory" "$HOME/.grok/disabled-hooks" && echo "hooks DISABLED in ~/.grok/disabled-hooks" || echo "disabled-hooks: clean"
grep -sA3 '^\[plugins\]' "$HOME/.grok/config.toml" | grep "enabled"
```

- Entries in `~/.grok/disabled-hooks` matching our hooks → the user declined
  the trust prompt or disabled them per-hook; hooks will not fire.
- `[plugins].enabled` in `~/.grok/config.toml` should list
  `observational-memory` if installed via `grok plugin install`. (A stale
  name after `grok plugin uninstall` is a known Grok wart — flag, don't fix.)

### 5. Sync exposure

```bash
test -h "$HOME/.grok/AGENTS.md" && echo "WARNING: AGENTS.md is a symlink"
git -C "$HOME/.grok" rev-parse --is-inside-work-tree 2>/dev/null
```

Either condition true → personal memory in AGENTS.md could leave this host
via dotfiles sync or git. Warn clearly.

### 6. om health

```bash
om status
om doctor
```

Summarize each in 2–4 lines (counts, last observe/reflect times, failures).
Do not paste full output; never paste memory content.

## Verification

Confirm every check above produced a definite answer (OK / issue / could not
determine). A check that errored is reported as "could not determine", not
silently skipped.

## Summary

Present a compact table:

```
## Observational Memory — Status

| Check | Result |
|-------|--------|
| Kill switch (OM_GROK_PLUGIN_DISABLE) | unset / SET |
| om CLI | <version> / missing |
| Plugin hook file | present / missing |
| Baked scripts (state-dir bin) | 4/4 / dangling |
| AGENTS.md block | well-formed / missing / malformed / orphaned / removed-notice |
| Last refreshed | <stamp> (fresh / stale) |
| Native SessionStart | stripped / re-added |
| disabled-hooks | clean / disabled |
| [plugins].enabled | listed / not listed / stale entry |
| Sync exposure | none / symlink / git work tree |
| om status | <2-line summary> |
| om doctor | <2-line summary> |
```

Remind the user of the one-session lag: the block reflects memory as of the
last session start/end, by design.

## Next Steps

- Missing/dangling wiring, native SessionStart re-added → `/om-setup`
  (idempotent, converges).
- Malformed block → hand-repair sentinels or delete block, then `/om-setup`.
- Want it gone → `/om-teardown`.
- Memory questions → `/recall <query>`.
- om doctor failures → follow its own remediation lines.
