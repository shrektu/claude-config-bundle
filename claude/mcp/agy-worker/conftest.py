from pathlib import Path

import pytest
from helpers_test import (
    EXECUTABLE_MODE,
    FAKE_AGY_SOURCE,
    FAKE_BWRAP_SOURCE,
    FAKE_DBUS_ADDRESS,
    FAKE_PROXY_SOURCE,
    FAKE_RUNTIME_DIR,
    FOREIGN_URL,
    ORIGIN_URL,
    FakeAgy,
    make_repo,
)


@pytest.fixture(autouse=True)
def clear_machine_mode(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.delenv("CLAUDE_MODE", raising=False)


def write_executable(path: Path, source: str) -> Path:
    path.write_text(source)
    path.chmod(EXECUTABLE_MODE)
    return path


@pytest.fixture
def fake_agy(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> FakeAgy:
    bin_dir = tmp_path / "bin"
    bin_dir.mkdir()
    agy = write_executable(bin_dir / "agy", FAKE_AGY_SOURCE)
    bwrap = write_executable(bin_dir / "bwrap", FAKE_BWRAP_SOURCE)
    proxy = write_executable(bin_dir / "xdg-dbus-proxy", FAKE_PROXY_SOURCE)
    work_dir = tmp_path / "work"
    work_dir.mkdir()
    fake = FakeAgy(
        record=tmp_path / "agy-record.json",
        work_dir=work_dir,
        lock_path=tmp_path / "agy.lock",
        proxy_pid_file=tmp_path / "proxy.pid",
        proxy_record=tmp_path / "proxy-record.json",
        bwrap_record=tmp_path / "bwrap.txt",
    )
    monkeypatch.setenv("AGY_BIN", str(agy))
    monkeypatch.setenv("AGY_BWRAP", str(bwrap))
    monkeypatch.setenv("AGY_DBUS_PROXY", str(proxy))
    monkeypatch.setenv("AGY_WORK_DIR", str(work_dir))
    monkeypatch.setenv("AGY_LOCK_PATH", str(fake.lock_path))
    monkeypatch.setenv("AGY_FAKE_RECORD", str(fake.record))
    monkeypatch.setenv("AGY_FAKE_BWRAP_RECORD", str(fake.bwrap_record))
    monkeypatch.setenv("AGY_FAKE_PROXY_PID_FILE", str(fake.proxy_pid_file))
    monkeypatch.setenv("AGY_FAKE_PROXY_RECORD", str(fake.proxy_record))
    monkeypatch.setenv("XDG_RUNTIME_DIR", FAKE_RUNTIME_DIR)
    monkeypatch.setenv("DBUS_SESSION_BUS_ADDRESS", FAKE_DBUS_ADDRESS)
    monkeypatch.setenv("AGY_STYLE_GUIDE", str(tmp_path / "no-guide.md"))
    monkeypatch.delenv("AGY_ALLOWLIST", raising=False)
    return fake


@pytest.fixture
def allowlisted_repo(tmp_path: Path) -> Path:
    return make_repo(tmp_path / "repo", ORIGIN_URL)


@pytest.fixture
def foreign_repo(tmp_path: Path) -> Path:
    return make_repo(tmp_path / "foreign", FOREIGN_URL)
