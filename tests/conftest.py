"""Shared fixtures for grok-observational-memory tests.

Every test drives the shipped scripts through subprocess inside a sandboxed
fake HOME under pytest's tmp_path. The real ~/.grok, ~/.claude, and
~/.local/state are NEVER touched: subprocess environments are built from
scratch (no inherited PATH, no inherited OM_* / provider vars).
"""

from __future__ import annotations

import json
import os
import subprocess
import sys
import time
from pathlib import Path

import pytest

REPO_ROOT = Path(__file__).resolve().parent.parent
SCRIPTS_DIR = REPO_ROOT / "scripts"

# A safe system PATH: sh/coreutils/git live here on macOS and ubuntu runners.
# Deliberately excludes any user dirs so a real `om` install can never leak in.
SYSTEM_PATH = "/usr/bin:/bin:/usr/sbin:/sbin"

DEFAULT_CONTEXT = "# Observational Memory\n\n- durable fact one\n- durable fact two"


def _read_sentinels() -> tuple[str, str]:
    """Source scripts/lib.sh to get the sentinel lines (single source of truth)."""
    res = subprocess.run(
        ["sh", "-c", '. "$0" && printf "%s\\n%s" "$OM_BLOCK_BEGIN" "$OM_BLOCK_END"', str(SCRIPTS_DIR / "lib.sh")],
        capture_output=True,
        text=True,
        check=True,
        env={"HOME": "/tmp", "PATH": SYSTEM_PATH},
    )
    begin, end = res.stdout.split("\n", 1)
    assert begin.startswith("<!--") and end.startswith("<!--")
    return begin, end


BLOCK_BEGIN, BLOCK_END = _read_sentinels()


def make_envelope(context: str = DEFAULT_CONTEXT) -> str:
    return json.dumps({"hookSpecificOutput": {"hookEventName": "SessionStart", "additionalContext": context}})


def wait_until(predicate, timeout: float = 10.0, interval: float = 0.05) -> bool:
    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        if predicate():
            return True
        time.sleep(interval)
    return predicate()


class Sandbox:
    """Fake HOME + stub-binary dir + from-scratch subprocess env."""

    def __init__(self, root: Path):
        self.root = root
        self.home = root / "home"
        self.home.mkdir(parents=True)
        self.bin = root / "stub-bin"
        self.bin.mkdir()
        # Guarantee python3 on the controlled PATH regardless of platform layout.
        (self.bin / "python3").symlink_to(sys.executable)
        self.om_log = root / "om-calls.log"

    # --- well-known paths inside the fake HOME -------------------------------
    @property
    def agents_file(self) -> Path:
        return self.home / ".grok" / "AGENTS.md"

    @property
    def hook_file(self) -> Path:
        return self.home / ".grok" / "hooks" / "grok-observational-memory.json"

    @property
    def native_hook_file(self) -> Path:
        return self.home / ".grok" / "hooks" / "observational-memory.json"

    @property
    def state_dir(self) -> Path:
        return self.home / ".local" / "state" / "grok-observational-memory"

    @property
    def registry_file(self) -> Path:
        return self.home / ".grok" / "installed-plugins" / "registry.json"

    # --- env / stubs ----------------------------------------------------------
    def env(self, **extra: str) -> dict[str, str]:
        env = {
            "HOME": str(self.home),
            "PATH": f"{self.bin}:{SYSTEM_PATH}",
            "LC_ALL": "C",
        }
        env.update(extra)
        return env

    def write_om_stub(
        self,
        context: str = DEFAULT_CONTEXT,
        version: str = "om, version 0.8.0",
        raw_context_output: str | None = None,
    ) -> Path:
        """Install a fake `om` on the sandbox PATH.

        It logs every invocation (one line per call) to self.om_log and emits a
        canned `om context` envelope. raw_context_output overrides the envelope
        verbatim (e.g. to simulate a broken om).
        """
        payload_file = self.root / "om-context-envelope.json"
        payload_file.write_text(
            raw_context_output if raw_context_output is not None else make_envelope(context),
            encoding="utf-8",
        )
        stub = self.bin / "om"
        stub.write_text(
            f"""#!/bin/sh
printf '%s\\n' "om $*" >> "{self.om_log}"
case "${{1:-}}" in
    --version) echo "{version}" ;;
    context) cat "{payload_file}" ;;
esac
exit 0
""",
            encoding="utf-8",
        )
        stub.chmod(0o755)
        return stub

    def om_calls(self) -> list[str]:
        if not self.om_log.exists():
            return []
        return [line for line in self.om_log.read_text(encoding="utf-8").splitlines() if line]

    # --- script runner ----------------------------------------------------------
    def run(
        self,
        script: str,
        *args: str,
        stdin: str = "",
        env_extra: dict[str, str] | None = None,
        script_path: Path | None = None,
        timeout: int = 30,
    ) -> subprocess.CompletedProcess:
        path = script_path if script_path is not None else SCRIPTS_DIR / script
        return subprocess.run(
            [str(path), *args],
            input=stdin,
            capture_output=True,
            text=True,
            env=self.env(**(env_extra or {})),
            timeout=timeout,
        )


@pytest.fixture
def sandbox(tmp_path: Path) -> Sandbox:
    return Sandbox(tmp_path)


@pytest.fixture
def sandbox_with_om(sandbox: Sandbox) -> Sandbox:
    sandbox.write_om_stub()
    return sandbox
