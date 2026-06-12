#!/bin/sh
# teardown.sh — full removal of everything /om-setup wired. Idempotent.
#
# Removes:
#   1. the user-level hook file ~/.grok/hooks/grok-observational-memory.json
#   2. the managed block in ~/.grok/AGENTS.md (ONLY the block; all user
#      content outside the sentinels is preserved byte-for-byte; the file is
#      deleted only when nothing but the block remains)
#   3. the state dir ~/.local/state/grok-observational-memory/
#
# Leaves alone: om-core's native hook file (~/.grok/hooks/
# observational-memory.json — remove with `om uninstall --grok`), om itself,
# and all memory data. Note: setup stripped SessionStart from the native
# file; re-running `om install --grok` restores native defaults.

# Kill switch FIRST — convention: first check in every script.
if [ "${OM_GROK_PLUGIN_DISABLE:-0}" = "1" ]; then
    echo "observational-memory(grok): OM_GROK_PLUGIN_DISABLE=1 - teardown skipped (unset it to tear down)" >&2
    exit 0
fi

# HOME guard BEFORE set -u / lib.sh. Teardown may exit non-zero (visible failure).
if [ -z "${HOME:-}" ]; then
    echo "error: HOME is unset - cannot locate ~/.grok" >&2
    exit 1
fi

set -u

SCRIPT_DIR=$(CDPATH='' cd -- "$(dirname -- "$0")" && pwd) || exit 1
# shellcheck disable=SC1091
. "$SCRIPT_DIR/lib.sh"

# --- 1. User-level hook file ---------------------------------------------------
if [ -f "$OM_GROK_HOOK_FILE" ]; then
    rm -f "$OM_GROK_HOOK_FILE"
    echo "Removed $OM_GROK_HOOK_FILE"
else
    echo "Hook file already absent: $OM_GROK_HOOK_FILE"
fi

# --- 2. Managed block in AGENTS.md ----------------------------------------------
# Best-effort: take the same lock context-refresh.sh uses, so an in-flight
# async refresh (grok allows it up to 15s) cannot rename a full new image
# over AGENTS.md right after the splice and resurrect the block.
TEARDOWN_LOCK="$OM_GROK_STATE_DIR/locks/agents-refresh.lock"
TEARDOWN_LOCK_HELD=0
if om_lock_acquire "$TEARDOWN_LOCK" 10; then
    TEARDOWN_LOCK_HELD=1
else
    sleep 1
    if om_lock_acquire "$TEARDOWN_LOCK" 10; then
        TEARDOWN_LOCK_HELD=1
    else
        echo "warning: a context refresh may be in flight - re-run /om-teardown if the block reappears" >&2
    fi
fi
if [ -f "$OM_GROK_AGENTS_FILE" ] && command -v python3 >/dev/null 2>&1; then
    python3 - "$OM_GROK_AGENTS_FILE" "$OM_BLOCK_BEGIN" "$OM_BLOCK_END" <<'PY'
import os
import sys
import tempfile

path, BEGIN, END = sys.argv[1:4]
real = os.path.realpath(path)

try:
    # newline="" disables universal-newline translation (CRLF user content
    # must survive the splice byte-for-byte).
    with open(real, encoding="utf-8", errors="surrogateescape", newline="") as fh:
        raw = fh.read()
except OSError:
    sys.exit(0)

lines = raw.split("\n")
begins = [i for i, line in enumerate(lines) if line.strip() == BEGIN]
ends = [i for i, line in enumerate(lines) if line.strip() == END]

if not begins and not ends:
    print("No OM managed block in ~/.grok/AGENTS.md")
elif len(begins) == 1 and len(ends) == 1 and begins[0] < ends[0]:
    remaining = lines[: begins[0]] + lines[ends[0] + 1 :]
    new_text = "\n".join(remaining)
    if not new_text.strip():
        os.unlink(real)
        print("Removed ~/.grok/AGENTS.md (contained only the OM managed block)")
    else:
        try:
            perm = os.stat(real).st_mode & 0o7777
        except OSError:
            perm = 0o600
        fd, tmp = tempfile.mkstemp(prefix=".om-agents-teardown.", dir=os.path.dirname(real))
        with os.fdopen(fd, "w", encoding="utf-8", errors="surrogateescape", newline="") as fh:
            fh.write(new_text)
            fh.flush()
            os.fsync(fh.fileno())
        os.chmod(tmp, perm)
        os.replace(tmp, real)
        print("Removed OM managed block from ~/.grok/AGENTS.md (user content preserved)")
else:
    print(
        "warning: malformed OM block in ~/.grok/AGENTS.md - left untouched, remove the sentinel lines manually",
        file=sys.stderr,
    )
PY
elif [ -f "$OM_GROK_AGENTS_FILE" ]; then
    echo "warning: python3 unavailable - remove the OM block from ~/.grok/AGENTS.md manually" >&2
else
    echo "AGENTS.md already absent: $OM_GROK_AGENTS_FILE"
fi
if [ "$TEARDOWN_LOCK_HELD" = "1" ]; then
    rm -rf "$TEARDOWN_LOCK"
fi

# --- 3. State dir ----------------------------------------------------------------
# Safe even when this script runs from $OM_GROK_STATE_DIR/bin/: the open
# file descriptor keeps the script readable after unlink.
if [ -d "$OM_GROK_STATE_DIR" ]; then
    rm -rf "$OM_GROK_STATE_DIR"
    echo "Removed $OM_GROK_STATE_DIR"
else
    echo "State dir already absent: $OM_GROK_STATE_DIR"
fi

echo "Teardown complete. (om itself, your memory data, and om-core's native"
echo "Grok hook file were left in place; use 'om uninstall --grok' for the latter.)"
exit 0
