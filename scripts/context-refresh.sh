#!/bin/sh
# context-refresh.sh — regenerate the Observational Memory managed block in
# ~/.grok/AGENTS.md from bounded `om context` output.
#
# Grok Build (verified on 0.2.50) discards hook stdout, so the global
# ~/.grok/AGENTS.md file is the working context channel. This script
# maintains a sentinel-delimited managed block inside it; everything outside
# the sentinels is preserved byte-for-byte. Rules files are read before
# SessionStart hooks run, so the block lags one session by design
# (SessionEnd also routes here to keep it fresh "as of last session end").
#
# Fail-closed contract: on ANY failure the target file is left untouched,
# at most one breadcrumb line goes to stderr (never memory content), and we
# exit 0. No provider env is sourced here — `om context` needs no LLM keys.
#
# Deliberately cwd-agnostic: NO --cwd/--task flags. A global file gets
# global context; project routing comes from /recall and the skill.
#
# Usage: context-refresh.sh [--init] [--throttle SECONDS]
#   --init  allow creating the managed block in an existing AGENTS.md that
#           has none yet (setup.sh's initial write). Normal refreshes fail
#           closed instead, so a user who deleted the block stays opted out
#           until they re-run /om-setup.
#   --throttle SECONDS  skip the refresh when the last successful refresh is
#           newer than SECONDS. Used for the UserPromptSubmit registration:
#           headless sessions never deliver SessionEnd (observed on 0.2.50),
#           so a throttled per-prompt refresh is the convergence fallback —
#           without flooding `om context` on every turn.

# Kill switch FIRST — gates everything.
if [ "${OM_GROK_PLUGIN_DISABLE:-0}" = "1" ]; then
    exit 0
fi

# HOME guard BEFORE set -u / lib.sh (both expand $HOME): keep the exit-0
# contract even in a hostile hook environment with HOME unset.
if [ -z "${HOME:-}" ]; then
    echo "observational-memory(grok): HOME is unset - context refresh skipped" >&2
    exit 0
fi

set -u

SCRIPT_DIR=$(CDPATH='' cd -- "$(dirname -- "$0")" && pwd) || exit 0
# shellcheck disable=SC1091
. "$SCRIPT_DIR/lib.sh"

INIT_MODE=0
THROTTLE_SECONDS=0
while [ $# -gt 0 ]; do
    case "$1" in
        --init) INIT_MODE=1 ;;
        --throttle)
            shift
            case "${1:-}" in
                ''|*[!0-9]*)
                    om_breadcrumb "invalid --throttle value - context refresh skipped"
                    exit 0
                    ;;
                *) THROTTLE_SECONDS=$1 ;;
            esac
            ;;
        *)
            om_breadcrumb "unknown argument '$1' - context refresh skipped"
            exit 0
            ;;
    esac
    shift
done

if ! command -v python3 >/dev/null 2>&1; then
    om_breadcrumb "python3 unavailable - context refresh skipped"
    exit 0
fi

# Throttle: compare against the epoch stamp written after each successful
# refresh. Missing/unreadable stamp means "never refreshed" -> run.
REFRESH_STAMP_FILE="$OM_GROK_STATE_DIR/last-context-refresh"
if [ "$THROTTLE_SECONDS" -gt 0 ] && [ -f "$REFRESH_STAMP_FILE" ]; then
    LAST_REFRESH=$(cat "$REFRESH_STAMP_FILE" 2>/dev/null || echo 0)
    NOW_EPOCH=$(date +%s)
    case "$LAST_REFRESH" in
        *[!0-9]*|'') LAST_REFRESH=0 ;;
    esac
    if [ $((NOW_EPOCH - LAST_REFRESH)) -lt "$THROTTLE_SECONDS" ]; then
        exit 0
    fi
fi

# --- "Plugin gone" degrade -------------------------------------------------
# If grok's install registry exists, parses, MATCHES the known 0.2.50 schema,
# and no longer lists this plugin, the user-level hook file is orphaned:
# replace the block CONTENT with a one-line removal notice instead of stale
# memory. A missing/unreadable registry — or one that parses but has an
# unrecognized shape (plausible after any grok upgrade; this is an
# undocumented internal file) — is treated as "cannot determine" and does
# NOT degrade (degrading wrongly would erase working context every session).
MODE="refresh"
if [ -f "$OM_GROK_REGISTRY_FILE" ]; then
    if ! python3 - "$OM_GROK_REGISTRY_FILE" <<'PY'
import json
import sys

try:
    with open(sys.argv[1], encoding="utf-8") as fh:
        data = json.load(fh)
except Exception:
    sys.exit(0)  # unreadable registry: cannot determine — do not degrade

# Positive schema evidence required before degrading: the 0.2.50 shape is a
# top-level "repos" dict whose values are dicts carrying a "plugins" dict.
# Exit 1 (degrade) ONLY when that shape is confirmed AND the plugin is
# absent from every confirmed repo entry.
repos = data.get("repos") if isinstance(data, dict) else None
if not isinstance(repos, dict):
    sys.exit(0)  # unknown schema: cannot determine — do not degrade
confirmed = False
for repo in repos.values():
    if not isinstance(repo, dict) or not isinstance(repo.get("plugins"), dict):
        continue
    confirmed = True
    if "observational-memory" in repo["plugins"]:
        sys.exit(0)  # still installed
sys.exit(1 if confirmed else 0)
PY
    then
        MODE="removed"
    fi
fi

# --- Target resolution + sync-exposure breadcrumbs --------------------------
TARGET="$OM_GROK_AGENTS_FILE"
REAL_TARGET="$TARGET"
if [ -h "$TARGET" ]; then
    # lstat says symlink: write through to the real file so rename does not
    # silently replace the link, and warn — a symlinked AGENTS.md usually
    # means a dotfiles repo, i.e. personal memory may leave this host.
    REAL_TARGET=$(python3 -c 'import os, sys; print(os.path.realpath(sys.argv[1]))' "$TARGET" 2>/dev/null) || REAL_TARGET=""
    if [ -z "$REAL_TARGET" ]; then
        om_breadcrumb "cannot resolve AGENTS.md symlink - context refresh skipped"
        exit 0
    fi
    om_breadcrumb "warning: ~/.grok/AGENTS.md is a symlink - the OM block contains personal memory; keep it off synced/committed paths"
fi
if [ "$(git -C "$HOME/.grok" rev-parse --is-inside-work-tree 2>/dev/null)" = "true" ]; then
    om_breadcrumb "warning: ~/.grok is inside a git work tree - never commit AGENTS.md (contains personal memory)"
fi

TARGET_DIR=$(dirname "$REAL_TARGET")
if ! mkdir -p "$TARGET_DIR" 2>/dev/null; then
    om_breadcrumb "cannot create $TARGET_DIR - context refresh skipped"
    exit 0
fi
# Sweep stale temp images from runs killed before any trap fired (EXIT traps
# do not run on untrapped SIGKILL — grok's async timeout kill is realistic):
# a leftover .om-agents-refresh.* holds a full memory image in a directory
# that may be a git work tree.
find "$TARGET_DIR" -maxdepth 1 -name '.om-agents-refresh.*' -mmin +60 -exec rm -f {} + 2>/dev/null || true

# --- Cleanup trap -------------------------------------------------------------
ENV_TMP=""
TMP_FILE=""
LOCK_OWNED=0
LOCK_PATH="$OM_GROK_STATE_DIR/locks/agents-refresh.lock"
# shellcheck disable=SC2329  # invoked indirectly via the EXIT trap
cleanup() {
    if [ -n "$ENV_TMP" ]; then rm -f "$ENV_TMP"; fi
    if [ -n "$TMP_FILE" ]; then rm -f "$TMP_FILE"; fi
    # Only remove the lock we actually acquired — never a live peer's.
    if [ "$LOCK_OWNED" = "1" ]; then rm -rf "$LOCK_PATH"; fi
}
trap cleanup EXIT
# EXIT traps do not fire on untrapped signals (dash/ash semantics); trap the
# realistic ones too so 0600 temp files holding memory content are removed.
# cleanup is idempotent, so the EXIT trap re-running it is harmless.
trap 'cleanup; exit 0' INT TERM HUP

# --- Step 1: produce content (om context runs BEFORE the target is read) ------
# The envelope is captured into a 0600 temp file under the private state dir;
# the python helper parses it from there. It is never echoed anywhere.
if [ "$MODE" = "removed" ]; then
    ENVELOPE_PATH=/dev/null
else
    if ! om_find; then
        om_breadcrumb "om not found - context refresh skipped (see /om-setup)"
        exit 0
    fi
    mkdir -p "$OM_GROK_STATE_DIR/tmp" 2>/dev/null || {
        om_breadcrumb "cannot create state dir - context refresh skipped"
        exit 0
    }
    # Sweep stale envelopes from killed runs (see the trap note above):
    # they are 0600 but still hold memory content.
    find "$OM_GROK_STATE_DIR/tmp" -name '.om-envelope.*' -mmin +60 -exec rm -f {} + 2>/dev/null || true
    ENV_TMP=$(mktemp "$OM_GROK_STATE_DIR/tmp/.om-envelope.XXXXXX" 2>/dev/null) || {
        om_breadcrumb "mktemp failed in state dir - context refresh skipped"
        exit 0
    }
    # cwd-agnostic on purpose: no --cwd, no --task (global file, global context).
    "$OM_BIN" context --for grok >"$ENV_TMP" 2>/dev/null || true
    ENVELOPE_PATH="$ENV_TMP"
fi

# --- Step 2: lock + atomic read-modify-write ----------------------------------
if ! om_lock_acquire "$LOCK_PATH" 10; then
    om_breadcrumb "another refresh holds the lock - skipped"
    exit 0
fi
LOCK_OWNED=1

# mktemp in the target directory so the final rename is atomic (same fs).
# mktemp creates the file 0600, which is also the fresh-create permission.
TMP_FILE=$(mktemp "$TARGET_DIR/.om-agents-refresh.XXXXXX" 2>/dev/null) || {
    om_breadcrumb "mktemp failed in $TARGET_DIR - context refresh skipped"
    exit 0
}

STAMP=$(date -u +%Y-%m-%dT%H:%M:%SZ)

# The python helper parses the captured `om context` envelope, splices the
# block, and writes the new file image to TMP_FILE. It never writes content
# to stdout/stderr. Exit codes: 0 ok, 3 envelope parse failure, 4 malformed
# block, 5 no block (needs --init), 7 nothing to do (removed-mode no-op).
run_splice() {
    python3 - "$REAL_TARGET" "$TMP_FILE" "$STAMP" "$1" "$INIT_MODE" "$OM_BLOCK_BEGIN" "$OM_BLOCK_END" "$ENVELOPE_PATH" <<'PY'
import json
import os
import sys

target, tmp_path, stamp, mode, init_mode, BEGIN, END, envelope_path = sys.argv[1:9]

NEUTRALIZED = "<!-- (sentinel-like line neutralized by grok-observational-memory) -->"
WARNING_LINE = "Contains personal memory derived from your sessions — do not commit or sync this file."
REMOVED_NOTICE = "Observational Memory plugin removed — run /om-setup to restore or delete this block."


def is_sentinel(line, sentinel):
    # Full-line anchored match (whitespace-insensitive at the edges, matching
    # the sanitizer below so the validator and sanitizer can never disagree).
    return line.strip() == sentinel


exists = os.path.exists(target)

if mode == "removed":
    content = REMOVED_NOTICE
else:
    # Parse the captured om context envelope BEFORE touching the target.
    try:
        with open(envelope_path, encoding="utf-8") as fh:
            envelope = json.load(fh)
        content = envelope["hookSpecificOutput"]["additionalContext"]
        if not isinstance(content, str) or not content.strip():
            raise ValueError("empty additionalContext")
    except Exception:
        sys.exit(3)
    # Step 2: sanitize — neutralize any line matching a sentinel so memory
    # content can never open/close the managed block.
    out = []
    for line in content.splitlines():
        if is_sentinel(line, BEGIN) or is_sentinel(line, END):
            line = NEUTRALIZED
        out.append(line)
    content = "\n".join(out)

block = "\n".join(
    [
        BEGIN,
        "<!-- last refreshed %s -->" % stamp,
        WARNING_LINE,
        "",
        content,
        END,
    ]
)

if not exists:
    if mode == "removed":
        sys.exit(7)  # nothing to degrade
    new_text = block + "\n"
else:
    # newline="" disables universal-newline translation: CRLF user content
    # must survive byte-for-byte (sentinel matching strips the trailing \r).
    with open(target, encoding="utf-8", errors="surrogateescape", newline="") as fh:
        raw = fh.read()
    lines = raw.split("\n")
    begins = [i for i, line in enumerate(lines) if is_sentinel(line, BEGIN)]
    ends = [i for i, line in enumerate(lines) if is_sentinel(line, END)]
    if not begins and not ends:
        if mode == "removed":
            sys.exit(7)  # no block to degrade
        if init_mode != "1":
            sys.exit(5)
        sep = "" if (not raw or raw.endswith("\n")) else "\n"
        new_text = raw + sep + block + "\n"
    elif len(begins) == 1 and len(ends) == 1 and begins[0] < ends[0]:
        before = "\n".join(lines[: begins[0]])
        if begins[0] > 0:
            before += "\n"
        after = "\n".join(lines[ends[0] + 1 :])
        new_text = before + block + "\n" + after
    else:
        sys.exit(4)  # malformed: not exactly one BEGIN then one END

perm = 0o600
if exists:
    try:
        perm = os.stat(target).st_mode & 0o7777
    except OSError:
        pass

with open(tmp_path, "w", encoding="utf-8", errors="surrogateescape", newline="") as fh:
    fh.write(new_text)
    fh.flush()
    os.fsync(fh.fileno())
os.chmod(tmp_path, perm)
sys.exit(0)
PY
}

run_splice "$MODE" </dev/null
STATUS=$?

case "$STATUS" in
    0)
        # Known limitation: the symlink lstat above and this rename are not
        # atomic (TOCTOU). If AGENTS.md becomes a symlink in between, the
        # rename replaces the link with a regular file. User-self race only —
        # no privilege boundary is crossed; the next refresh warns.
        if mv -f "$TMP_FILE" "$REAL_TARGET" 2>/dev/null; then
            TMP_FILE=""
            date +%s > "$REFRESH_STAMP_FILE" 2>/dev/null || :
        else
            om_breadcrumb "atomic rename failed - AGENTS.md left untouched"
        fi
        ;;
    3) om_breadcrumb "om context unavailable or malformed - run om doctor" ;;
    4) om_breadcrumb "malformed OM block in ~/.grok/AGENTS.md - run /memory-status" ;;
    5) om_breadcrumb "no OM block in ~/.grok/AGENTS.md - run /om-setup" ;;
    7) : ;; # removed-mode no-op
    *) om_breadcrumb "context refresh failed (status $STATUS)" ;;
esac

exit 0
