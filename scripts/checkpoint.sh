#!/bin/sh
# checkpoint.sh — throttled `om grok-checkpoint` for Grok Build hook events.
#
# Adapted from the Cowork plugin's session-end.sh for the Grok hook envelope:
# stdin carries camelCase keys (.transcriptPath, .hookEventName) with
# snake_case event values (session_end, user_prompt_submit, pre_compact).
#
# Runtime dedup: if om-core's NATIVE hook file
# (~/.grok/hooks/observational-memory.json, written by `om install --grok`)
# registers the same event, the native wiring owns checkpointing and we exit
# 0 — one checkpointer wins, regardless of what setup-time slimming did.
#
# Fail-closed contract: always exit 0; one-line stderr breadcrumbs only;
# never print memory content. The actual `om grok-checkpoint` runs in a
# detached background subshell so async hooks never block the session.

# Kill switch FIRST — gates everything.
if [ "${OM_GROK_PLUGIN_DISABLE:-0}" = "1" ]; then
    exit 0
fi

set -u

SCRIPT_DIR=$(CDPATH='' cd -- "$(dirname -- "$0")" && pwd) || exit 0
# shellcheck disable=SC1091
. "$SCRIPT_DIR/lib.sh"

if ! command -v python3 >/dev/null 2>&1; then
    om_breadcrumb "python3 unavailable - checkpoint skipped"
    exit 0
fi

# --- Parse the Grok hook stdin envelope --------------------------------------
INPUT=$(cat 2>/dev/null) || INPUT=""

stdin_field() {
    printf '%s' "$INPUT" | python3 -c '
import json
import sys

try:
    data = json.load(sys.stdin)
except Exception:
    sys.exit(0)
value = data.get(sys.argv[1])
if isinstance(value, str):
    sys.stdout.write(value)
' "$1" 2>/dev/null
}

EVENT=$(stdin_field hookEventName)
TRANSCRIPT=$(stdin_field transcriptPath)
if [ -z "$EVENT" ]; then
    EVENT="${GROK_HOOK_EVENT:-}"
fi

# --- Runtime dedup vs the native om-core hook file ---------------------------
EVENT_KEY=$(om_event_key "$EVENT")
if [ -n "$EVENT_KEY" ] && om_hook_file_registers_event "$OM_GROK_NATIVE_HOOK_FILE" "$EVENT_KEY"; then
    # Native `om install --grok` wiring owns this checkpoint event.
    exit 0
fi

# --- Provider env (set -a, Cowork pattern) -----------------------------------
# Sourced ONLY here: reflection-side om work may need provider keys.
# context-refresh.sh never sources this.
ENV_FILE="${XDG_CONFIG_HOME:-$HOME/.config}/observational-memory/env"
if [ -f "$ENV_FILE" ]; then
    set -a
    # shellcheck disable=SC1090
    . "$ENV_FILE"
    set +a
fi

if ! om_find; then
    om_breadcrumb "om not found - checkpoint skipped (see /om-setup)"
    exit 0
fi

# --- Throttle + lock, keyed by session ---------------------------------------
# session_end (and a manual/unknown invocation) forces a checkpoint;
# user_prompt_submit and pre_compact are throttled.
FORCE=0
case "$EVENT" in
    session_end | SessionEnd | "") FORCE=1 ;;
esac

THROTTLE_SECONDS="${OM_GROK_CHECKPOINT_INTERVAL_SECONDS:-900}"
case "$THROTTLE_SECONDS" in
    *[!0-9]* | "") THROTTLE_SECONDS=900 ;;
esac

KEY="${GROK_SESSION_ID:-global}"
KEY=$(printf '%s' "$KEY" | tr -c 'A-Za-z0-9_.-' '_')
[ -n "$KEY" ] || KEY="global"

LOCK_PATH="$OM_GROK_STATE_DIR/locks/checkpoint-$KEY.lock"
if ! om_lock_acquire "$LOCK_PATH" 60; then
    exit 0 # a checkpoint for this session is already in flight
fi

STATE_FILE="$OM_GROK_STATE_DIR/checkpoint-last/$KEY"
NOW=$(date +%s)
if [ "$FORCE" = "0" ] && [ "$THROTTLE_SECONDS" -gt 0 ]; then
    LAST=$(cat "$STATE_FILE" 2>/dev/null) || LAST=0
    case "$LAST" in
        *[!0-9]* | "") LAST=0 ;;
    esac
    if [ $((NOW - LAST)) -lt "$THROTTLE_SECONDS" ]; then
        rm -rf "$LOCK_PATH"
        exit 0
    fi
fi
mkdir -p "$OM_GROK_STATE_DIR/checkpoint-last" 2>/dev/null || {
    rm -rf "$LOCK_PATH"
    exit 0
}
printf '%s' "$NOW" >"$STATE_FILE" 2>/dev/null || true

# --- Run om grok-checkpoint in the background (async-safe) -------------------
# stdio fully detached so the hook returns immediately and grok never waits
# on an open pipe. The subshell owns the lock and releases it on exit.
# --transcript is passed only when stdin actually populated transcriptPath;
# otherwise om grok-checkpoint self-scans ~/.grok/sessions.
(
    trap 'rm -rf "$LOCK_PATH"' EXIT
    if [ -n "$TRANSCRIPT" ] && [ -f "$TRANSCRIPT" ]; then
        "$OM_BIN" grok-checkpoint --transcript "$TRANSCRIPT"
    else
        "$OM_BIN" grok-checkpoint
    fi
) </dev/null >/dev/null 2>&1 &

exit 0
