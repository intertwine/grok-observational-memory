"""Manifest hygiene: plugin.json, hooks/hooks.json, versioning lockstep, exec bits."""

from __future__ import annotations

import json
import os
import re

import pytest
from conftest import REPO_ROOT, SCRIPTS_DIR

PLUGIN_JSON = REPO_ROOT / ".grok-plugin" / "plugin.json"
HOOKS_JSON = REPO_ROOT / "hooks" / "hooks.json"
NAME_RE = re.compile(r"^[a-z0-9]+(-[a-z0-9]+)*$")
HOOK_EVENTS = {"SessionStart", "SessionEnd", "UserPromptSubmit", "PreCompact"}
COMMAND_RE = re.compile(r'^"\$\{GROK_PLUGIN_ROOT\}/scripts/run-hook" (context-refresh|checkpoint)$')


def load(path):
    with open(path, encoding="utf-8") as fh:
        return json.load(fh)


def test_plugin_json_valid_and_schema_fields():
    data = load(PLUGIN_JSON)
    assert NAME_RE.match(data["name"]), data["name"]
    assert data["name"] == "observational-memory"
    assert re.match(r"^\d+\.\d+\.\d+$", data["version"])
    assert data["version"] == "0.9.0"
    assert data["license"] == "MIT"
    assert data["author"]["name"] == "Intertwine Systems"
    assert isinstance(data["description"], str)
    assert len(data["description"]) <= 120
    assert "grok-observational-memory" in data["repository"]


def test_plugin_keywords_are_branded():
    keywords = load(PLUGIN_JSON)["keywords"]
    assert keywords, "keywords must not be empty"
    assert "om" not in keywords  # no bare "om"
    assert "memory" not in keywords  # no bare "memory"


def test_hooks_json_valid_and_routed_through_run_hook():
    data = load(HOOKS_JSON)
    assert set(data["hooks"]) == HOOK_EVENTS
    for event, groups in data["hooks"].items():
        assert groups, f"{event} has no hook groups"
        for group in groups:
            assert group["hooks"], f"{event} group has no hooks"
            for hook in group["hooks"]:
                assert hook["type"] == "command"
                assert hook["async"] is True
                assert isinstance(hook["timeout"], int) and hook["timeout"] > 0
                assert isinstance(hook["statusMessage"], str) and hook["statusMessage"]
                assert COMMAND_RE.match(hook["command"]), hook["command"]


def test_hooks_json_timeouts_match_spec():
    data = load(HOOKS_JSON)
    for groups in data["hooks"].values():
        for group in groups:
            for hook in group["hooks"]:
                if "context-refresh" in hook["command"]:
                    assert hook["timeout"] == 15
                else:
                    assert hook["timeout"] == 30


def test_plugin_version_matches_changelog_head():
    changelog = REPO_ROOT / "CHANGELOG.md"
    if not changelog.exists():
        pytest.skip("CHANGELOG.md not present yet (docs task); lockstep check self-enables once it lands")
    match = re.search(r"(\d+\.\d+\.\d+)", changelog.read_text(encoding="utf-8"))
    assert match, "CHANGELOG.md has no version-shaped head entry"
    assert match.group(1) == load(PLUGIN_JSON)["version"]


def test_marketplace_description_length():
    # TODO: docs task may add docs/marketplace-entry.json (catalog PR payload);
    # until it exists this check self-skips.
    entry = REPO_ROOT / "docs" / "marketplace-entry.json"
    if not entry.exists():
        pytest.skip("docs/marketplace-entry.json not present yet (docs task)")
    data = load(entry)
    assert len(data["description"]) <= 120
    assert NAME_RE.match(data["name"])


EXECUTABLE_SCRIPTS = ["run-hook", "context-refresh.sh", "checkpoint.sh", "setup.sh", "teardown.sh"]


@pytest.mark.parametrize("name", EXECUTABLE_SCRIPTS)
def test_scripts_are_executable(name):
    path = SCRIPTS_DIR / name
    assert path.is_file()
    assert os.access(path, os.X_OK), f"{name} must be executable"


def test_lib_sh_is_sourced_not_executed():
    path = SCRIPTS_DIR / "lib.sh"
    assert path.is_file()
    assert not os.access(path, os.X_OK), "lib.sh is sourced, keep it non-executable"


@pytest.mark.parametrize("name", EXECUTABLE_SCRIPTS)
def test_scripts_are_posix_sh(name):
    first_line = (SCRIPTS_DIR / name).read_text(encoding="utf-8").splitlines()[0]
    assert first_line == "#!/bin/sh"


@pytest.mark.parametrize("name", EXECUTABLE_SCRIPTS + ["lib.sh"])
def test_kill_switch_is_first_check(name):
    """Convention: OM_GROK_PLUGIN_DISABLE gates everything, before lib.sh sourcing."""
    text = (SCRIPTS_DIR / name).read_text(encoding="utf-8")
    if name == "lib.sh":
        # lib.sh documents that callers check first; it must not be a script.
        assert "OM_GROK_PLUGIN_DISABLE" in text
        return
    body = [line for line in text.splitlines() if line.strip() and not line.strip().startswith("#")]
    assert "OM_GROK_PLUGIN_DISABLE" in body[0], f"{name}: kill switch must be the first statement"
