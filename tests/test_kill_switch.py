"""OM_GROK_PLUGIN_DISABLE=1 must short-circuit every script with zero side effects."""

from __future__ import annotations

import json

import pytest

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
