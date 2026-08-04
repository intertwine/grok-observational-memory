---
description: Set up Observational Memory for Grok Build — consent-gated wiring of hooks and the managed AGENTS.md context block.
---

# /om-setup

Guided, consent-gated bootstrap for Observational Memory (OM). Nothing is
written until the user explicitly confirms. Never install software on the
user's behalf.

## Preflight

1. **Kill switch** — if `OM_GROK_PLUGIN_DISABLE=1` is set in the environment,
   tell the user setup is disabled by that variable and stop.
2. **Is `om` installed?** Check with:

   ```bash
   command -v om && om --version
   ```

   - **If found**: confirm the version is `>=0.10,<0.11` (setup.sh re-verifies).
   - **If NOT found**: STOP. Do not install anything automatically. Explain
     the two supported options and let the user choose and run one themselves
     (or ask you to run their chosen one):

     ```bash
     uv tool install observational-memory
     # or
     pipx install observational-memory
     ```

     Wait for the user. Re-run the check after they decide. If they decline,
     end here — setup requires the `om` CLI.

## Explain and confirm (required consent gate)

Before running anything, tell the user exactly what setup will write:

1. `~/.grok/hooks/grok-observational-memory.json` — a user-level hook file
   registering SessionStart/SessionEnd → context refresh and
   SessionEnd/UserPromptSubmit/PreCompact → throttled memory checkpoints.
   (Plugin `hooks/hooks.json` is not executed by Grok 0.2.50; the user-level
   file is the wiring that actually fires.)
2. A managed, sentinel-delimited block in `~/.grok/AGENTS.md` containing
   bounded startup context from `om context`. Everything outside the
   sentinels is preserved byte-for-byte. This block contains personal memory
   derived from sessions — the file must never be committed or synced.
3. `~/.local/state/grok-observational-memory/` — a state directory holding
   stable copies of the hook scripts (so hooks survive `grok plugin update`),
   plus throttle and lock state.

It also runs `om install --grok` (om-core's native checkpoint wiring) and
strips the native SessionStart entry (its stdout is a no-op on Grok).

Ask: **"Proceed with setup? (yes/no)"** — only continue on an explicit yes.

## Run setup

Locate the installed plugin's `setup.sh` (the install directory has a hashed
suffix, so glob for it):

```bash
for dir in "$HOME"/.grok/installed-plugins/*/; do
  if grep -qs '"name": *"observational-memory"' "$dir.grok-plugin/plugin.json"; then
    PLUGIN_DIR="$dir"; break
  fi
done
echo "${PLUGIN_DIR:-not found}"
```

If not found, the plugin is not installed — tell the user to run
`grok plugin install <repo-url> --trust` first, and stop.

Then run it:

```bash
sh "${PLUGIN_DIR}scripts/setup.sh"
```

- **Sync-exposure gate**: if setup exits with a warning that
  `~/.grok/AGENTS.md` is a symlink or `~/.grok` is inside a git work tree,
  relay that warning to the user verbatim. Personal memory written there
  could leave the host via dotfiles sync or git. Only if the user explicitly
  acknowledges the risk, re-run with:

  ```bash
  sh "${PLUGIN_DIR}scripts/setup.sh" --ack-sync-risk
  ```

- Any other non-zero exit: report the script's stderr to the user and stop.
  Do not retry blindly.

## Verification

```bash
test -f "$HOME/.grok/hooks/grok-observational-memory.json" && echo "hook file: OK"
grep -cF "BEGIN OBSERVATIONAL MEMORY" "$HOME/.grok/AGENTS.md" 2>/dev/null
ls "$HOME/.local/state/grok-observational-memory/bin/"
om doctor
```

Expect: hook file present, exactly one BEGIN sentinel, four scripts in the
bin dir, and `om doctor` healthy. Summarize `om doctor` findings; do not
paste raw memory content. If anything failed, suggest `/memory-status` for a
full diagnosis.

## Summary — set honest expectations

Tell the user, plainly:

- Grok reads `~/.grok/AGENTS.md` **before** session hooks run, so refreshed
  memory lands **one session late**: what this session does becomes visible
  context in the *next* session (the block is refreshed at session start and
  session end).
- The initial block was just written, so the next session starts with
  current memory.
- Checkpoints (observation of session transcripts) run throttled in the
  background on SessionEnd/UserPromptSubmit/PreCompact.
- Emergency off switch: `export OM_GROK_PLUGIN_DISABLE=1` disables every
  plugin script instantly. Full removal: `/om-teardown`.
- Health check any time: `/memory-status`. Search memory: `/recall <query>`.
