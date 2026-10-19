import json
import threading
import uuid
from pathlib import Path

import agy_runner
import agy_worker
import pytest
from agy_errors import AgyUnavailableError
from helpers_test import (
    FAKE_DBUS_ADDRESS,
    FAKE_RUNTIME_DIR,
    REAL_BWRAP,
    REAL_DBUS_ADDRESS,
    REAL_DBUS_PROXY,
    REAL_RUNTIME_DIR,
    FakeAgy,
    pids_with_marker,
    plan_review,
    process_gone,
    wait_until,
)

PROXY_TARGET = f"{FAKE_RUNTIME_DIR}/bus"
SECRETS_FILTER = "--talk=org.freedesktop.secrets"


def bind_triples(command: list[str]) -> list[tuple[str, str, str]]:
    return [
        (flag, command[index + 1], command[index + 2])
        for index, flag in enumerate(command)
        if flag.startswith(("--ro-bind", "--bind"))
    ]


def test_sandbox_command_binds_proxy_socket_never_the_real_bus(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setenv("XDG_RUNTIME_DIR", FAKE_RUNTIME_DIR)
    binding = agy_runner.BusBinding(Path("/work/proxy/bus"), PROXY_TARGET)

    command = agy_runner.sandbox_command(
        Path("/work/ws"),
        "/usr/bin/agy",
        ["models"],
        binding,
        Path("/work/private/.gemini"),
    )

    triples = bind_triples(command)
    assert ("--ro-bind", "/work/proxy/bus", PROXY_TARGET) in triples
    assert [t for t in triples if t[1] == PROXY_TARGET] == []
    address = f"unix:path={PROXY_TARGET}"
    setenv = ["--setenv", "DBUS_SESSION_BUS_ADDRESS", address]
    assert any(command[i : i + 3] == setenv for i in range(len(command)))


def test_sandbox_command_binds_scratch_dir_at_gemini_unit() -> None:
    binding = agy_runner.BusBinding(Path("/work/proxy/bus"), PROXY_TARGET)
    scratch = Path("/work/private/.gemini")

    command = agy_runner.sandbox_command(
        Path("/work/ws"), "/usr/bin/agy", ["models"], binding, scratch
    )

    triples = bind_triples(command)
    host_gemini = str(Path.home() / ".gemini")
    assert ("--bind", str(scratch), host_gemini) in triples
    assert [t for t in triples if t[1] == host_gemini] == []
    assert [t for t in triples if t[2] == host_gemini] == [
        ("--bind", str(scratch), host_gemini)
    ]


def sandbox_environment(command: list[str]) -> dict[str, str]:
    return {
        command[index + 1]: command[index + 2]
        for index, flag in enumerate(command)
        if flag == "--setenv"
    }


@pytest.mark.parametrize(
    ("host_lang", "expected_lang"),
    [
        ("pl_PL.UTF-8", "pl_PL.UTF-8"),
        ("C.UTF-8", "C.UTF-8"),
        ("en_US", "en_US"),
        ("x; rm -rf /", "C.UTF-8"),
        ("", "C.UTF-8"),
        (None, "C.UTF-8"),
    ],
)
def test_sandbox_command_clears_environment_and_sets_only_allowed_unit(
    host_lang: str | None,
    expected_lang: str,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    if host_lang is None:
        monkeypatch.delenv("LANG", raising=False)
    else:
        monkeypatch.setenv("LANG", host_lang)
    binding = agy_runner.BusBinding(Path("/work/proxy/bus"), PROXY_TARGET)

    command = agy_runner.sandbox_command(
        Path("/work/ws"),
        "/usr/bin/agy",
        ["models"],
        binding,
        Path("/work/private/.gemini"),
    )

    assert "--clearenv" in command
    assert command.index("--clearenv") < command.index("--setenv")
    assert sandbox_environment(command) == {
        "HOME": str(Path.home()),
        "PATH": "/usr/bin:/bin",
        "LANG": expected_lang,
        "DBUS_SESSION_BUS_ADDRESS": f"unix:path={PROXY_TARGET}",
    }


def test_sandbox_environment_has_no_host_secrets(
    fake_agy: FakeAgy,
    allowlisted_repo: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setenv("FAKE_SECRET_TOKEN", "s3cret")
    monkeypatch.setenv("AGY_FAKE_MODE", "env")
    monkeypatch.setenv("AGY_BWRAP", REAL_BWRAP)

    result = plan_review(allowlisted_repo)

    names = json.loads(result.split("Findings:\n")[1])
    assert "FAKE_SECRET_TOKEN" not in names
    assert set(names) - {"PWD"} == {
        "HOME",
        "PATH",
        "LANG",
        "DBUS_SESSION_BUS_ADDRESS",
    }
    assert list(fake_agy.work_dir.iterdir()) == []


def test_sandbox_cannot_see_or_modify_host_gemini_dir(
    fake_agy: FakeAgy,
    allowlisted_repo: Path,
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    home = tmp_path / "home"
    host_gemini = home / ".gemini"
    (host_gemini / "antigravity-cli").mkdir(parents=True)
    marker = host_gemini / "marker.txt"
    marker.write_text("host-secret")
    settings = host_gemini / "antigravity-cli" / "settings.json"
    settings.write_text("{}")
    monkeypatch.setenv("HOME", str(home))
    monkeypatch.setenv("AGY_FAKE_MODE", "gemini")
    monkeypatch.setenv("AGY_BWRAP", REAL_BWRAP)

    result = plan_review(allowlisted_repo)

    assert result.endswith("Findings:\nlisting=[] write=OK")
    assert marker.read_text() == "host-secret"
    assert settings.read_text() == "{}"
    assert sorted(path.name for path in host_gemini.iterdir()) == [
        "antigravity-cli",
        "marker.txt",
    ]
    assert list(fake_agy.work_dir.iterdir()) == []


def test_dbus_proxy_runs_filtered_and_is_terminated_unit(
    fake_agy: FakeAgy,
) -> None:
    with agy_runner.dbus_proxy() as binding:
        assert wait_until(fake_agy.proxy_record.exists)
        assert wait_until(binding.socket.exists)
        pid = fake_agy.proxy_pid()
        assert fake_agy.proxy_args() == [
            FAKE_DBUS_ADDRESS,
            str(binding.socket),
            "--filter",
            SECRETS_FILTER,
        ]
        assert binding.target == PROXY_TARGET
        assert binding.socket.parent.parent == fake_agy.work_dir

    assert wait_until(lambda: process_gone(pid))
    assert not binding.socket.parent.exists()


def test_dbus_proxy_missing_binary_is_sandbox_unavailable_unit(
    fake_agy: FakeAgy, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setenv("AGY_DBUS_PROXY", str(tmp_path / "no-such-proxy"))

    with (
        pytest.raises(AgyUnavailableError, match="sandbox unavailable"),
        agy_runner.dbus_proxy(),
    ):
        pass

    assert list(fake_agy.work_dir.iterdir()) == []


@pytest.mark.parametrize(
    "missing", ["DBUS_SESSION_BUS_ADDRESS", "XDG_RUNTIME_DIR"]
)
@pytest.mark.usefixtures("fake_agy")
def test_dbus_proxy_unset_environment_is_sandbox_unavailable_unit(
    missing: str, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.delenv(missing)

    with (
        pytest.raises(
            AgyUnavailableError, match=f"sandbox unavailable.*{missing}"
        ),
        agy_runner.dbus_proxy(),
    ):
        pass


def test_dbus_proxy_socket_timeout_is_sandbox_unavailable_unit(
    fake_agy: FakeAgy, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setenv("AGY_FAKE_PROXY_MODE", "silent")
    monkeypatch.setattr(agy_runner, "PROXY_STARTUP_SECONDS", 1.0)
    monkeypatch.setattr(agy_runner, "PROXY_POLL_SECONDS", 0.05)
    monkeypatch.setattr(agy_runner, "KILL_GRACE_SECONDS", 0.5)

    with (
        pytest.raises(AgyUnavailableError, match="did not create its socket"),
        agy_runner.dbus_proxy(),
    ):
        pass

    assert wait_until(lambda: process_gone(fake_agy.proxy_pid()))


def test_dbus_proxy_early_exit_is_sandbox_unavailable_unit(
    fake_agy: FakeAgy, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setenv("AGY_FAKE_PROXY_MODE", "exit")

    with (
        pytest.raises(AgyUnavailableError, match="D-Bus proxy exited"),
        agy_runner.dbus_proxy(),
    ):
        pass

    assert list(fake_agy.work_dir.iterdir()) == []


def test_missing_proxy_binary_blocks_the_tool_without_running_agy(
    fake_agy: FakeAgy,
    allowlisted_repo: Path,
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setenv("AGY_DBUS_PROXY", str(tmp_path / "no-such-proxy"))

    result = plan_review(allowlisted_repo)

    assert result.startswith("AGY-UNAVAILABLE: sandbox unavailable")
    assert "no-such-proxy" in result
    assert not fake_agy.ran()
    assert list(fake_agy.work_dir.iterdir()) == []


@pytest.mark.parametrize(
    "missing", ["DBUS_SESSION_BUS_ADDRESS", "XDG_RUNTIME_DIR"]
)
def test_unset_bus_environment_blocks_the_tool_without_running_agy(
    missing: str,
    fake_agy: FakeAgy,
    allowlisted_repo: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.delenv(missing)

    result = plan_review(allowlisted_repo)

    assert result.startswith("AGY-UNAVAILABLE: sandbox unavailable")
    assert missing in result
    assert not fake_agy.ran()


def test_proxy_socket_timeout_blocks_the_tool_without_running_agy(
    fake_agy: FakeAgy,
    allowlisted_repo: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setenv("AGY_FAKE_PROXY_MODE", "silent")
    monkeypatch.setattr(agy_runner, "PROXY_STARTUP_SECONDS", 1.0)
    monkeypatch.setattr(agy_runner, "PROXY_POLL_SECONDS", 0.05)
    monkeypatch.setattr(agy_runner, "KILL_GRACE_SECONDS", 0.5)

    result = plan_review(allowlisted_repo)

    assert result.startswith("AGY-UNAVAILABLE: sandbox unavailable")
    assert "did not create its socket" in result
    assert not fake_agy.ran()
    assert list(fake_agy.work_dir.iterdir()) == []


def test_agy_sees_only_the_proxy_bus_address(
    fake_agy: FakeAgy, allowlisted_repo: Path
) -> None:
    plan_review(allowlisted_repo)

    assert fake_agy.invocation().dbus_address == f"unix:path={PROXY_TARGET}"
    triples = bind_triples(fake_agy.bwrap_flags())
    assert [t[0] for t in triples if t[2] == PROXY_TARGET] == ["--ro-bind"]
    assert [t for t in triples if t[1] == PROXY_TARGET] == []


@pytest.mark.parametrize("mode", ["ok", "error", "nonjson", "hang", "auth"])
def test_proxy_terminated_on_every_path(
    mode: str,
    fake_agy: FakeAgy,
    allowlisted_repo: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setenv("AGY_FAKE_MODE", mode)
    monkeypatch.setenv("AGY_FAKE_PID_FILE", str(fake_agy.work_dir / "ignored"))
    monkeypatch.setattr(agy_worker, "PLAN_TIMEOUT_SECONDS", 2)
    monkeypatch.setattr(agy_runner, "KILL_GRACE_SECONDS", 0.5)

    plan_review(allowlisted_repo)

    assert fake_agy.proxy_pid_file.exists()
    assert wait_until(lambda: process_gone(fake_agy.proxy_pid()))


def test_sandbox_cannot_reach_systemd_user_bus(
    fake_agy: FakeAgy,
    allowlisted_repo: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setenv("AGY_FAKE_MODE", "systemd")
    monkeypatch.setenv("AGY_BWRAP", REAL_BWRAP)
    monkeypatch.setenv("AGY_DBUS_PROXY", REAL_DBUS_PROXY)
    monkeypatch.setenv("XDG_RUNTIME_DIR", REAL_RUNTIME_DIR)
    monkeypatch.setenv("DBUS_SESSION_BUS_ADDRESS", REAL_DBUS_ADDRESS)

    result = plan_review(allowlisted_repo)

    assert result.endswith("Findings:\nsystemd=CANNOT")
    assert list(fake_agy.work_dir.iterdir()) == []


def test_bwrap_missing_unavailable(
    fake_agy: FakeAgy,
    allowlisted_repo: Path,
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setenv("AGY_BWRAP", str(tmp_path / "no-such-bwrap"))

    result = plan_review(allowlisted_repo)

    assert result.startswith("AGY-UNAVAILABLE: sandbox unavailable")
    assert "no-such-bwrap" in result
    assert not fake_agy.ran()
    assert list(fake_agy.work_dir.iterdir()) == []


def test_bwrap_start_failure_reports_sandbox_unavailable(
    fake_agy: FakeAgy,
    allowlisted_repo: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setenv("AGY_FAKE_BWRAP_FAIL", "1")

    result = plan_review(allowlisted_repo)

    assert result.startswith("AGY-UNAVAILABLE: sandbox unavailable")
    assert "Permission denied" in result
    assert not fake_agy.ran()


@pytest.mark.usefixtures("fake_agy")
def test_isolation_cannot_read_or_write_outside_workspace(
    allowlisted_repo: Path,
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    outside = tmp_path / "outside"
    outside.mkdir()
    secret = outside / "secret.txt"
    secret.write_text("token-4711")
    target = outside / "written.txt"
    monkeypatch.setenv("AGY_FAKE_MODE", "isolation")
    monkeypatch.setenv("AGY_BWRAP", REAL_BWRAP)
    monkeypatch.setenv("AGY_FAKE_READ_PATH", str(secret))
    monkeypatch.setenv("AGY_FAKE_WRITE_PATH", str(target))

    result = plan_review(allowlisted_repo)

    assert result.endswith("Findings:\nread=CANNOT write=CANNOT")
    assert not target.exists()
    assert secret.read_text() == "token-4711"


def test_timeout_kills_process_group_real_bwrap(
    fake_agy: FakeAgy,
    allowlisted_repo: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    marker = f"agy-hang-{uuid.uuid4().hex}"
    monkeypatch.setenv("AGY_FAKE_MODE", "hang")
    monkeypatch.setenv("AGY_FAKE_HANG_MARKER", marker)
    monkeypatch.setenv("AGY_FAKE_PID_FILE", str(fake_agy.work_dir / "ignored"))
    monkeypatch.setenv("AGY_BWRAP", REAL_BWRAP)
    monkeypatch.setattr(agy_worker, "PLAN_TIMEOUT_SECONDS", 3)
    monkeypatch.setattr(agy_runner, "KILL_GRACE_SECONDS", 0.5)
    results: list[str] = []
    review = threading.Thread(
        target=lambda: results.append(plan_review(allowlisted_repo))
    )

    review.start()
    started = wait_until(lambda: bool(pids_with_marker(marker)), seconds=15)
    review.join(timeout=60)

    assert started
    assert "timed out after 3 s" in results[0]
    assert wait_until(lambda: not pids_with_marker(marker))


@pytest.mark.parametrize(
    "address",
    [
        "unix:path=/run/user/1000/bus",
        "unix:path=/run/user/1000/bus,guid=0123abcd",
    ],
)
def test_bus_address_with_a_single_unix_path_is_accepted_unit(
    address: str,
) -> None:
    agy_runner.check_bus_address(address)


@pytest.mark.parametrize(
    "address",
    [
        "unix:abstract=/tmp/dbus-abc",
        "unix:abstract=/tmp/dbus-abc,guid=0123abcd",
        "tcp:host=localhost,port=1234",
        "unix:path=/run/user/1000/bus;unix:abstract=/tmp/dbus-abc",
        "unix:path=/run/user/1000/bus;unix:path=/run/user/1000/other",
        "unix:path=relative/bus",
        "unix:path=/run/user/1000/bus,abstract=/tmp/dbus-abc",
        "",
    ],
)
def test_bus_address_other_than_unix_path_is_refused_unit(
    address: str,
) -> None:
    with pytest.raises(
        AgyUnavailableError,
        match=r"sandbox unavailable: session bus address .* is not a",
    ):
        agy_runner.check_bus_address(address)


def test_abstract_bus_address_blocks_the_tool_without_running_agy(
    fake_agy: FakeAgy,
    allowlisted_repo: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setenv("DBUS_SESSION_BUS_ADDRESS", "unix:abstract=/tmp/dbus-x")

    result = plan_review(allowlisted_repo)

    assert result.startswith(
        "AGY-UNAVAILABLE: sandbox unavailable: session bus address "
        "unix:abstract=/tmp/dbus-x is not a unix:path socket; refusing "
        "(abstract sockets are reachable from the sandbox)"
    )
    assert not fake_agy.ran()
    assert not fake_agy.proxy_pid_file.exists()
    assert list(fake_agy.work_dir.iterdir()) == []
