# Contributing

Thanks for your interest in improving the Grok Observational Memory plugin.

## Development

Hook scripts are POSIX sh and must stay shellcheck-clean:

```sh
shellcheck scripts/*.sh scripts/run-hook
python3 -m json.tool .grok-plugin/plugin.json >/dev/null
python3 -m json.tool hooks/hooks.json >/dev/null
```

Ground rules for changes:

- Fail closed: hook-path scripts always exit 0, breadcrumb once to stderr, and never print memory content.
- The kill switch (`OM_GROK_PLUGIN_DISABLE=1`) stays the first check in every script.
- Never test against a real `~/.grok` or `~/.local/state` — use a fake `HOME` in a temp dir.
- This plugin wraps the `om` CLI; memory logic belongs in [observational-memory](https://github.com/intertwine/observational-memory), not here.

## Licensing and contributor terms

This repository is and will remain MIT licensed. Observational Memory is stewarded by Intertwine Systems, which also builds separately licensed commercial add-ons on top of the core's public interfaces. Contributions are accepted under these terms:

1. **DCO**: you certify the [Developer Certificate of Origin](https://developercertificate.org/) — the contribution is your own work (or you have the right to submit it). Sign each commit with `git commit -s`.
2. **MIT**: you license your contribution under this repository's MIT license.
3. **Steward grant**: you additionally grant Intertwine Systems a perpetual, worldwide, non-exclusive, irrevocable, royalty-free right to use, reproduce, modify, sublicense, and distribute your contribution under other license terms, including commercial terms. Your contribution always also remains available to everyone under MIT here.

Opening a pull request constitutes agreement to these terms. If you contribute on behalf of an employer, make sure you are authorized to agree.

## Security

Do not open public issues for security problems. Report them privately to <bryan@intertwinesys.com>.
