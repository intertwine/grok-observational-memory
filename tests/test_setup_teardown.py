"""setup.sh / teardown.sh — wiring, idempotency, version floor, zero residue."""

from __future__ import annotations

import json
import os
import re
import subprocess

import pytest
from conftest import BLOCK_BEGIN, BLOCK_END, SYSTEM_PATH

GUARD_RE = re.compile(r"^if \[ -x (?P<p1>\S+) \]; then exec (?P<p2>\S+)(?P<args>(?: \S+)*); fi; exit 0$")
BIN_SCRIPTS = ["lib.sh", "context-refresh.sh", "checkpoint.sh", "teardown.sh"]


def run_setup(sb, *args):
    return sb.run("setup.sh", *args)


def block_count(text: str) -> int:
    return sum(1 for line in text.split("\n") if line.strip() == BLOCK_BEGIN)


def test_setup_wires_everything(sandbox_with_om):
    sb = sandbox_with_om
    res = run_setup(sb)
    assert res.returncode == 0, res.stderr

    # native om wiring requested; tests run without a TTY, so setup must add
    # --non-interactive (om install prompts for a provider profile otherwise)
    assert "om install --grok --non-interactive" in sb.om_calls()
    # scripts copied to the stable bin dir, executable
    for name in BIN_SCRIPTS:
        path = sb.state_dir / "bin" / name
        assert path.is_file()
        assert os.access(path, os.X_OK)
    # hook file written with all four events
    data = json.loads(sb.hook_file.read_text(encoding="utf-8"))
    assert sorted(data["hooks"]) == ["PreCompact", "SessionEnd", "SessionStart", "UserPromptSubmit"]
    # initial managed block written
    text = sb.agents_file.read_text(encoding="utf-8")
    assert block_count(text) == 1
    assert "durable fact one" in text


def test_setup_bakes_absolute_self_guarding_commands(sandbox_with_om):
    sb = sandbox_with_om
    assert run_setup(sb).returncode == 0
    data = json.loads(sb.hook_file.read_text(encoding="utf-8"))
    bin_dir = str(sb.state_dir / "bin")

    seen = {}
    for event, groups in data["hooks"].items():
        for group in groups:
            for hook in group["hooks"]:
                assert hook["type"] == "command"
                assert hook["async"] is True
                assert isinstance(hook["timeout"], int)
                assert isinstance(hook["statusMessage"], str) and hook["statusMessage"]
                match = GUARD_RE.match(hook["command"])
                assert match, f"not self-guarding: {hook['command']}"
                assert match["p1"] == match["p2"]
                assert os.path.isabs(match["p1"])
                assert match["p1"].startswith(bin_dir + "/")
                seen.setdefault(event, []).append(
                    (os.path.basename(match["p1"]), hook["timeout"], match["args"].strip())
                )

    assert seen["SessionStart"] == [("context-refresh.sh", 15, "")]
    assert seen["SessionEnd"] == [("context-refresh.sh", 15, ""), ("checkpoint.sh", 30, "")]
    # throttled refresh on every prompt: headless sessions never deliver
    # SessionEnd (live finding on 0.2.50), so this is the convergence fallback
    assert seen["UserPromptSubmit"] == [
        ("context-refresh.sh", 15, "--throttle 900"),
        ("checkpoint.sh", 30, ""),
    ]
    assert seen["PreCompact"] == [("checkpoint.sh", 30, "")]


def test_setup_idempotent_rerun_converges(sandbox_with_om):
    sb = sandbox_with_om
    assert run_setup(sb).returncode == 0
    hook_payload = sb.hook_file.read_bytes()
    assert run_setup(sb).returncode == 0
    assert sb.hook_file.read_bytes() == hook_payload
    assert block_count(sb.agents_file.read_text(encoding="utf-8")) == 1


def test_setup_strips_native_session_start_only(sandbox_with_om):
    sb = sandbox_with_om
    sb.native_hook_file.parent.mkdir(parents=True)
    sb.native_hook_file.write_text(
        json.dumps(
            {
                "hooks": {
                    "SessionStart": [{"hooks": [{"type": "command", "command": "om context"}]}],
                    "SessionEnd": [{"hooks": [{"type": "command", "command": "om grok-checkpoint"}]}],
                }
            }
        ),
        encoding="utf-8",
    )
    assert run_setup(sb).returncode == 0
    native = json.loads(sb.native_hook_file.read_text(encoding="utf-8"))
    assert "SessionStart" not in native["hooks"]
    assert "SessionEnd" in native["hooks"]


@pytest.mark.parametrize("version", ["om, version 0.7.9", "om, version 0.9.0", "om, version 1.2.0"])
def test_setup_rejects_om_outside_version_floor(sandbox, version):
    sb = sandbox
    sb.write_om_stub(version=version)
    res = run_setup(sb)
    assert res.returncode != 0
    assert ">=0.8,<0.9" in res.stderr
    assert not sb.hook_file.exists()


def test_setup_fails_without_om(sandbox):
    res = run_setup(sandbox)
    assert res.returncode != 0
    assert "om CLI was not found" in res.stderr


def _git_init(sb, path):
    subprocess.run(
        ["git", "init", "-q", str(path)],
        check=True,
        capture_output=True,
        env={"HOME": str(sb.home), "PATH": SYSTEM_PATH},
    )


def test_setup_sync_exposure_requires_ack(sandbox_with_om):
    sb = sandbox_with_om
    (sb.home / ".grok").mkdir(parents=True)
    _git_init(sb, sb.home / ".grok")

    res = run_setup(sb)  # non-interactive, no ack
    assert res.returncode != 0
    assert "--ack-sync-risk" in res.stderr
    assert not sb.hook_file.exists()

    res = run_setup(sb, "--ack-sync-risk")
    assert res.returncode == 0, res.stderr
    assert sb.hook_file.exists()


def test_teardown_zero_residue(sandbox_with_om):
    sb = sandbox_with_om
    sb.native_hook_file.parent.mkdir(parents=True)
    native_payload = json.dumps(
        {"hooks": {"SessionEnd": [{"hooks": [{"type": "command", "command": "om grok-checkpoint"}]}]}}
    )
    sb.native_hook_file.write_text(native_payload, encoding="utf-8")
    assert run_setup(sb).returncode == 0

    # run the COPY in the state dir it deletes (the live wiring path)
    res = sb.run("teardown.sh", script_path=sb.state_dir / "bin" / "teardown.sh")
    assert res.returncode == 0
    assert not sb.hook_file.exists()
    assert not sb.state_dir.exists()
    assert not sb.agents_file.exists()  # block was the sole content -> file removed
    # native om wiring is not ours to remove
    assert json.loads(sb.native_hook_file.read_text(encoding="utf-8"))["hooks"]


def test_teardown_preserves_user_content(sandbox_with_om):
    sb = sandbox_with_om
    user_content = "# Mine\nsome text\n"
    sb.agents_file.parent.mkdir(parents=True)
    sb.agents_file.write_bytes(user_content.encode("utf-8"))
    assert run_setup(sb).returncode == 0
    assert block_count(sb.agents_file.read_text(encoding="utf-8")) == 1

    assert sb.run("teardown.sh").returncode == 0
    assert sb.agents_file.read_bytes() == user_content.encode("utf-8")


def test_teardown_idempotent(sandbox_with_om):
    sb = sandbox_with_om
    assert run_setup(sb).returncode == 0
    assert sb.run("teardown.sh").returncode == 0
    res = sb.run("teardown.sh")
    assert res.returncode == 0


def test_teardown_through_symlinked_agents_file(sandbox, tmp_path):
    """Teardown splices through to the real file (realpath) and never replaces
    the symlink with a regular file."""
    sb = sandbox
    real = tmp_path / "elsewhere" / "agents-real.md"
    real.parent.mkdir(parents=True)
    user_content = "# mine\nkeep this\n"
    real.write_text(f"{user_content}{BLOCK_BEGIN}\nold memory\n{BLOCK_END}\n", encoding="utf-8")
    sb.agents_file.parent.mkdir(parents=True)
    sb.agents_file.symlink_to(real)

    res = sb.run("teardown.sh")
    assert res.returncode == 0
    assert sb.agents_file.is_symlink()
    text = real.read_text(encoding="utf-8")
    assert "old memory" not in text
    assert BLOCK_BEGIN not in text
    assert user_content.strip() in text


def test_teardown_leaves_malformed_block_untouched(sandbox):
    sb = sandbox
    malformed = f"{BLOCK_BEGIN}\nuser data\n{BLOCK_END}\n{BLOCK_END}\n"
    sb.agents_file.parent.mkdir(parents=True)
    sb.agents_file.write_bytes(malformed.encode("utf-8"))
    res = sb.run("teardown.sh")
    assert res.returncode == 0
    assert sb.agents_file.read_bytes() == malformed.encode("utf-8")
    assert "malformed" in res.stderr
