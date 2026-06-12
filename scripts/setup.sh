#!/bin/sh
# setup.sh — consent-assumed installer, invoked by the /om-setup command.
#
# Consent is gathered by the /om-setup command flow before this script runs;
# the one residual interactive gate here is the sync-exposure acknowledgment
# (override non-interactively with --ack-sync-risk).
#
# What it does (idempotent — re-runs converge):
#   1. verify om on PATH and within the supported version range >=0.8,<0.9
#   2. sync-exposure acknowledgment for ~/.grok/AGENTS.md
#   3. run `om install --grok` (native checkpoint wiring)
#   4. strip SessionStart from om-core's NATIVE hook file (no-op on Grok)
#   5. copy hook scripts to ~/.local/state/grok-observational-memory/bin/
#      (stable path that survives `grok plugin update` re-clones)
#   6. write ~/.grok/hooks/grok-observational-memory.json with self-guarding
#      absolute-path commands
#   7. initial managed-block write into ~/.grok/AGENTS.md
#
# Unlike the hook scripts, setup is allowed to exit non-zero: a failed setup
# must be visible to /om-setup. It still never prints memory content.

# Kill switch FIRST — gates everything.
if [ "${OM_GROK_PLUGIN_DISABLE:-0}" = "1" ]; then
    echo "observational-memory(grok): OM_GROK_PLUGIN_DISABLE=1 - setup skipped" >&2
    exit 0
fi

# HOME guard BEFORE set -u / lib.sh. Setup may exit non-zero (visible failure).
if [ -z "${HOME:-}" ]; then
    echo "error: HOME is unset - cannot locate ~/.grok" >&2
    exit 1
fi

set -u

SCRIPT_DIR=$(CDPATH='' cd -- "$(dirname -- "$0")" && pwd) || exit 1
# shellcheck disable=SC1091
. "$SCRIPT_DIR/lib.sh"

ACK_SYNC=0
for arg in "$@"; do
    case "$arg" in
        --ack-sync-risk) ACK_SYNC=1 ;;
        *)
            echo "usage: setup.sh [--ack-sync-risk]" >&2
            exit 2
            ;;
    esac
done

if ! command -v python3 >/dev/null 2>&1; then
    echo "error: python3 is required (om itself is a Python tool)." >&2
    exit 1
fi

# --- 1. om on PATH + version floor -------------------------------------------
if ! om_find; then
    echo "error: the om CLI was not found." >&2
    echo "Install it first:  uv tool install observational-memory   (or: pipx install observational-memory)" >&2
    exit 1
fi
OM_VERSION_RAW=$("$OM_BIN" --version 2>/dev/null) || OM_VERSION_RAW=""
if ! printf '%s' "$OM_VERSION_RAW" | python3 -c '
import re
import sys

match = re.search(r"(\d+)\.(\d+)(?:\.(\d+))?", sys.stdin.read())
if not match:
    sys.exit(1)
version = (int(match.group(1)), int(match.group(2)))
sys.exit(0 if (0, 8) <= version < (0, 9) else 1)
'; then
    echo "error: om version '${OM_VERSION_RAW:-unknown}' is outside the supported range >=0.8,<0.9." >&2
    echo "Upgrade/downgrade observational-memory, then re-run /om-setup." >&2
    exit 1
fi
echo "Found $OM_VERSION_RAW at $OM_BIN"

# --- 2. Sync-exposure acknowledgment -----------------------------------------
# The managed block holds personal memory. If ~/.grok/AGENTS.md is a symlink
# (dotfiles repo pattern) or ~/.grok sits inside a git work tree, it can leak
# off-host. Setup requires an explicit acknowledgment; refreshes only warn.
SYNC_REASON=""
if [ -h "$OM_GROK_AGENTS_FILE" ]; then
    # shellcheck disable=SC2088  # literal tilde in a human-readable message
    SYNC_REASON="~/.grok/AGENTS.md is a symlink"
fi
if [ "$(git -C "$HOME/.grok" rev-parse --is-inside-work-tree 2>/dev/null)" = "true" ]; then
    [ -n "$SYNC_REASON" ] && SYNC_REASON="$SYNC_REASON; "
    SYNC_REASON="$SYNC_REASON~/.grok is inside a git work tree"
fi
if [ -n "$SYNC_REASON" ] && [ "$ACK_SYNC" != "1" ]; then
    echo "WARNING: $SYNC_REASON."
    echo "The managed block written to ~/.grok/AGENTS.md contains personal memory derived"
    echo "from your sessions. Make sure this file is never committed or synced off this host."
    if [ -t 0 ]; then
        printf "Type 'yes' to acknowledge and continue: "
        read -r ANSWER
        if [ "$ANSWER" != "yes" ]; then
            echo "Setup aborted (sync risk not acknowledged)." >&2
            exit 1
        fi
    else
        echo "Non-interactive run: re-run with --ack-sync-risk to acknowledge." >&2
        exit 1
    fi
fi

# --- 3. Native om wiring -------------------------------------------------------
if ! "$OM_BIN" install --grok; then
    echo "error: 'om install --grok' failed - run 'om doctor' and retry." >&2
    exit 1
fi

# --- 4. Strip SessionStart from the NATIVE hook file ---------------------------
# WHY: Grok (verified on 0.2.50) discards hook stdout — there is no
# additionalContext machinery in the binary — so the native SessionStart
# hook's `om context` run injects nothing; it only burns time every session
# start. This plugin owns SessionStart instead via context-refresh.sh, which
# feeds context through the managed ~/.grok/AGENTS.md block (the channel that
# actually works). The native file's checkpoint events stay untouched:
# checkpoint.sh defers to them at runtime. /memory-status detects a re-added
# native SessionStart (e.g. after a bare `om install --grok` re-run).
if [ -f "$OM_GROK_NATIVE_HOOK_FILE" ]; then
    python3 - "$OM_GROK_NATIVE_HOOK_FILE" <<'PY'
import json
import os
import sys

path = sys.argv[1]
try:
    with open(path, encoding="utf-8") as fh:
        data = json.load(fh)
except Exception:
    sys.exit(0)  # not ours to fix
hooks = data.get("hooks")
if isinstance(hooks, dict) and "SessionStart" in hooks:
    del hooks["SessionStart"]
    tmp = path + ".om-setup-tmp"
    with open(tmp, "w", encoding="utf-8") as fh:
        json.dump(data, fh, indent=2)
        fh.write("\n")
    os.replace(tmp, path)
    print("Stripped SessionStart from native om hook file (stdout is a no-op on Grok)")
PY
fi

# --- Claude-compat check (informational) ---------------------------------------
# WHY a Grok plugin reads ~/.claude/settings.json: Grok ingests Claude Code
# settings through its compatibility layer, so OM's Claude SessionStart hook
# also fires inside Grok sessions. Grok discards its stdout (no double
# context), but the user should know it runs. This is a structured read of
# hook command strings only — no credentials, no foreign data. It replicates
# om-core `_has_om_claude_session_start` (cli.py): parse the JSON, walk
# .hooks.SessionStart[].hooks[].command, match the three OM substrings.
CLAUDE_SETTINGS="$HOME/.claude/settings.json"
if [ -f "$CLAUDE_SETTINGS" ] && python3 - "$CLAUDE_SETTINGS" <<'PY'
import json
import sys

try:
    with open(sys.argv[1], encoding="utf-8") as fh:
        data = json.load(fh)
except Exception:
    sys.exit(1)
for group in (data.get("hooks") or {}).get("SessionStart") or []:
    if not isinstance(group, dict):
        continue
    for hook in group.get("hooks") or []:
        cmd = hook.get("command") if isinstance(hook, dict) else None
        if not isinstance(cmd, str):
            continue  # non-string command values (e.g. int) are not ours
        if "observational-memory" in cmd or "om context" in cmd or "hooks/claude/session-start" in cmd:
            sys.exit(0)
sys.exit(1)
PY
then
    echo "Note: OM Claude SessionStart hook detected in ~/.claude/settings.json."
    echo "      Grok runs it via the Claude-compat layer but ignores its output;"
    echo "      Grok context comes from the managed ~/.grok/AGENTS.md block instead."
fi

# --- 5. Copy scripts to the stable bin dir -------------------------------------
# Baking ~/.local/state/... paths (not the plugin install dir) into the hook
# file keeps hooks working across `grok plugin update` re-clones and keeps
# uninstall from leaving dangling commands (they self-guard, see below).
BIN_DIR="$OM_GROK_STATE_DIR/bin"
mkdir -p "$BIN_DIR" || exit 1
chmod 700 "$OM_GROK_STATE_DIR" 2>/dev/null || true
for script in lib.sh context-refresh.sh checkpoint.sh teardown.sh; do
    if [ ! -f "$SCRIPT_DIR/$script" ]; then
        echo "error: missing $SCRIPT_DIR/$script" >&2
        exit 1
    fi
    cp "$SCRIPT_DIR/$script" "$BIN_DIR/$script" || exit 1
    chmod 755 "$BIN_DIR/$script" || exit 1
done
echo "Installed hook scripts in $BIN_DIR"

# --- 6. Write the user-level hook file ------------------------------------------
# Commands are self-guarding: if the baked script disappears (state dir
# wiped), the command degrades to a silent exit 0 instead of a hook error.
# Event policy (binding spec):
#   SessionStart  -> context-refresh (async, 15s) — always ours
#   SessionEnd    -> context-refresh (async, 15s) + checkpoint (async, 30s)
#   UserPromptSubmit, PreCompact -> checkpoint (async, 30s)
# checkpoint.sh dedups at runtime against the native om hook file.
python3 - "$OM_GROK_HOOK_FILE" "$BIN_DIR/context-refresh.sh" "$BIN_DIR/checkpoint.sh" <<'PY'
import json
import os
import shlex
import sys

hook_file, ctx, ckp = sys.argv[1:4]


def guard(path):
    quoted = shlex.quote(path)
    return "if [ -x %s ]; then exec %s; fi; exit 0" % (quoted, quoted)


def handler(path, timeout, status):
    return {
        "type": "command",
        "command": guard(path),
        "timeout": timeout,
        "async": True,
        "statusMessage": status,
    }


CTX_STATUS = "Refreshing observational memory context..."
CKP_STATUS = "Checkpointing observational memory (Grok)..."

payload = {
    "hooks": {
        "SessionStart": [{"hooks": [handler(ctx, 15, CTX_STATUS)]}],
        "SessionEnd": [{"hooks": [handler(ctx, 15, CTX_STATUS), handler(ckp, 30, CKP_STATUS)]}],
        "UserPromptSubmit": [{"hooks": [handler(ckp, 30, CKP_STATUS)]}],
        "PreCompact": [{"hooks": [handler(ckp, 30, CKP_STATUS)]}],
    }
}

os.makedirs(os.path.dirname(hook_file), exist_ok=True)
tmp = hook_file + ".om-setup-tmp"
with open(tmp, "w", encoding="utf-8") as fh:
    json.dump(payload, fh, indent=2)
    fh.write("\n")
os.replace(tmp, hook_file)
print("Wrote %s" % hook_file)
PY
# shellcheck disable=SC2181
if [ $? -ne 0 ]; then
    echo "error: failed to write $OM_GROK_HOOK_FILE" >&2
    exit 1
fi

# --- 7. Initial managed-block write ---------------------------------------------
# --init allows creating the block in an AGENTS.md that has none yet.
# context-refresh.sh is fail-closed (always exits 0), so verify the result.
"$BIN_DIR/context-refresh.sh" --init || true
if grep -qxF "$OM_BLOCK_BEGIN" "$OM_GROK_AGENTS_FILE" 2>/dev/null; then
    echo "Managed Observational Memory block written to ~/.grok/AGENTS.md"
else
    echo "WARNING: managed block not written to ~/.grok/AGENTS.md - run 'om doctor' and /memory-status" >&2
fi

echo ""
echo "Setup complete. Context refreshes at every session start/end (one-session lag"
echo "by design: Grok reads AGENTS.md before hooks run). Checkpoints observe sessions"
echo "on SessionEnd/UserPromptSubmit/PreCompact. Remove everything with /om-teardown."
exit 0
