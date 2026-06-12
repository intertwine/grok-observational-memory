# shellcheck shell=sh
# shellcheck disable=SC2034  # variables are consumed by the sourcing scripts
# lib.sh — shared helpers for grok-observational-memory hook scripts.
#
# Sourced with `. "<dir>/lib.sh"` from POSIX sh scripts. Defines paths,
# the managed-block sentinels, breadcrumb logging, om discovery, and the
# mkdir-based lock with stale reclaim.
#
# IMPORTANT: callers must check OM_GROK_PLUGIN_DISABLE *before* sourcing
# this file — the kill switch is always the first line of every script.

OM_GROK_STATE_DIR="$HOME/.local/state/grok-observational-memory"
OM_GROK_HOOK_FILE="$HOME/.grok/hooks/grok-observational-memory.json"
OM_GROK_NATIVE_HOOK_FILE="$HOME/.grok/hooks/observational-memory.json"
OM_GROK_AGENTS_FILE="$HOME/.grok/AGENTS.md"
OM_GROK_REGISTRY_FILE="$HOME/.grok/installed-plugins/registry.json"

# Managed-block sentinels (single source of truth — python helpers receive
# these via argv so sh and python can never disagree).
OM_BLOCK_BEGIN="<!-- BEGIN OBSERVATIONAL MEMORY (managed by grok-observational-memory; edits inside will be overwritten) -->"
OM_BLOCK_END="<!-- END OBSERVATIONAL MEMORY -->"

# One-line diagnostic to stderr. Never pass memory content to this.
om_breadcrumb() {
    echo "observational-memory(grok): $1" >&2
}

# Locate the om CLI. Sets OM_BIN; returns 1 when not found.
om_find() {
    OM_BIN=$(command -v om 2>/dev/null) || OM_BIN=""
    if [ -z "$OM_BIN" ]; then
        for om_candidate in \
            "$HOME/.local/bin/om" \
            "$HOME/.cargo/bin/om" \
            "$HOME/.local/share/uv/tools/observational-memory/bin/om"; do
            if [ -x "$om_candidate" ]; then
                OM_BIN="$om_candidate"
                break
            fi
        done
    fi
    [ -n "$OM_BIN" ]
}

# om_lock_acquire <lock_dir_path> <stale_minutes>
# mkdir-based lock; reclaims locks older than <stale_minutes>. Returns 1 if
# the lock is held by a live peer.
om_lock_acquire() {
    om_lock_path=$1
    om_lock_stale=$2
    mkdir -p "$(dirname "$om_lock_path")" 2>/dev/null || return 1
    if mkdir "$om_lock_path" 2>/dev/null; then
        return 0
    fi
    if [ "$om_lock_stale" -gt 0 ] 2>/dev/null &&
        [ -n "$(find "$om_lock_path" -prune -mmin +"$om_lock_stale" -print -quit 2>/dev/null)" ]; then
        rm -rf "$om_lock_path" 2>/dev/null
        if mkdir "$om_lock_path" 2>/dev/null; then
            return 0
        fi
    fi
    return 1
}

# Map a hook event name (snake_case stdin/env value or CamelCase key) to the
# CamelCase key used inside hook JSON files. Echoes "" when unknown.
om_event_key() {
    case "$1" in
        session_start | SessionStart) echo "SessionStart" ;;
        session_end | SessionEnd) echo "SessionEnd" ;;
        user_prompt_submit | UserPromptSubmit) echo "UserPromptSubmit" ;;
        pre_compact | PreCompact) echo "PreCompact" ;;
        *) echo "" ;;
    esac
}

# om_hook_file_registers_event <hook_file> <CamelCaseKey>
# Structured (python3 json) check: does <hook_file> register at least one
# command hook for the event? Returns 1 on missing/unparseable file.
om_hook_file_registers_event() {
    [ -f "$1" ] || return 1
    command -v python3 >/dev/null 2>&1 || return 1
    python3 - "$1" "$2" <<'PY'
import json
import sys

try:
    with open(sys.argv[1], encoding="utf-8") as fh:
        data = json.load(fh)
except Exception:
    sys.exit(1)
groups = (data.get("hooks") or {}).get(sys.argv[2]) or []
registered = any(isinstance(g, dict) and g.get("hooks") for g in groups)
sys.exit(0 if registered else 1)
PY
}
