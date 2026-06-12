"""run-hook — forward-compat dispatcher self-suppression vs the user-level hook file."""

from __future__ import annotations

import json
from pathlib import Path


def make_plugin_root(tmp_path: Path) -> tuple[Path, Path]:
    plugin_root = tmp_path / "plugin-root"
    (plugin_root / "scripts").mkdir(parents=True)
    marker = tmp_path / "dispatched"
    target = plugin_root / "scripts" / "context-refresh.sh"
    target.write_text(f'#!/bin/sh\ntouch "{marker}"\n', encoding="utf-8")
    target.chmod(0o755)
    return plugin_root, marker


def user_hook_payload(events: list[str]) -> str:
    return json.dumps({"hooks": {event: [{"hooks": [{"type": "command", "command": "x"}]}] for event in events}})


def test_no_plugin_root_exits_zero(sandbox):
    res = sandbox.run("run-hook", "context-refresh")
    assert res.returncode == 0
    assert res.stdout == ""


def test_unknown_script_name_exits_zero(sandbox, tmp_path):
    plugin_root, marker = make_plugin_root(tmp_path)
    res = sandbox.run(
        "run-hook",
        "rm-rf-everything",
        env_extra={"GROK_PLUGIN_ROOT": str(plugin_root)},
    )
    assert res.returncode == 0
    assert not marker.exists()


def test_dispatches_when_user_file_absent(sandbox, tmp_path):
    plugin_root, marker = make_plugin_root(tmp_path)
    res = sandbox.run(
        "run-hook",
        "context-refresh",
        env_extra={"GROK_PLUGIN_ROOT": str(plugin_root), "GROK_HOOK_EVENT": "session_start"},
    )
    assert res.returncode == 0
    assert marker.exists()


def test_suppresses_when_user_file_registers_event(sandbox, tmp_path):
    sb = sandbox
    plugin_root, marker = make_plugin_root(tmp_path)
    sb.hook_file.parent.mkdir(parents=True)
    sb.hook_file.write_text(user_hook_payload(["SessionStart"]), encoding="utf-8")
    res = sb.run(
        "run-hook",
        "context-refresh",
        env_extra={"GROK_PLUGIN_ROOT": str(plugin_root), "GROK_HOOK_EVENT": "session_start"},
    )
    assert res.returncode == 0
    assert not marker.exists()


def test_suppresses_conservatively_when_event_unknown(sandbox, tmp_path):
    sb = sandbox
    plugin_root, marker = make_plugin_root(tmp_path)
    sb.hook_file.parent.mkdir(parents=True)
    sb.hook_file.write_text(user_hook_payload(["SessionEnd"]), encoding="utf-8")
    # No GROK_HOOK_EVENT: user file exists, event undeterminable -> suppress.
    res = sb.run(
        "run-hook",
        "context-refresh",
        env_extra={"GROK_PLUGIN_ROOT": str(plugin_root)},
    )
    assert res.returncode == 0
    assert not marker.exists()


def test_dispatches_when_user_file_lacks_event(sandbox, tmp_path):
    sb = sandbox
    plugin_root, marker = make_plugin_root(tmp_path)
    sb.hook_file.parent.mkdir(parents=True)
    sb.hook_file.write_text(user_hook_payload(["SessionEnd"]), encoding="utf-8")
    res = sb.run(
        "run-hook",
        "context-refresh",
        env_extra={"GROK_PLUGIN_ROOT": str(plugin_root), "GROK_HOOK_EVENT": "session_start"},
    )
    assert res.returncode == 0
    assert marker.exists()
