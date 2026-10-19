import contextlib
import fcntl
import os
import re
import shutil
import signal
import subprocess
import threading
import time
from collections.abc import Callable, Iterator, Sequence
from contextlib import AbstractContextManager
from enum import StrEnum
from pathlib import Path
from typing import IO, NamedTuple

from agy_errors import fail
from agy_workspace import (
    DECODE_ERRORS,
    TEXT_ENCODING,
    Workspace,
    dirty_paths,
    path_from_env,
    scratch_dir,
)
from pydantic import BaseModel, JsonValue, ValidationError

AGY_BIN_ENV = "AGY_BIN"
DEFAULT_AGY_BIN = "agy"
BWRAP_ENV = "AGY_BWRAP"
DEFAULT_BWRAP = "/usr/bin/bwrap"
LOCK_PATH_ENV = "AGY_LOCK_PATH"
DEFAULT_LOCK_PARTS = (".cache", "agy-worker", "agy.lock")
RUNTIME_DIR_ENV = "XDG_RUNTIME_DIR"
GEMINI_DIR = ".gemini"
AUTH_MARKER = "Authentication required"
BWRAP_ERROR_MARKER = "bwrap:"
NOT_LOGGED_IN = (
    "agy is not logged in; run `agy` once interactively to sign in, then retry"
)
PRINT_TIMEOUT_MARGIN_SECONDS = 60
MIN_PRINT_TIMEOUT_SECONDS = 1
LOCK_WAIT_SECONDS = 900.0
LOCK_POLL_SECONDS = 1.0
KILL_GRACE_SECONDS = 10.0
POLL_SECONDS = 0.1
PIPE_JOIN_SECONDS = 5.0
MAX_PROMPT_BYTES = 100_000
STDERR_TAIL_CHARS = 500
PROXY_POLL_SECONDS = 0.05
PROXY_STARTUP_SECONDS = 5.0
DBUS_PROXY_ENV = "AGY_DBUS_PROXY"
DEFAULT_DBUS_PROXY = "/usr/bin/xdg-dbus-proxy"
DBUS_ADDRESS_ENV = "DBUS_SESSION_BUS_ADDRESS"
SECRETS_TALK = "--talk=org.freedesktop.secrets"
BUS_NAME = "bus"
HOME_ENV = "HOME"
PATH_ENV = "PATH"
LANG_ENV = "LANG"
SANDBOX_PATH = "/usr/bin:/bin"
DEFAULT_LANG = "C.UTF-8"
LANG_PATTERN = re.compile(r"[A-Za-z]{2,3}(_[A-Za-z]{2})?(\.[A-Za-z0-9-]+)?")
SANDBOX_ENV_NAMES = (HOME_ENV, PATH_ENV, LANG_ENV, DBUS_ADDRESS_ENV)
BUS_PATH_PATTERN = re.compile(r"unix:path=/[^,;\s]*(,guid=[0-9A-Fa-f]+)?")
MODEL_PATTERN = re.compile(r"[A-Za-z0-9][A-Za-z0-9._-]*")
QUOTA_PATTERN = re.compile(
    r"quota|rate.?limit|RESOURCE_EXHAUSTED|\b429\b|exhausted|usage limit",
    re.IGNORECASE,
)
BWRAP_RO_DIRS = ("/usr", "/etc")
BWRAP_USR_LINKS = {
    "/bin": "usr/bin",
    "/lib": "usr/lib",
    "/lib64": "usr/lib64",
    "/sbin": "usr/sbin",
}
BWRAP_TMPFS_NAMES = ("tmp", "home", "run")
BWRAP_RESOLVE_DIR = "/run/systemd/resolve"
BWRAP_TAIL = ("--die-with-parent", "--unshare-pid", "--unshare-ipc")


class AgyStatus(StrEnum):
    """Final status values of an agy JSON envelope."""

    SUCCESS = "SUCCESS"


class Envelope(BaseModel):
    """The JSON object agy prints in headless mode."""

    status: str
    response: str | None = None
    error: str | None = None
    structured_output: JsonValue = None


class AgyJob(NamedTuple):
    """One agy invocation."""

    prompt: str
    model: str
    timeout_seconds: int
    schema: str | None


class AgyRun(NamedTuple):
    """Raw result of an agy process."""

    stdout: str
    stderr: str
    returncode: int | None
    timed_out: bool = False


def check_model(model: str) -> None:
    """Reject model names that are not plain slugs."""
    if not MODEL_PATTERN.fullmatch(model):
        fail(f"invalid model name {model!r}")


def check_prompt_size(prompt: str) -> None:
    """Refuse prompts that do not fit on a command line."""
    size = len(prompt.encode(TEXT_ENCODING))
    if size > MAX_PROMPT_BYTES:
        fail(f"prompt is {size} bytes, over the {MAX_PROMPT_BYTES} byte limit")


def agy_executable() -> str:
    """Return the real path of the agy binary."""
    binary = os.environ.get(AGY_BIN_ENV, DEFAULT_AGY_BIN)
    found = shutil.which(binary)
    if found is None:
        fail(f"agy executable not found: {binary}")
    return os.path.realpath(found)


class BusBinding(NamedTuple):
    """A filtered session bus socket and where the sandbox sees it."""

    socket: Path
    target: str


def check_bus_address(address: str) -> None:
    """Refuse session bus addresses other than a single unix:path."""
    if not BUS_PATH_PATTERN.fullmatch(address):
        fail(
            f"sandbox unavailable: session bus address {address} is not a "
            "unix:path socket; refusing (abstract sockets are reachable "
            "from the sandbox)"
        )


def start_proxy(address: str, socket_path: Path) -> "subprocess.Popen[str]":
    """Start xdg-dbus-proxy so that only the secrets service is reachable."""
    proxy = os.environ.get(DBUS_PROXY_ENV, DEFAULT_DBUS_PROXY)
    command = [proxy, address, str(socket_path), "--filter", SECRETS_TALK]
    try:
        return subprocess.Popen(
            command,
            stdin=subprocess.DEVNULL,
            stdout=subprocess.DEVNULL,
            stderr=subprocess.DEVNULL,
            start_new_session=True,
            text=True,
        )
    except OSError as error:
        fail(f"sandbox unavailable: cannot start D-Bus proxy {proxy}: {error}")


def wait_for_socket(
    process: "subprocess.Popen[str]", socket_path: Path
) -> None:
    """Wait until the proxy has created its socket."""
    deadline = time.monotonic() + PROXY_STARTUP_SECONDS
    while not socket_path.exists():
        if process.poll() is not None:
            fail(
                "sandbox unavailable: D-Bus proxy exited with code "
                f"{process.returncode}"
            )
        if time.monotonic() >= deadline:
            fail(
                "sandbox unavailable: D-Bus proxy did not create its socket "
                f"within {PROXY_STARTUP_SECONDS:g} s"
            )
        time.sleep(PROXY_POLL_SECONDS)


@contextlib.contextmanager
def dbus_proxy() -> Iterator[BusBinding]:
    """Provide the filtered session bus for one sandboxed run."""
    address = os.environ.get(DBUS_ADDRESS_ENV)
    runtime_dir = os.environ.get(RUNTIME_DIR_ENV)
    if not address:
        fail(f"sandbox unavailable: {DBUS_ADDRESS_ENV} is not set")
    if not runtime_dir:
        fail(f"sandbox unavailable: {RUNTIME_DIR_ENV} is not set")
    check_bus_address(address)
    with scratch_dir() as scratch:
        socket_path = scratch / BUS_NAME
        process = start_proxy(address, socket_path)
        try:
            wait_for_socket(process, socket_path)
            yield BusBinding(socket_path, str(Path(runtime_dir) / BUS_NAME))
        finally:
            terminate_group(process)


def sandbox_lang() -> str:
    """Return the host locale when it is a plain locale name."""
    host = os.environ.get(LANG_ENV, "")
    return host if LANG_PATTERN.fullmatch(host) else DEFAULT_LANG


def sandbox_command(
    workspace: Path,
    agy_path: str,
    arguments: Sequence[str],
    bus: BusBinding,
    gemini_dir: Path,
) -> list[str]:
    """Wrap an agy command line in the bubblewrap sandbox."""
    home = str(Path.home())
    gemini = str(Path.home() / GEMINI_DIR)
    command = [os.environ.get(BWRAP_ENV, DEFAULT_BWRAP), "--clearenv"]
    for directory in BWRAP_RO_DIRS:
        command += ["--ro-bind", directory, directory]
    for link, target in BWRAP_USR_LINKS.items():
        command += ["--symlink", target, link]
    command += ["--proc", "/proc", "--dev", "/dev"]
    for name in BWRAP_TMPFS_NAMES:
        command += ["--tmpfs", str(Path("/", name))]
    command += ["--ro-bind", str(bus.socket), bus.target]
    command += ["--ro-bind-try", BWRAP_RESOLVE_DIR, BWRAP_RESOLVE_DIR]
    command += ["--bind", str(gemini_dir), gemini]
    command += ["--ro-bind", agy_path, agy_path]
    command += ["--bind", str(workspace), str(workspace)]
    command += ["--chdir", str(workspace), *BWRAP_TAIL]
    environment = {
        HOME_ENV: home,
        PATH_ENV: SANDBOX_PATH,
        LANG_ENV: sandbox_lang(),
        DBUS_ADDRESS_ENV: f"unix:path={bus.target}",
    }
    for name in SANDBOX_ENV_NAMES:
        command += ["--setenv", name, environment[name]]
    command += ["--", agy_path, *arguments]
    return command


def agy_arguments(job: AgyJob) -> list[str]:
    """Build the agy command line arguments for a job."""
    print_timeout = max(
        job.timeout_seconds - PRINT_TIMEOUT_MARGIN_SECONDS,
        MIN_PRINT_TIMEOUT_SECONDS,
    )
    arguments = [
        "-p",
        job.prompt,
        "--output-format",
        "json",
        "--model",
        job.model,
        "--sandbox",
        "--print-timeout",
        f"{print_timeout}s",
    ]
    if job.schema is not None:
        arguments += ["--json-schema", job.schema]
    return arguments


def pump(
    stream: IO[str] | None,
    sink: list[str],
    marker_found: threading.Event | None,
) -> None:
    """Copy lines of a pipe into a list until it closes."""
    for line in stream or ():
        sink.append(line)
        if marker_found is not None and AUTH_MARKER in line:
            marker_found.set()


def signal_group(process: subprocess.Popen[str], signum: int) -> None:
    """Send a signal to the whole process group of a child."""
    with contextlib.suppress(ProcessLookupError, PermissionError):
        os.killpg(process.pid, signum)


def terminate_group(process: subprocess.Popen[str]) -> None:
    """Stop a child and everything it started."""
    signal_group(process, signal.SIGTERM)
    with contextlib.suppress(subprocess.TimeoutExpired):
        process.wait(KILL_GRACE_SECONDS)
    signal_group(process, signal.SIGKILL)
    process.wait()


def wait_for_exit(
    process: subprocess.Popen[str],
    auth_seen: threading.Event,
    timeout_seconds: float,
) -> bool:
    """Wait for exit, a login prompt or the deadline; True on timeout."""
    deadline = time.monotonic() + timeout_seconds
    while process.poll() is None:
        if auth_seen.wait(POLL_SECONDS):
            return False
        if time.monotonic() >= deadline:
            return True
    return False


def run_command(
    command: Sequence[str], cwd: Path, timeout_seconds: float
) -> AgyRun:
    """Run a command in its own process group and collect its output."""
    try:
        process = subprocess.Popen(
            command,
            cwd=cwd,
            stdin=subprocess.DEVNULL,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            start_new_session=True,
            text=True,
            encoding=TEXT_ENCODING,
            errors=DECODE_ERRORS,
        )
    except OSError as error:
        fail(f"sandbox unavailable: cannot start {command[0]}: {error}")
    auth_seen = threading.Event()
    out_lines: list[str] = []
    err_lines: list[str] = []
    readers = [
        threading.Thread(
            target=pump, args=(process.stdout, out_lines, None), daemon=True
        ),
        threading.Thread(
            target=pump,
            args=(process.stderr, err_lines, auth_seen),
            daemon=True,
        ),
    ]
    with process:
        for reader in readers:
            reader.start()
        try:
            timed_out = wait_for_exit(process, auth_seen, timeout_seconds)
        finally:
            terminate_group(process)
            for reader in readers:
                reader.join(PIPE_JOIN_SECONDS)
    return AgyRun(
        "".join(out_lines), "".join(err_lines), process.returncode, timed_out
    )


def run_agy(
    workspace: Path, arguments: Sequence[str], timeout_seconds: float
) -> AgyRun:
    """Run agy in the sandbox with stdin closed and collect its output."""
    with scratch_dir() as private, dbus_proxy() as bus:
        gemini_dir = private / GEMINI_DIR
        gemini_dir.mkdir()
        command = sandbox_command(
            workspace, agy_executable(), arguments, bus, gemini_dir
        )
        return run_command(command, workspace, timeout_seconds)


def parse_envelope(stdout: str) -> Envelope | None:
    """Return the last line of stdout that is a JSON envelope."""
    for line in reversed(stdout.splitlines()):
        candidate = line.strip()
        if not candidate.startswith("{"):
            continue
        try:
            return Envelope.model_validate_json(candidate)
        except ValidationError:
            continue
    return None


def stderr_tail(stderr: str) -> str:
    """Return the end of stderr for use in messages."""
    return stderr.strip()[-STDERR_TAIL_CHARS:]


def check_outcome(run: AgyRun, timeout_seconds: float) -> None:
    """Fail when agy needed a login, ran too long or never started."""
    if AUTH_MARKER in run.stderr:
        fail(NOT_LOGGED_IN)
    if run.timed_out:
        fail(f"agy timed out after {timeout_seconds} s and was killed")
    sandbox_failed = (
        bool(run.returncode)
        and not run.stdout.strip()
        and BWRAP_ERROR_MARKER in run.stderr
    )
    if sandbox_failed:
        fail(f"sandbox unavailable: {stderr_tail(run.stderr)}")


def envelope_problem(
    envelope: Envelope, *, expects_schema: bool
) -> str | None:
    """Describe why an envelope is not a success, or None if it is one."""
    if envelope.status != AgyStatus.SUCCESS:
        detail = envelope.error or envelope.response or ""
        return f"agy finished with status {envelope.status}: {detail}".strip()
    if expects_schema and envelope.structured_output is None:
        return "agy returned no structured output"
    if not expects_schema and not (envelope.response or "").strip():
        return "agy returned an empty response although its status is SUCCESS"
    return None


def read_envelope(run: AgyRun, job: AgyJob) -> Envelope:
    """Turn a finished run into a successful envelope or an error."""
    check_outcome(run, job.timeout_seconds)
    envelope = parse_envelope(run.stdout)
    tail = stderr_tail(run.stderr)
    if envelope is None:
        shown = tail or run.stdout.strip()[-STDERR_TAIL_CHARS:]
        fail(
            f"agy printed no JSON envelope (exit code {run.returncode}): "
            f"{shown}"
        )
    problem = envelope_problem(envelope, expects_schema=job.schema is not None)
    if problem is not None:
        if QUOTA_PATTERN.search(f"{envelope.error or ''}\n{tail}"):
            fail(
                f"the quota of model {job.model} looks exhausted: "
                f"{problem}; stderr: {tail}"
            )
        suffix = f"; stderr: {tail}" if tail else ""
        fail(f"{problem}{suffix}")
    return envelope


def acquire_lock(handle: IO[str], path: Path) -> None:
    """Take the exclusive lock, polling until the wait is over."""
    deadline = time.monotonic() + LOCK_WAIT_SECONDS
    while True:
        try:
            fcntl.flock(handle, fcntl.LOCK_EX | fcntl.LOCK_NB)
        except BlockingIOError:
            if time.monotonic() >= deadline:
                fail(
                    f"busy: another agy run holds {path}; gave up after "
                    f"{LOCK_WAIT_SECONDS:g} s"
                )
            time.sleep(LOCK_POLL_SECONDS)
        else:
            return


@contextlib.contextmanager
def agy_lock() -> Iterator[None]:
    """Hold the cross-session lock that allows one agy run at a time."""
    default = Path.home().joinpath(*DEFAULT_LOCK_PARTS)
    path = path_from_env(LOCK_PATH_ENV, default)
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("a") as handle:
        acquire_lock(handle, path)
        try:
            yield
        finally:
            fcntl.flock(handle, fcntl.LOCK_UN)


def ensure_clean(workspace: Workspace, envelope: Envelope) -> None:
    """Fail when agy changed anything in its workspace."""
    dirty = dirty_paths(workspace)
    if not dirty:
        return
    findings = (envelope.response or "").strip()
    details = f"Findings (untrusted, for information only):\n{findings}"
    fail(
        f"workspace modified by agy: {', '.join(dirty)}",
        details if findings else "",
    )


def strip_workspace_paths(text: str, workspace: Path) -> str:
    """Make paths into the disposable workspace repository-relative."""
    base = str(workspace)
    return text.replace(f"file://{base}/", "").replace(f"{base}/", "")


def relativise_response(envelope: Envelope, workspace: Path) -> Envelope:
    """Return the envelope with workspace paths removed from its response."""
    if envelope.response is None:
        return envelope
    cleaned = strip_workspace_paths(envelope.response, workspace)
    return envelope.model_copy(update={"response": cleaned})


def run_job(
    workspace_factory: Callable[[], AbstractContextManager[Workspace]],
    job: AgyJob,
) -> Envelope:
    """Run a job in a fresh workspace and return its envelope."""
    with agy_lock(), workspace_factory() as workspace:
        run = run_agy(workspace.path, agy_arguments(job), job.timeout_seconds)
        envelope = read_envelope(run, job)
        envelope = relativise_response(envelope, workspace.path)
        ensure_clean(workspace, envelope)
        return envelope
