"""checkpoint.sh — Grok envelope parsing, throttle, and runtime dedup."""

from __future__ import annotations

import json
import time

from conftest import wait_until

SCRIPT = "checkpoint.sh"
SESSION = "sess-1"


def envelope(event: str, transcript: str | None = None) -> str:
    data: dict = {"hookEventName": event}
    if transcript is not None:
        data["transcriptPath"] = transcript  # camelCase key, real Grok shape
    return json.dumps(data)


def lock_released(sb, key: str = SESSION) -> bool:
    return not (sb.state_dir / "locks" / f"checkpoint-{key}.lock").exists()


def test_envelope_transcript_passed_to_om(sandbox_with_om, tmp_path):
    sb = sandbox_with_om
    transcript = tmp_path / "session.jsonl"
    transcript.write_text('{"role":"user"}\n', encoding="utf-8")
    res = sb.run(
        SCRIPT,
        stdin=envelope("session_end", str(transcript)),
        env_extra={"GROK_SESSION_ID": SESSION},
    )
    assert res.returncode == 0
    assert res.stdout == ""
    assert wait_until(lambda: len(sb.om_calls()) == 1)
    assert sb.om_calls() == [f"om grok-checkpoint --transcript {transcript}"]
    assert wait_until(lambda: lock_released(sb))


def test_missing_transcript_falls_back_to_self_scan(sandbox_with_om, tmp_path):
    sb = sandbox_with_om
    res = sb.run(
        SCRIPT,
        stdin=envelope("session_end", str(tmp_path / "does-not-exist.jsonl")),
        env_extra={"GROK_SESSION_ID": SESSION},
    )
    assert res.returncode == 0
    assert wait_until(lambda: sb.om_calls() == ["om grok-checkpoint"])


def test_user_prompt_submit_is_throttled(sandbox_with_om):
    sb = sandbox_with_om
    env = {"GROK_SESSION_ID": SESSION, "OM_GROK_CHECKPOINT_INTERVAL_SECONDS": "900"}

    assert sb.run(SCRIPT, stdin=envelope("user_prompt_submit"), env_extra=env).returncode == 0
    assert wait_until(lambda: len(sb.om_calls()) == 1)
    assert wait_until(lambda: lock_released(sb))

    # Second prompt within the interval: throttled, no new om run.
    assert sb.run(SCRIPT, stdin=envelope("user_prompt_submit"), env_extra=env).returncode == 0
    time.sleep(0.5)
    assert len(sb.om_calls()) == 1


def test_session_end_forces_despite_throttle(sandbox_with_om):
    sb = sandbox_with_om
    env = {"GROK_SESSION_ID": SESSION, "OM_GROK_CHECKPOINT_INTERVAL_SECONDS": "900"}

    assert sb.run(SCRIPT, stdin=envelope("user_prompt_submit"), env_extra=env).returncode == 0
    assert wait_until(lambda: len(sb.om_calls()) == 1)
    assert wait_until(lambda: lock_released(sb))

    assert sb.run(SCRIPT, stdin=envelope("session_end"), env_extra=env).returncode == 0
    assert wait_until(lambda: len(sb.om_calls()) == 2)


def native_hook_file(events: list[str]) -> dict:
    return {"hooks": {event: [{"hooks": [{"type": "command", "command": "om grok-checkpoint"}]}] for event in events}}


def test_runtime_dedup_defers_to_native_hook_file(sandbox_with_om):
    sb = sandbox_with_om
    sb.native_hook_file.parent.mkdir(parents=True)
    sb.native_hook_file.write_text(json.dumps(native_hook_file(["SessionEnd"])), encoding="utf-8")
    res = sb.run(SCRIPT, stdin=envelope("session_end"), env_extra={"GROK_SESSION_ID": SESSION})
    assert res.returncode == 0
    time.sleep(0.5)
    assert sb.om_calls() == []  # native wiring owns this event


def test_dedup_only_suppresses_registered_events(sandbox_with_om):
    sb = sandbox_with_om
    sb.native_hook_file.parent.mkdir(parents=True)
    sb.native_hook_file.write_text(json.dumps(native_hook_file(["SessionEnd"])), encoding="utf-8")
    res = sb.run(
        SCRIPT,
        stdin=envelope("user_prompt_submit"),
        env_extra={"GROK_SESSION_ID": SESSION},
    )
    assert res.returncode == 0
    assert wait_until(lambda: sb.om_calls() == ["om grok-checkpoint"])
