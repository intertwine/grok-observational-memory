---
name: observational-memory
description: >
  Cross-session observational memory for Grok Build. Use when the user asks
  to "recall something from a past session", "search memory", "what do you
  know about me", "remember when we discussed", or needs context from
  previous conversations. Also triggers when the user mentions
  "observational memory", "OM", or asks about cross-session context.
when-to-use: >
  Recalling decisions, preferences, or project status from earlier sessions;
  identity questions like "what do you know about me"; expanding a recall
  handle that appears in startup context; questions about how observational
  memory works or whether it is set up.
---

# Observational Memory

You have access to a persistent memory system that compresses conversation
transcripts into observations and reflections shared across sessions. It
requires the `om` CLI (observational-memory `>=0.8,<0.9`) on PATH.

## What's Available

Memory reaches Grok through a managed block in `~/.grok/AGENTS.md`,
refreshed by hooks at session start and session end. Grok reads that file
before hooks run, so the block reflects memory **as of the previous
session** (one-session lag, by design). The block is budgeted, so it may
include recall handles for deeper sections. It contains:

- **Profile** — stable facts about the user (role, preferences,
  communication style) extracted from long-term reflections.
- **Active context** — current projects, recent themes, and in-flight work
  derived from recent observations.

## Recalling Memory

Use `om recall` for agent-friendly retrieval:

```bash
om recall --query "query terms" --limit 10 --json
```

Expand a startup handle when one appears in the context block:

```bash
om recall --handle startup:active:active-projects
```

Use `om search` when you want direct search output and source metadata:

```bash
om search "query terms" --limit 10 --json
```

This searches across three document sources:

- **Observations** — compressed transcripts organized by date
- **Reflections** — consolidated long-term memory organized by topic
- **Auto-memory** — Claude Code per-project memory files

Report only what the commands return — never invent memories. If a command
fails or `om` is missing, say so plainly and point to `/memory-status`.

## How It Works

1. **Observer** — after each session, an LLM compresses the conversation
   transcript into prioritized observations (high / medium / low). On Grok
   this runs as throttled background checkpoints on session end, prompt
   submit, and pre-compact.
2. **Reflector** — periodically, observations are consolidated into
   structured reflections covering identity, projects, preferences, themes.
3. **Startup priming** — the context-refresh hook rewrites the managed
   `~/.grok/AGENTS.md` block from budgeted `om context` output.
4. **Recall** — during a session, `om recall` expands startup handles or
   searches deeper memory on demand.

## When to Use This Skill

- User asks about something discussed in a previous session
- User wants to recall a decision, preference, or project status
- User asks "what do you know about me" or similar identity questions
- Context from prior sessions would improve the current response

## Setup and Health

If memory appears to be missing or unconfigured (no managed block in
`~/.grok/AGENTS.md`, `om` not on PATH, recall errors), do NOT attempt to
wire anything yourself — point the user to **/om-setup** (consent-gated
bootstrap). For diagnosis use **/memory-status**; for removal,
**/om-teardown**. The kill switch `OM_GROK_PLUGIN_DISABLE=1` disables all
plugin scripts.
