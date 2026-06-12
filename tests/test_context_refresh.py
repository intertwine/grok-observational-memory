"""context-refresh.sh — managed AGENTS.md block behavior (fail-closed write path)."""

from __future__ import annotations

import json
import os
import re

from conftest import BLOCK_BEGIN, BLOCK_END, SCRIPTS_DIR, make_envelope

SCRIPT = "context-refresh.sh"


def block_line_counts(text: str) -> tuple[int, int]:
    lines = text.split("\n")
    begins = sum(1 for line in lines if line.strip() == BLOCK_BEGIN)
    ends = sum(1 for line in lines if line.strip() == BLOCK_END)
    return begins, ends


def strip_stamp(text: str) -> str:
    return re.sub(r"<!-- last refreshed [0-9TZ:.-]+ -->", "<!-- last refreshed X -->", text)


def existing_block_file(content: str = "stale memory") -> str:
    return f"{BLOCK_BEGIN}\n{content}\n{BLOCK_END}\n"


def test_fresh_create_writes_block_with_mode_600(sandbox_with_om):
    sb = sandbox_with_om
    res = sb.run(SCRIPT)
    assert res.returncode == 0
    assert res.stdout == ""  # memory content never goes to stdout
    text = sb.agents_file.read_text(encoding="utf-8")
    assert block_line_counts(text) == (1, 1)
    assert "durable fact one" in text
    assert "last refreshed " in text
    assert "do not commit or sync this file" in text
    assert (sb.agents_file.stat().st_mode & 0o777) == 0o600


def test_existing_file_permissions_preserved(sandbox_with_om):
    sb = sandbox_with_om
    sb.agents_file.parent.mkdir(parents=True)
    sb.agents_file.write_text(existing_block_file(), encoding="utf-8")
    sb.agents_file.chmod(0o644)
    res = sb.run(SCRIPT)
    assert res.returncode == 0
    assert "durable fact one" in sb.agents_file.read_text(encoding="utf-8")
    assert (sb.agents_file.stat().st_mode & 0o777) == 0o644


def test_block_writer_idempotent(sandbox_with_om):
    sb = sandbox_with_om
    assert sb.run(SCRIPT).returncode == 0
    first = sb.agents_file.read_text(encoding="utf-8")
    assert sb.run(SCRIPT).returncode == 0
    second = sb.agents_file.read_text(encoding="utf-8")
    assert block_line_counts(second) == (1, 1)
    assert strip_stamp(first) == strip_stamp(second)


def test_user_content_preserved_byte_for_byte(sandbox_with_om):
    sb = sandbox_with_om
    prefix = "# My agents file\n\nline with trailing space   \n"
    suffix = "tail content\nlast line without trailing newline"
    original = prefix + existing_block_file() + suffix
    sb.agents_file.parent.mkdir(parents=True)
    sb.agents_file.write_bytes(original.encode("utf-8"))

    assert sb.run(SCRIPT).returncode == 0
    text = sb.agents_file.read_text(encoding="utf-8")
    assert text[: text.index(BLOCK_BEGIN)] == prefix
    assert text[text.index(BLOCK_END) + len(BLOCK_END) + 1 :] == suffix
    assert "durable fact one" in text


def test_sentinel_injection_neutralized(sandbox_with_om):
    sb = sandbox_with_om
    evil = f"benign line\n{BLOCK_BEGIN}\nfake injected memory\n  {BLOCK_END}  \ntrailing"
    sb.write_om_stub(context=evil)
    suffix = "user tail stays outside the block\n"
    sb.agents_file.parent.mkdir(parents=True)
    sb.agents_file.write_text(existing_block_file() + suffix, encoding="utf-8")

    assert sb.run(SCRIPT).returncode == 0
    text = sb.agents_file.read_text(encoding="utf-8")
    assert block_line_counts(text) == (1, 1)  # injected sentinels neutralized
    assert text.count("sentinel-like line neutralized") == 2
    assert text.endswith(suffix)
    # the file must still be re-spliceable on the next refresh
    assert sb.run(SCRIPT).returncode == 0
    assert block_line_counts(sb.agents_file.read_text(encoding="utf-8")) == (1, 1)


def test_malformed_block_fails_closed(sandbox_with_om):
    sb = sandbox_with_om
    malformed = f"{BLOCK_BEGIN}\nfirst\n{BLOCK_BEGIN}\nsecond\n{BLOCK_END}\n"
    sb.agents_file.parent.mkdir(parents=True)
    sb.agents_file.write_bytes(malformed.encode("utf-8"))
    res = sb.run(SCRIPT)
    assert res.returncode == 0
    assert sb.agents_file.read_bytes() == malformed.encode("utf-8")
    assert "malformed" in res.stderr
    assert "durable fact one" not in res.stderr  # breadcrumbs never carry memory


def test_no_block_without_init_fails_closed(sandbox_with_om):
    sb = sandbox_with_om
    original = "just user content, no OM block\n"
    sb.agents_file.parent.mkdir(parents=True)
    sb.agents_file.write_bytes(original.encode("utf-8"))
    res = sb.run(SCRIPT)
    assert res.returncode == 0
    assert sb.agents_file.read_bytes() == original.encode("utf-8")
    assert "om-setup" in res.stderr


def test_init_appends_block_to_existing_file(sandbox_with_om):
    sb = sandbox_with_om
    original = "user content first\n"
    sb.agents_file.parent.mkdir(parents=True)
    sb.agents_file.write_text(original, encoding="utf-8")
    assert sb.run(SCRIPT, "--init").returncode == 0
    text = sb.agents_file.read_text(encoding="utf-8")
    assert text.startswith(original)
    assert block_line_counts(text) == (1, 1)


def test_symlinked_agents_file_written_through(sandbox_with_om, tmp_path):
    sb = sandbox_with_om
    real = tmp_path / "elsewhere" / "agents-real.md"
    real.parent.mkdir(parents=True)
    real.write_text(existing_block_file(), encoding="utf-8")
    sb.agents_file.parent.mkdir(parents=True)
    sb.agents_file.symlink_to(real)

    res = sb.run(SCRIPT)
    assert res.returncode == 0
    assert sb.agents_file.is_symlink()  # rename must not replace the link
    assert "durable fact one" in real.read_text(encoding="utf-8")
    assert "symlink" in res.stderr


def test_om_garbage_output_fails_closed(sandbox):
    sb = sandbox
    sb.write_om_stub(raw_context_output="this is not json {")
    original = existing_block_file()
    sb.agents_file.parent.mkdir(parents=True)
    sb.agents_file.write_bytes(original.encode("utf-8"))
    res = sb.run(SCRIPT)
    assert res.returncode == 0
    assert sb.agents_file.read_bytes() == original.encode("utf-8")
    assert "om context" in res.stderr


def test_om_missing_fails_closed(sandbox):
    sb = sandbox  # no om stub installed
    res = sb.run(SCRIPT)
    assert res.returncode == 0
    assert not sb.agents_file.exists()
    assert "om not found" in res.stderr


def test_plugin_gone_degrades_block_to_notice(sandbox_with_om):
    sb = sandbox_with_om
    sb.agents_file.parent.mkdir(parents=True)
    sb.agents_file.write_text(existing_block_file("old memory content"), encoding="utf-8")
    sb.registry_file.parent.mkdir(parents=True)
    sb.registry_file.write_text(
        json.dumps({"repos": {"example/repo": {"plugins": {"some-other-plugin": {}}}}}),
        encoding="utf-8",
    )
    res = sb.run(SCRIPT)
    assert res.returncode == 0
    text = sb.agents_file.read_text(encoding="utf-8")
    assert "Observational Memory plugin removed" in text
    assert "old memory content" not in text
    assert not any("om context" in call for call in sb.om_calls())


def test_registry_unknown_schema_does_not_degrade(sandbox_with_om):
    """A registry that parses but has an unexpected shape (plausible after any
    grok upgrade) is 'cannot determine': the working block must refresh
    normally, never be replaced with the removal notice."""
    sb = sandbox_with_om
    sb.agents_file.parent.mkdir(parents=True)
    sb.agents_file.write_text(existing_block_file("old memory content"), encoding="utf-8")
    sb.registry_file.parent.mkdir(parents=True)
    sb.registry_file.write_text(json.dumps({"installed": ["some-other-plugin"]}), encoding="utf-8")
    res = sb.run(SCRIPT)
    assert res.returncode == 0
    text = sb.agents_file.read_text(encoding="utf-8")
    assert "Observational Memory plugin removed" not in text
    assert "durable fact one" in text  # normal refresh happened


def test_registry_without_confirmed_repo_shape_does_not_degrade(sandbox_with_om):
    """`repos` present but no entry carries a `plugins` dict: schema not
    positively confirmed -> no degrade."""
    sb = sandbox_with_om
    sb.agents_file.parent.mkdir(parents=True)
    sb.agents_file.write_text(existing_block_file(), encoding="utf-8")
    sb.registry_file.parent.mkdir(parents=True)
    sb.registry_file.write_text(json.dumps({"repos": {"example/repo": {"version": 2}}}), encoding="utf-8")
    assert sb.run(SCRIPT).returncode == 0
    text = sb.agents_file.read_text(encoding="utf-8")
    assert "Observational Memory plugin removed" not in text
    assert "durable fact one" in text


def test_registry_unparseable_does_not_degrade(sandbox_with_om):
    sb = sandbox_with_om
    sb.agents_file.parent.mkdir(parents=True)
    sb.agents_file.write_text(existing_block_file(), encoding="utf-8")
    sb.registry_file.parent.mkdir(parents=True)
    sb.registry_file.write_text("{not json", encoding="utf-8")
    assert sb.run(SCRIPT).returncode == 0
    text = sb.agents_file.read_text(encoding="utf-8")
    assert "Observational Memory plugin removed" not in text
    assert "durable fact one" in text


def test_registry_listing_plugin_refreshes_normally(sandbox_with_om):
    sb = sandbox_with_om
    sb.registry_file.parent.mkdir(parents=True)
    sb.registry_file.write_text(
        json.dumps({"repos": {"intertwine/grok-observational-memory": {"plugins": {"observational-memory": {}}}}}),
        encoding="utf-8",
    )
    assert sb.run(SCRIPT).returncode == 0
    assert "durable fact one" in sb.agents_file.read_text(encoding="utf-8")


def test_crlf_agents_file_user_content_preserved(sandbox_with_om):
    """CRLF user content survives a refresh byte-for-byte (sentinel matching
    strips the trailing \\r; surrogateescape round-trips the rest)."""
    sb = sandbox_with_om
    prefix = "# user heading\r\nline two\r\n"
    original = prefix + f"{BLOCK_BEGIN}\r\nold\r\n{BLOCK_END}\r\n"
    sb.agents_file.parent.mkdir(parents=True)
    sb.agents_file.write_bytes(original.encode("utf-8"))
    assert sb.run(SCRIPT).returncode == 0
    raw = sb.agents_file.read_bytes().decode("utf-8")  # no newline translation
    assert raw.startswith(prefix)
    assert block_line_counts(raw) == (1, 1)
    assert "durable fact one" in raw


def test_om_context_invocation_has_no_cwd_or_task_flag():
    """Binding amendment A3: the refresh is cwd-agnostic."""
    text = (SCRIPTS_DIR / "context-refresh.sh").read_text(encoding="utf-8")
    invocations = [
        line
        for line in text.splitlines()
        if "OM_BIN" in line and " context" in line and not line.lstrip().startswith("#")
    ]
    assert invocations, "expected an om context invocation in context-refresh.sh"
    for line in invocations:
        assert "--cwd" not in line
        assert "--task" not in line


def test_throttle_skips_when_recent_refresh(sandbox_with_om):
    sb = sandbox_with_om
    assert sb.run(SCRIPT).returncode == 0
    first = sb.agents_file.read_text(encoding="utf-8")
    calls_before = len(sb.om_calls())
    res = sb.run(SCRIPT, "--throttle", "900")
    assert res.returncode == 0
    # within the throttle window: om not invoked, file untouched
    assert len(sb.om_calls()) == calls_before
    assert sb.agents_file.read_text(encoding="utf-8") == first


def test_throttle_runs_when_stamp_stale(sandbox_with_om):
    sb = sandbox_with_om
    assert sb.run(SCRIPT).returncode == 0
    stamp = sb.state_dir / "last-context-refresh"
    assert stamp.is_file()
    stamp.write_text("0", encoding="utf-8")  # epoch 0 = long stale
    calls_before = len(sb.om_calls())
    assert sb.run(SCRIPT, "--throttle", "900").returncode == 0
    assert len(sb.om_calls()) > calls_before


def test_throttle_runs_when_stamp_missing(sandbox_with_om):
    sb = sandbox_with_om
    res = sb.run(SCRIPT, "--throttle", "900")
    assert res.returncode == 0
    # no prior stamp: refresh proceeds and creates the block
    assert sb.agents_file.is_file()
    assert (sb.state_dir / "last-context-refresh").is_file()


def test_throttle_invalid_value_fails_closed(sandbox_with_om):
    sb = sandbox_with_om
    res = sb.run(SCRIPT, "--throttle", "bogus")
    assert res.returncode == 0
    assert not sb.agents_file.exists()
    assert len(sb.om_calls()) == 0
