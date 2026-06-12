# Maintainers

Internal checklists. Users never need this page.

## Pre-submission live checklist (spec F)

Run every item on a real machine with Grok Build 0.2.50+ before opening the
marketplace PR. CI cannot cover these — they exercise the live `grok` binary.

1. `grok plugin validate .` passes, then `grok plugin install <local path> --trust`
   plus a headless smoke test: the `~/.grok/AGENTS.md` block is created on the
   first SessionStart and its content is injected into the **second** session
   (probe-token pattern — put a unique token in memory, ask the next session
   to repeat it).
2. Verify SessionEnd and PreCompact actually fire from `~/.grok/hooks`
   (UserPromptSubmit covers checkpoints if they do not; decide from evidence,
   not assumption).
3. `/om-teardown` leaves zero residue: hook file, managed block, and state dir
   all gone; re-running `/om-setup` converges.
4. `grok plugin update` keeps wiring functional (stable-path re-resolve test).
5. `git fetch --depth 1 <url> <sha>` works against the public repo before
   opening the marketplace PR.
6. End state on the validation machine: plugin installed and wired (dogfooding
   — leave it active).

## Pinning the marketplace catalog sha

`docs/marketplace-entry.json` ships with the placeholder
`"sha": "TBD-pin-at-submission"`. The catalog validator requires a full
40-hex commit sha (`^[0-9a-f]{40}$`), so the placeholder **must** be replaced
at submission time with the tip of the public repo:

```sh
git ls-remote https://github.com/intertwine/grok-observational-memory.git HEAD
```

Copy the sha into `source.sha`, re-run `uv run --group dev pytest`
(`test_marketplace_source_sha_pinned_or_placeholder` accepts only the
placeholder or a valid 40-hex sha), and paste the validator output into the
marketplace PR body.

## Marketplace PR body must disclose

- The forward-compat `hooks/hooks.json` (inventoried but inert on 0.2.50).
- The consent-gated `/om-setup` writing a user-level hook file and the
  `~/.grok/AGENTS.md` managed block.
- Local validator output and a link to `docs/how-it-works.md`.
