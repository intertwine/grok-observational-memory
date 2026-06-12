"""Environment guards: OM_GROK_PLUGIN_DISABLE=1 must short-circuit every script
with zero side effects, and hook scripts must keep the exit-0 contract even
when HOME is unset (no raw `set -u` errors)."""

from __future__ import annotations

import json
import subprocess

import pytest
from conftest import SCRIPTS_DIR, SYSTEM_PATH

KILL = {"OM_GROK_PLUGIN_DISABLE": "1"}


@pytest.mark.parametrize(
    ("script", "args", "stdin"),
    [
        ("context-refresh.sh", (), ""),
        ("checkpoint.sh", (), "{}"),
        ("setup.sh", ("--ack-sync-risk",), ""),
        ("run-hook", ("context-refresh",), ""),
    ],
)
def test_kill_switch_short_circuits(sandbox_with_om, script, args, stdin):
    sb = sandbox_with_om
    res = sb.run(script, *args, stdin=stdin, env_extra=KILL)
    assert res.returncode == 0
    assert res.stdout == ""
    assert not (sb.home / ".grok").exists()
    assert not sb.state_dir.exists()
    assert sb.om_calls() == []


def test_kill_switch_run_hook_does_not_dispatch(sandbox, tmp_path):
    plugin_root = tmp_path / "plugin-root"
    (plugin_root / "scripts").mkdir(parents=True)
    marker = tmp_path / "dispatched"
    target = plugin_root / "scripts" / "context-refresh.sh"
    target.write_text(f'#!/bin/sh\ntouch "{marker}"\n', encoding="utf-8")
    target.chmod(0o755)

    res = sandbox.run(
        "run-hook",
        "context-refresh",
        env_extra=KILL | {"GROK_PLUGIN_ROOT": str(plugin_root), "GROK_HOOK_EVENT": "session_start"},
    )
    assert res.returncode == 0
    assert not marker.exists()


@pytest.mark.parametrize(
    ("script", "args", "stdin"),
    [
        ("context-refresh.sh", (), ""),
        ("checkpoint.sh", (), "{}"),
        ("run-hook", ("context-refresh",), ""),
    ],
)
def test_home_unset_hook_scripts_fail_closed(script, args, stdin):
    """Hook scripts must exit 0 with a breadcrumb when HOME is unset, instead
    of dying on a raw `set -u` unbound-variable error."""
    res = subprocess.run(
        [str(SCRIPTS_DIR / script), *args],
        input=stdin,
        capture_output=True,
        text=True,
        env={"PATH": SYSTEM_PATH, "LC_ALL": "C"},  # no HOME on purpose
        timeout=30,
    )
    assert res.returncode == 0
    assert res.stdout == ""
    assert "HOME is unset" in res.stderr
    assert "unbound variable" not in res.stderr


def test_kill_switch_teardown_leaves_wiring_intact(sandbox):
    sb = sandbox
    sb.hook_file.parent.mkdir(parents=True)
    sb.hook_file.write_text(json.dumps({"hooks": {}}), encoding="utf-8")
    sb.state_dir.mkdir(parents=True)
    sb.agents_file.write_text("content\n", encoding="utf-8")

    res = sb.run("teardown.sh", env_extra=KILL)
    assert res.returncode == 0
    assert sb.hook_file.exists()
    assert sb.state_dir.exists()
    assert sb.agents_file.exists()
    assert "OM_GROK_PLUGIN_DISABLE" in res.stderr
