import json
import os
import subprocess
import time
from collections.abc import Callable
from dataclasses import dataclass
from pathlib import Path

import agy_worker
from pydantic import BaseModel

REAL_BWRAP = "/usr/bin/bwrap"
BAKED_MARKER = "AGY_BAKED_ORIGINAL"
NO_TOOLS_SENTENCE = (
    "You have no tools: never run commands, never read or write files. "
    "Produce the answer in a single reply from this prompt alone."
)
REAL_DBUS_PROXY = "/usr/bin/xdg-dbus-proxy"
REAL_DBUS_ADDRESS = os.environ.get("DBUS_SESSION_BUS_ADDRESS", "")
REAL_RUNTIME_DIR = os.environ.get("XDG_RUNTIME_DIR", "")
FAKE_RUNTIME_DIR = "/run/user/4242"
FAKE_DBUS_ADDRESS = "unix:path=/run/user/4242/host-bus"
GIT_TIMEOUT = 60
MAX_AUTH_SECONDS = 10
EXECUTABLE_MODE = 0o755
TRACKED_FILE = "tracked.txt"
IGNORED_FILE = "ignored.log"
ORIGIN_URL = "https://github.com/acme/widgets.git"
FOREIGN_URL = "https://gitlab.com/acme/widgets.git"
GIT_IDENTITY = [
    "-c",
    "user.email=t@t",
    "-c",
    "user.name=t",
    "-c",
    "commit.gpgsign=false",
]
WHAT_CHANGED = "Replace the polling loop with an interrupt handler"
REVIEW_FOCUS = "ordering and rollback"
REVIEW_BODY = "IMPORTANT\n- step 3 breaks the rollback\nPASS"
PLAN_SUCCESS_TEXT = (
    "Gemini review completed "
    "(mode=plan, model=gemini-3.8-flash-medium, workspace=clean).\n\n"
    "Findings:\n" + REVIEW_BODY
)
DATASHEET_CLAIMS = [
    "Reset value of CTRL is 0x00",
    "Maximum SPI clock is 20 MHz",
    "Supply voltage is 3.3 V",
]
DATASHEET_STRUCTURED = {
    "claims": [
        {
            "id": 1,
            "verdict": "refuted",
            "pdf_pages": [4],
            "printed_pages": ["4-2"],
            "evidence": "CTRL resets to 0x01",
            "correction": "reset value is 0x01",
        },
        {
            "id": 2,
            "verdict": "uncertain",
            "pdf_pages": [7],
            "printed_pages": [],
            "evidence": "only the typical value is listed",
            "correction": "",
        },
        {
            "id": 3,
            "verdict": "confirmed",
            "pdf_pages": [2],
            "printed_pages": ["2"],
            "evidence": "VDD = 3.3 V",
            "correction": "",
        },
    ]
}
DATASHEET_SUCCESS_TEXT = (
    "Argon datasheet check completed (model=gemini-4-argon-high, "
    "pdf=spec.pdf, pages=all, workspace=clean).\n\n"
    "REFUTED\n"
    "#1 Reset value of CTRL is 0x00 — PDF p. 4 (printed 4-2): "
    '"CTRL resets to 0x01" [→ reset value is 0x01]\n\n'
    "UNCERTAIN\n"
    "#2 Maximum SPI clock is 20 MHz — PDF p. 7: "
    '"only the typical value is listed"\n\n'
    "INVALID CITATION\n(none)\n\n"
    "MISSING VERDICT\n(none)\n\n"
    "CONFIRMED\n"
    '#3 Supply voltage is 3.3 V — PDF p. 2 (printed 2): "VDD = 3.3 V"'
)
TRANSLATE_ENTRIES = {
    "greeting": "Hello {{name}}",
    "bye": "Goodbye",
}
TRANSLATE_STRUCTURED = {
    "translations": {
        "greeting": "Cześć {{name}}",
        "bye": "Do widzenia",
    }
}
ARGON_MODEL = "gemini-4-argon-high"

FAKE_BWRAP_SOURCE = """#!/usr/bin/env python3
import os
import sys

if os.environ.get("AGY_FAKE_BWRAP_FAIL"):
    sys.stderr.write("bwrap: setting up uid map: Permission denied\\n")
    sys.exit(1)
arguments = sys.argv[1:]
separator = arguments.index("--")
with open(os.environ["AGY_FAKE_BWRAP_RECORD"], "w") as record:
    record.write("\\n".join(arguments[:separator]))
flags = arguments[:separator]
for index, flag in enumerate(flags):
    if flag == "--setenv":
        os.environ[flags[index + 1]] = flags[index + 2]
command = arguments[separator + 1:]
os.execv(command[0], command)
"""

FAKE_PROXY_SOURCE = """#!/usr/bin/env python3
import json
import os
import socket
import sys
import time

mode = os.environ.get("AGY_FAKE_PROXY_MODE", "ok")
with open(os.environ["AGY_FAKE_PROXY_PID_FILE"], "w") as handle:
    handle.write(str(os.getpid()))
with open(os.environ["AGY_FAKE_PROXY_RECORD"], "w") as handle:
    json.dump(sys.argv[1:], handle)
if mode == "exit":
    sys.exit(3)
if mode != "silent":
    listener = socket.socket(socket.AF_UNIX)
    listener.bind(sys.argv[2])
time.sleep(60)
"""

FAKE_AGY_SOURCE = """#!/usr/bin/env python3
import json
import os
import subprocess
import sys
import time

DEFAULT_RESPONSE = "REVIEW BODY"
HANG_SECONDS = 20
BUSCTL = [
    "busctl", "--user", "call", "org.freedesktop.systemd1",
    "/org/freedesktop/systemd1", "org.freedesktop.systemd1.Manager",
    "GetDefaultTarget",
]


def emit(status="SUCCESS", response="", structured=None, error=None):
    body = {
        "conversation_id": "c1",
        "status": status,
        "response": response,
        "duration_seconds": 1.0,
        "num_turns": 1,
        "usage": {},
    }
    if structured is not None:
        body["structured_output"] = structured
    if error is not None:
        body["error"] = error
    print(json.dumps(body), flush=True)


def listing(root):
    found = {}
    for base, dirs, names in os.walk(root):
        dirs[:] = [name for name in dirs if name != ".git"]
        for name in names:
            path = os.path.join(base, name)
            try:
                with open(path, encoding="utf-8") as handle:
                    found[os.path.relpath(path, root)] = handle.read()
            except UnicodeDecodeError:
                found[os.path.relpath(path, root)] = None
    return found


def pdf_pages():
    if not os.path.exists("document.pdf"):
        return None
    info = subprocess.run(
        ["pdfinfo", "document.pdf"], capture_output=True, text=True
    ).stdout
    for line in info.splitlines():
        if line.startswith("Pages:"):
            return int(line.split()[1])
    return None


def record(arguments):
    target = os.environ.get("AGY_FAKE_RECORD")
    if not target:
        return
    null_device = os.stat("/dev/null")
    standard_input = os.fstat(0)
    body = {
        "argv": arguments,
        "cwd": os.getcwd(),
        "stdin_is_devnull": standard_input.st_rdev == null_device.st_rdev,
        "files": listing(os.getcwd()),
        "pdf_pages": pdf_pages(),
        "dbus_address": os.environ.get("DBUS_SESSION_BUS_ADDRESS"),
    }
    with open(target, "w") as handle:
        json.dump(body, handle)


def attempt(action):
    try:
        action()
    except OSError:
        return "CANNOT"
    return "OK"


def read_outside():
    with open(os.environ["AGY_FAKE_READ_PATH"]) as handle:
        handle.read()


def write_outside():
    with open(os.environ["AGY_FAKE_WRITE_PATH"], "w") as handle:
        handle.write("escaped")


def gemini_listing():
    gemini = os.path.join(os.environ["HOME"], ".gemini")
    return sorted(os.listdir(gemini)) if os.path.isdir(gemini) else None


def write_gemini_settings():
    folder = os.path.join(os.environ["HOME"], ".gemini", "antigravity-cli")
    os.makedirs(folder, exist_ok=True)
    with open(os.path.join(folder, "settings.json"), "w") as handle:
        handle.write('{"permissions": {"allow": ["Bash(ls)"]}}')


def spawn_stubborn_grandchild():
    code = (
        "import signal, time\\n"
        "signal.signal(signal.SIGTERM, signal.SIG_IGN)\\n"
        "time.sleep(%d)\\n" % HANG_SECONDS
    )
    marker = os.environ.get("AGY_FAKE_HANG_MARKER", "")
    child = subprocess.Popen([sys.executable, "-c", code, marker])
    pid_file = os.environ.get("AGY_FAKE_PID_FILE")
    if pid_file:
        with open(pid_file, "w") as handle:
            handle.write(str(child.pid))


arguments = sys.argv[1:]
mode = os.environ.get("AGY_FAKE_MODE", "ok")
record(arguments)
if mode == "auth":
    sys.stderr.write(
        "Authentication required. Please visit the URL https://x.invalid\\n"
    )
    sys.stderr.flush()
    time.sleep(HANG_SECONDS)
elif arguments[:1] == ["models"]:
    print("gemini-4-argon-low\\ngemini-3.8-flash-medium")
elif mode == "empty":
    sys.stderr.write(
        'jetski: no output produced - a tool required the "command" '
        "permission\\n"
    )
    emit(response="")
elif mode == "quota":
    emit(status="ERROR", error="RESOURCE_EXHAUSTED: quota exceeded")
    sys.exit(1)
elif mode == "error":
    emit(status="ERROR", error="unknown model foo; available: a, b")
    sys.exit(1)
elif mode == "nonjson":
    print("this is not json")
elif mode == "write":
    with open("evil.txt", "w") as handle:
        handle.write("changed")
    emit(response=DEFAULT_RESPONSE)
elif mode == "hang":
    spawn_stubborn_grandchild()
    time.sleep(HANG_SECONDS)
elif mode == "isolation":
    emit(
        response="read=%s write=%s"
        % (attempt(read_outside), attempt(write_outside))
    )
elif mode == "env":
    names = globals().get("AGY_BAKED_ORIGINAL") or sorted(os.environ)
    emit(response=json.dumps(names))
elif mode == "locked":
    for base in (os.getcwd(), os.path.join(os.environ["HOME"], ".gemini")):
        os.makedirs(os.path.join(base, "locked"), exist_ok=True)
        with open(os.path.join(base, "locked", "inner.txt"), "w") as handle:
            handle.write("x")
        os.chmod(os.path.join(base, "locked"), 0)
    emit(response=DEFAULT_RESPONSE)
elif mode == "gemini":
    emit(
        response="listing=%s write=%s"
        % (gemini_listing(), attempt(write_gemini_settings))
    )
elif mode == "cwd":
    here = os.getcwd()
    text = "see file://%s/ratelimit.py#L14 and %s/auth.py:3"
    emit(response=text % (here, here))
elif mode == "systemd":
    done = subprocess.run(BUSCTL, capture_output=True, text=True, timeout=30)
    emit(response="systemd=%s" % ("OK" if done.returncode == 0 else "CANNOT"))
elif mode == "ok":
    structured = os.environ.get("AGY_FAKE_STRUCTURED")
    if "--json-schema" in arguments and structured:
        emit(structured=json.loads(structured))
    else:
        emit(response=os.environ.get("AGY_FAKE_RESPONSE", DEFAULT_RESPONSE))
"""


class Invocation(BaseModel):
    argv: list[str]
    cwd: str
    stdin_is_devnull: bool
    files: dict[str, str | None]
    pdf_pages: int | None
    dbus_address: str | None


@dataclass(slots=True)
class FakeAgy:
    record: Path
    work_dir: Path
    lock_path: Path
    proxy_pid_file: Path
    proxy_record: Path
    bwrap_record: Path

    def ran(self) -> bool:
        return self.record.exists()

    def invocation(self) -> Invocation:
        return Invocation.model_validate_json(self.record.read_text())

    def proxy_args(self) -> list[str]:
        result: list[str] = json.loads(self.proxy_record.read_text())
        return result

    def proxy_pid(self) -> int:
        return int(self.proxy_pid_file.read_text())

    def bwrap_flags(self) -> list[str]:
        return self.bwrap_record.read_text().splitlines()


def git(repo: Path, *args: str) -> None:
    subprocess.run(
        ["git", "-C", str(repo), *GIT_IDENTITY, *args],
        check=True,
        capture_output=True,
        timeout=GIT_TIMEOUT,
    )


def git_output(repo: Path, *args: str) -> str:
    output: str = subprocess.run(
        ["git", "-C", str(repo), *args],
        check=True,
        capture_output=True,
        text=True,
        timeout=GIT_TIMEOUT,
    ).stdout
    return output


def repo_state(repo: Path) -> dict[str, str]:
    return {
        "refs": git_output(repo, "for-each-ref"),
        "head": git_output(repo, "rev-parse", "HEAD"),
        "index": git_output(repo, "ls-files", "-s"),
        "status": git_output(repo, "status", "--porcelain", "--ignored"),
        "worktrees": git_output(repo, "worktree", "list"),
        "stash": git_output(repo, "stash", "list"),
    }


def make_repo(root: Path, origin: str) -> Path:
    root.mkdir()
    git(root, "init", "-q")
    (root / TRACKED_FILE).write_text("original\n")
    git(root, "add", TRACKED_FILE)
    git(root, "commit", "-q", "-m", "initial")
    git(root, "remote", "add", "origin", origin)
    return root


def force_add_ignored_file(repo: Path) -> bytes:
    (repo / ".gitignore").write_text(f"{IGNORED_FILE}\n")
    git(repo, "add", ".gitignore")
    git(repo, "commit", "-q", "-m", "ignore")
    (repo / IGNORED_FILE).write_text("forced in\n")
    git(repo, "add", "-f", IGNORED_FILE)
    return (repo / ".git" / "index").read_bytes()


def make_pdf(path: Path, pages: int) -> None:
    kids = " ".join(f"{3 + index} 0 R" for index in range(pages))
    bodies = [
        "<< /Type /Catalog /Pages 2 0 R >>",
        f"<< /Type /Pages /Kids [{kids}] /Count {pages} >>",
        *["<< /Type /Page /Parent 2 0 R /MediaBox [0 0 200 200] >>"] * pages,
    ]
    out = b"%PDF-1.4\n"
    offsets = []
    for number, body in enumerate(bodies, start=1):
        offsets.append(len(out))
        out += f"{number} 0 obj\n{body}\nendobj\n".encode()
    table = "".join(f"{offset:010d} 00000 n \n" for offset in offsets)
    out += (
        f"xref\n0 {len(bodies) + 1}\n0000000000 65535 f \n{table}"
        f"trailer\n<< /Size {len(bodies) + 1} /Root 1 0 R >>\n"
        f"startxref\n{len(out)}\n%%EOF\n"
    ).encode()
    path.write_bytes(out)


def bake_fake_environment() -> None:
    if os.environ.get("AGY_BWRAP") != REAL_BWRAP:
        return
    script = Path(os.environ["AGY_BIN"])
    source = script.read_text()
    if f"{BAKED_MARKER} = " in source:
        return
    baked = {
        name: value
        for name, value in os.environ.items()
        if name.startswith("AGY_FAKE_")
    }
    shebang, _, rest = source.partition("\n")
    script.write_text(
        f"{shebang}\nimport os\n{BAKED_MARKER} = sorted(os.environ)\n"
        f"os.environ.update({baked!r})\n{rest}"
    )


def plan_review(repo: Path, **kwargs: str) -> str:
    bake_fake_environment()
    result: str = agy_worker.agy_plan_review(
        what_changed=WHAT_CHANGED,
        review_focus=REVIEW_FOCUS,
        project_path=str(repo),
        **kwargs,
    )
    return result


def translate(repo: Path, entries: dict[str, str]) -> str:
    result: str = agy_worker.agy_translate(
        project_path=str(repo),
        entries=entries,
        source_lang="en",
        target_lang="pl",
    )
    return result


def datasheet_claims(*cited: tuple[int, str, list[int]]) -> str:
    return json.dumps(
        {
            "claims": [
                {
                    "id": number,
                    "verdict": verdict,
                    "pdf_pages": pages,
                    "printed_pages": [],
                    "evidence": f"evidence {number}",
                    "correction": "",
                }
                for number, verdict, pages in cited
            ]
        }
    )


def wait_until(condition: Callable[[], bool], seconds: float = 5.0) -> bool:
    deadline = time.monotonic() + seconds
    while time.monotonic() < deadline:
        if condition():
            return True
        time.sleep(0.05)
    return condition()


def process_gone(pid: int) -> bool:
    try:
        stat = Path(f"/proc/{pid}/stat").read_text()
    except FileNotFoundError:
        return True
    return stat.rpartition(")")[2].split()[0] == "Z"


def pids_with_marker(marker: str) -> list[int]:
    found = []
    for entry in Path("/proc").iterdir():
        if not entry.name.isdigit():
            continue
        try:
            command = (entry / "cmdline").read_bytes()
        except OSError:
            continue
        if marker.encode() in command and not process_gone(int(entry.name)):
            found.append(int(entry.name))
    return found
