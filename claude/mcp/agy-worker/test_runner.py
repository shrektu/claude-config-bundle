import fcntl
import json
import time
from pathlib import Path

import agy_runner
import agy_worker
import pytest
from agy_errors import AgyUnavailableError
from agy_runner import AgyJob, AgyRun
from helpers_test import (
    FLASH_LOW_MODEL,
    MAX_AUTH_SECONDS,
    WHAT_CHANGED,
    FakeAgy,
    plan_review,
    process_gone,
    wait_until,
)

PLAIN_JOB = AgyJob("prompt", "gemini-4-argon-high", 600, None)
SCHEMA_JOB = AgyJob("prompt", "gemini-4-argon-high", 600, "{}")


def agy_run(stdout: str, stderr: str = "", returncode: int = 0) -> AgyRun:
    return AgyRun(stdout, stderr, returncode)


def envelope_line(**fields: object) -> str:
    body = {"conversation_id": "c1", "status": "SUCCESS", "response": "ok"}
    return json.dumps({**body, **fields})


def raise_value_error() -> str:
    message = "embedded null byte"
    raise ValueError(message)


def raise_runtime_error() -> str:
    message = "Could not determine home directory."
    raise RuntimeError(message)


def use_mode(monkeypatch: pytest.MonkeyPatch, mode: str) -> None:
    monkeypatch.setenv("AGY_FAKE_MODE", mode)


def test_parse_envelope_takes_last_json_line_and_skips_log_noise() -> None:
    stdout = (
        f"{envelope_line(response='old')}\nlog: finished\n"
        f"{envelope_line(response='new')}\n"
    )

    envelope = agy_runner.parse_envelope(stdout)

    assert envelope is not None
    assert envelope.response == "new"


def test_parse_envelope_returns_none_without_json_object() -> None:
    assert agy_runner.parse_envelope("hello\n[1, 2]\n{broken\n") is None


@pytest.mark.parametrize(
    ("stdout", "job", "reason"),
    [
        (envelope_line(response="  "), PLAIN_JOB, "empty response"),
        (envelope_line(), SCHEMA_JOB, "no structured output"),
        (
            envelope_line(status="ERROR", error="bad model"),
            PLAIN_JOB,
            "status ERROR: bad model",
        ),
        (
            envelope_line(status="CANCELED", response=""),
            PLAIN_JOB,
            "status CANCELED",
        ),
    ],
)
def test_read_envelope_rejects_what_is_not_a_success(
    stdout: str, job: AgyJob, reason: str
) -> None:
    with pytest.raises(AgyUnavailableError) as raised:
        agy_runner.read_envelope(agy_run(stdout), job)

    assert reason in raised.value.reason


def test_read_envelope_accepts_response_and_structured_output() -> None:
    plain = agy_runner.read_envelope(agy_run(envelope_line()), PLAIN_JOB)
    structured = agy_runner.read_envelope(
        agy_run(envelope_line(response="", structured_output={"a": 1})),
        SCHEMA_JOB,
    )

    assert plain.response == "ok"
    assert structured.structured_output == {"a": 1}


@pytest.mark.parametrize(
    "error",
    [
        "RESOURCE_EXHAUSTED: quota exceeded",
        "429 Too Many Requests",
        "You have hit the usage limit for this model",
        "rate limit reached",
    ],
)
def test_quota_text_reports_quota_of_model(error: str) -> None:
    stdout = envelope_line(status="ERROR", error=error)

    with pytest.raises(AgyUnavailableError) as raised:
        agy_runner.read_envelope(agy_run(stdout), PLAIN_JOB)

    assert "quota of model gemini-4-argon-high looks exhausted" in (
        raised.value.reason
    )


def test_non_quota_error_is_not_reported_as_quota() -> None:
    stdout = envelope_line(status="ERROR", error="unknown model foo")

    with pytest.raises(AgyUnavailableError) as raised:
        agy_runner.read_envelope(agy_run(stdout), PLAIN_JOB)

    assert "quota" not in raised.value.reason


def test_strip_workspace_paths_makes_links_repo_relative_unit() -> None:
    workspace = Path("/home/u/.cache/agy-worker/work/agy-x1/wt")
    text = (
        "see file:///home/u/.cache/agy-worker/work/agy-x1/wt/a/b.py#L14, "
        "/home/u/.cache/agy-worker/work/agy-x1/wt/c.py:3 and /etc/hosts"
    )

    assert agy_runner.strip_workspace_paths(text, workspace) == (
        "see a/b.py#L14, c.py:3 and /etc/hosts"
    )


def test_plan_review_findings_use_repo_relative_paths(
    fake_agy: FakeAgy,
    allowlisted_repo: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    use_mode(monkeypatch, "cwd")

    result = plan_review(allowlisted_repo)

    assert result == (
        "Gemini review completed "
        f"(mode=plan, model={FLASH_LOW_MODEL}, workspace=clean).\n\n"
        "Findings:\nsee ratelimit.py#L14 and auth.py:3"
    )
    assert list(fake_agy.work_dir.iterdir()) == []


def test_prompt_size_limit_counts_bytes_not_characters() -> None:
    agy_runner.check_prompt_size("x" * 100_000)
    agy_runner.check_prompt_size("é" * 50_000)
    with pytest.raises(AgyUnavailableError):
        agy_runner.check_prompt_size("é" * 50_001)


def test_guarded_maps_value_error_to_unavailable_unit() -> None:
    assert agy_worker.guarded(raise_value_error) == (
        "AGY-UNAVAILABLE: invalid argument: embedded null byte"
    )


def test_plan_review_prompt_opens_with_the_no_commands_rule(
    fake_agy: FakeAgy, allowlisted_repo: Path
) -> None:
    plan_review(allowlisted_repo)

    assert (
        fake_agy.invocation()
        .argv[1]
        .startswith(
            "You may read files in the working directory, "
            "but you must never run commands.\n\n"
        )
    )


def test_guarded_maps_runtime_error_to_unavailable_unit() -> None:
    assert agy_worker.guarded(raise_runtime_error) == (
        "AGY-UNAVAILABLE: invalid argument: "
        "Could not determine home directory."
    )


def test_unknown_user_home_in_project_path_unavailable(
    fake_agy: FakeAgy,
) -> None:
    result = agy_worker.agy_plan_review(
        what_changed=WHAT_CHANGED,
        review_focus="x",
        project_path="~no-such-user-4711/repo",
    )

    assert result.startswith("AGY-UNAVAILABLE: invalid argument: ")
    assert not fake_agy.ran()


def test_nul_in_project_path_unavailable(fake_agy: FakeAgy) -> None:
    result = agy_worker.agy_plan_review(
        what_changed=WHAT_CHANGED,
        review_focus="x",
        project_path="repo\0x",
    )

    assert result.startswith("AGY-UNAVAILABLE: ")
    assert not fake_agy.ran()


def test_auth_hang_killed_within_ten_seconds(
    fake_agy: FakeAgy,
    allowlisted_repo: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    use_mode(monkeypatch, "auth")
    started = time.monotonic()

    result = plan_review(allowlisted_repo)

    assert time.monotonic() - started < MAX_AUTH_SECONDS
    assert result.startswith("AGY-UNAVAILABLE: ")
    assert "not logged in" in result
    assert "run `agy` once interactively" in result
    assert list(fake_agy.work_dir.iterdir()) == []


def test_agy_models_not_logged_in_unavailable(
    fake_agy: FakeAgy, monkeypatch: pytest.MonkeyPatch
) -> None:
    use_mode(monkeypatch, "auth")
    started = time.monotonic()

    result = agy_worker.agy_models()

    assert time.monotonic() - started < MAX_AUTH_SECONDS
    assert result.startswith("AGY-UNAVAILABLE: ")
    assert "not logged in" in result
    assert fake_agy.ran()


def test_agy_models_lists_models(fake_agy: FakeAgy) -> None:
    result = agy_worker.agy_models()

    assert result == "gemini-4-argon-low\ngemini-3.8-flash-medium"
    assert fake_agy.invocation().argv == ["models"]


def test_success_with_empty_response_is_unavailable(
    fake_agy: FakeAgy,
    allowlisted_repo: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    use_mode(monkeypatch, "empty")

    result = plan_review(allowlisted_repo)

    assert result.startswith("AGY-UNAVAILABLE: ")
    assert "empty response" in result
    assert "a tool required the" in result
    assert fake_agy.ran()


def test_quota_error_reports_quota(
    fake_agy: FakeAgy,
    allowlisted_repo: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    use_mode(monkeypatch, "quota")

    result = plan_review(allowlisted_repo)

    assert result.startswith("AGY-UNAVAILABLE: ")
    assert "quota of model gemini-3.8-flash-low looks exhausted" in result
    assert fake_agy.ran()


def test_error_status_reports_status_and_error(
    fake_agy: FakeAgy,
    allowlisted_repo: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    use_mode(monkeypatch, "error")

    result = plan_review(allowlisted_repo, model="nope")

    assert result.startswith("AGY-UNAVAILABLE: ")
    assert "status ERROR: unknown model foo; available: a, b" in result
    assert "quota" not in result
    assert fake_agy.ran()


def test_non_json_stdout_unavailable(
    fake_agy: FakeAgy,
    allowlisted_repo: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    use_mode(monkeypatch, "nonjson")

    result = plan_review(allowlisted_repo)

    assert result.startswith("AGY-UNAVAILABLE: ")
    assert "no JSON envelope" in result
    assert "this is not json" in result
    assert fake_agy.ran()


def test_timeout_kills_process_group(
    fake_agy: FakeAgy,
    allowlisted_repo: Path,
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    pid_file = tmp_path / "grandchild.pid"
    use_mode(monkeypatch, "hang")
    monkeypatch.setenv("AGY_FAKE_PID_FILE", str(pid_file))
    monkeypatch.setattr(agy_worker, "PLAN_TIMEOUT_SECONDS", 2)
    monkeypatch.setattr(agy_runner, "KILL_GRACE_SECONDS", 0.5)

    result = plan_review(allowlisted_repo)

    assert result.startswith("AGY-UNAVAILABLE: ")
    assert "timed out after 2 s" in result
    grandchild = int(pid_file.read_text())
    assert wait_until(lambda: process_gone(grandchild))
    assert list(fake_agy.work_dir.iterdir()) == []


def test_second_caller_busy_while_lock_held(
    fake_agy: FakeAgy,
    allowlisted_repo: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setenv("AGY_MAX_PARALLEL", "1")
    monkeypatch.setattr(agy_runner, "LOCK_WAIT_SECONDS", 0.3)
    monkeypatch.setattr(agy_runner, "LOCK_POLL_SECONDS", 0.05)
    with fake_agy.lock_path.open("a") as holder:
        fcntl.flock(holder, fcntl.LOCK_EX)

        result = plan_review(allowlisted_repo)

    assert result.startswith("AGY-UNAVAILABLE: ")
    assert "busy" in result
    assert not fake_agy.ran()
    assert list(fake_agy.work_dir.iterdir()) == []


def test_run_proceeds_while_slot_zero_held(
    fake_agy: FakeAgy,
    allowlisted_repo: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setenv("AGY_MAX_PARALLEL", "2")
    monkeypatch.setattr(agy_runner, "LOCK_WAIT_SECONDS", 0.3)
    monkeypatch.setattr(agy_runner, "LOCK_POLL_SECONDS", 0.05)
    with fake_agy.lock_path.open("a") as holder:
        fcntl.flock(holder, fcntl.LOCK_EX)

        result = plan_review(allowlisted_repo)

    assert result.startswith("Gemini review completed")
    assert fake_agy.ran()


def test_busy_when_every_slot_held(
    fake_agy: FakeAgy,
    allowlisted_repo: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setenv("AGY_MAX_PARALLEL", "2")
    monkeypatch.setattr(agy_runner, "LOCK_WAIT_SECONDS", 0.3)
    monkeypatch.setattr(agy_runner, "LOCK_POLL_SECONDS", 0.05)
    second_slot = fake_agy.lock_path.with_name(fake_agy.lock_path.name + ".1")
    with (
        fake_agy.lock_path.open("a") as first,
        second_slot.open("a") as second,
    ):
        fcntl.flock(first, fcntl.LOCK_EX)
        fcntl.flock(second, fcntl.LOCK_EX)

        result = plan_review(allowlisted_repo)

    assert result.startswith("AGY-UNAVAILABLE: ")
    assert "busy" in result
    assert not fake_agy.ran()


@pytest.mark.parametrize("value", ["abc", "0", "-1"])
def test_invalid_max_parallel_falls_back_to_default(
    monkeypatch: pytest.MonkeyPatch, value: str
) -> None:
    monkeypatch.setenv("AGY_MAX_PARALLEL", value)

    assert agy_runner.max_parallel() == 3


def test_unset_max_parallel_is_default(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.delenv("AGY_MAX_PARALLEL", raising=False)

    assert agy_runner.max_parallel() == 3


def test_valid_max_parallel_is_used(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("AGY_MAX_PARALLEL", "5")

    assert agy_runner.max_parallel() == 5


def test_lock_slot_paths_unit(tmp_path: Path) -> None:
    base = tmp_path / "agy.lock"

    assert agy_runner.lock_slot_paths(base, 3) == [
        base,
        tmp_path / "agy.lock.1",
        tmp_path / "agy.lock.2",
    ]


def test_slot_released_after_failed_run(
    fake_agy: FakeAgy,
    allowlisted_repo: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setenv("AGY_MAX_PARALLEL", "1")
    use_mode(monkeypatch, "error")

    result = plan_review(allowlisted_repo)

    assert result.startswith("AGY-UNAVAILABLE: ")
    assert fake_agy.ran()
    with fake_agy.lock_path.open("a") as probe:
        fcntl.flock(probe, fcntl.LOCK_EX | fcntl.LOCK_NB)


def test_lock_is_released_after_a_run(
    fake_agy: FakeAgy, allowlisted_repo: Path
) -> None:
    first = plan_review(allowlisted_repo)
    second = plan_review(allowlisted_repo)

    assert first.startswith("Gemini review completed")
    assert second.startswith("Gemini review completed")
    assert fake_agy.ran()


def test_prompt_too_large_refused(
    fake_agy: FakeAgy, allowlisted_repo: Path
) -> None:
    result = agy_worker.agy_plan_review(
        what_changed="x" * 100_001,
        review_focus="x",
        project_path=str(allowlisted_repo),
    )

    assert result.startswith("AGY-UNAVAILABLE: ")
    assert "byte limit" in result
    assert not fake_agy.ran()


def test_agy_missing_unavailable(
    fake_agy: FakeAgy,
    allowlisted_repo: Path,
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setenv("AGY_BIN", str(tmp_path / "no-such-agy"))

    result = plan_review(allowlisted_repo)

    assert result.startswith("AGY-UNAVAILABLE: agy executable not found")
    assert "no-such-agy" in result
    assert not fake_agy.ran()


def test_stdin_is_devnull(fake_agy: FakeAgy, allowlisted_repo: Path) -> None:
    plan_review(allowlisted_repo)

    assert fake_agy.invocation().stdin_is_devnull is True


def test_agy_receives_json_sandbox_arguments_inside_bwrap(
    fake_agy: FakeAgy, allowlisted_repo: Path
) -> None:
    plan_review(allowlisted_repo)

    invocation = fake_agy.invocation()
    argv = invocation.argv
    assert argv[0] == "-p"
    assert WHAT_CHANGED in argv[1]
    assert argv[2:] == [
        "--output-format",
        "json",
        "--model",
        FLASH_LOW_MODEL,
        "--sandbox",
        "--dangerously-skip-permissions",
        "--print-timeout",
        "1740s",
    ]
    assert Path(invocation.cwd).parent.parent == fake_agy.work_dir
    sandbox_flags = fake_agy.bwrap_flags()
    assert "--unshare-pid" in sandbox_flags
    assert "--die-with-parent" in sandbox_flags
    assert invocation.cwd in sandbox_flags
