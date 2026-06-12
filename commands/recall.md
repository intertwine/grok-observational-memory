---
description: Search observational memory for context from past sessions.
argument-hint: "<query>"
---

# /recall

Search observational memory for context from past sessions.

## Usage

```
/recall $ARGUMENTS
```

Run the following command to recall memory:

```bash
om recall --query "$ARGUMENTS" --limit 10
```

Present the results to the user, highlighting the most relevant matches.

For structured output (easier to rank and quote precisely), use JSON mode:

```bash
om recall --query "$ARGUMENTS" --limit 10 --json
```

## No results

If nothing comes back:

- Suggest broadening or rephrasing the search terms (fewer words, no quotes).
- Try `om search "$ARGUMENTS" --limit 10` as an alternative — it searches
  observations, reflections, and auto-memory directly with source metadata.
- If `om` itself is missing or errors, point the user to `/memory-status`
  for a wiring diagnosis (and `/om-setup` if OM was never set up).

Never invent memories — report only what the commands return.
