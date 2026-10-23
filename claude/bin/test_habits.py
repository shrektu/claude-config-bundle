import functools
import importlib.machinery
import importlib.util
import inspect
import json
import os
import shutil
import subprocess
import sys
from pathlib import Path
from typing import TYPE_CHECKING

import pytest
from git_remote import parse_remote_slug

if TYPE_CHECKING:
    from types import ModuleType

MODULE_NAME = "habits"
SCRIPT_PATH = Path(__file__).with_name("habits")
STORE_NAME = "habits.json"
ENV_STORE = "HABITS_FILE"
ENCODING = "utf-8"
EXIT_OK = 0
EXIT_NOT_FOUND = 1
EXIT_USAGE = 2
FIRST_ID = "H001"
SECOND_ID = "H002"
UNKNOWN_ID = "H999"
REF_A = "device-service#12/345"
REF_B = "device-service#12/346"
REF_C = "device-service#13/400"
REVIEWER = "Anna"
OTHER_REVIEWER = "Piotr"
DAY_ONE = "2026-09-01"
DAY_TWO = "2026-09-15"
RULE = "Use pathlib"
WHY = "os.path is legacy"
GLOBAL = "global"
PYTHON = "python"
TYPESCRIPT = "typescript"
MY_REPO_SCOPE = "repo:acme/device-service"
OTHER_REPO_SCOPE = "repo:acme/other"
ORIGIN_URL = "git@bitbucket.org:acme/device-service.git"
HEADER_PREFIX = "Nawyki z review"
MORE_MARKER = "more: habits list --all"
CORRUPT_CONTENT = b'{"version": 1, "habits": [ broken'
BUMP_TIMES = 2
SMALL_CAP = 120
MANY_HABITS = 6
SEEDED_HABITS = 5
TIMES = "\N{MULTIPLICATION SIGN}"
EAGER_ANNOTATION_PYTHONS = ("python3.13", "python3.12")
PROBE_TIMEOUT_SECONDS = 10


def load_module() -> ModuleType:
    loader = importlib.machinery.SourceFileLoader(
        MODULE_NAME, str(SCRIPT_PATH)
    )
    spec = importlib.util.spec_from_loader(MODULE_NAME, loader)
    assert spec is not None
    module = importlib.util.module_from_spec(spec)
    sys.modules[MODULE_NAME] = module
    loader.exec_module(module)
    return module


@pytest.fixture
def store(tmp_path: Path) -> Path:
    return tmp_path / "lessons" / STORE_NAME


def run_habits(
    store_path: Path, *args: str, cwd: Path | None = None
) -> subprocess.CompletedProcess[str]:
    env = {"PATH": "/usr/bin:/bin", ENV_STORE: str(store_path)}
    return subprocess.run(
        [sys.executable, str(SCRIPT_PATH), *args],
        capture_output=True,
        text=True,
        env=env,
        cwd=cwd,
        check=False,
    )


def add(
    store_path: Path,
    scope: str,
    ref: str,
    rule: str = RULE,
    date: str = DAY_ONE,
) -> subprocess.CompletedProcess[str]:
    return run_habits(
        store_path,
        "add",
        "--scope",
        scope,
        "--rule",
        rule,
        "--why",
        WHY,
        "--source",
        ref,
        "--reviewer",
        REVIEWER,
        "--date",
        date,
    )


def bump(
    store_path: Path, habit_id: str, ref: str, date: str = DAY_TWO
) -> subprocess.CompletedProcess[str]:
    return run_habits(
        store_path,
        "bump",
        habit_id,
        "--source",
        ref,
        "--reviewer",
        OTHER_REVIEWER,
        "--date",
        date,
    )


def read_store(store_path: Path) -> dict:
    return json.loads(store_path.read_text(encoding=ENCODING))


def git(repo: Path, *args: str) -> None:
    subprocess.run(
        ["git", "-C", str(repo), *args],
        check=True,
        capture_output=True,
    )


def make_repo(
    root: Path, files: tuple[str, ...], origin: str | None = ORIGIN_URL
) -> Path:
    root.mkdir(parents=True)
    git(root, "init", "-q")
    for name in files:
        path = root / name
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text("x\n", encoding=ENCODING)
    git(root, "add", "--", *files)
    if origin is not None:
        git(root, "remote", "add", "origin", origin)
    return root


def test_add_prints_first_id_and_stores_one_habit(store: Path):
    result = add(store, PYTHON, REF_A)

    assert result.returncode == EXIT_OK
    assert result.stdout.strip() == FIRST_ID
    data = read_store(store)
    assert data["version"] == 1
    [habit] = data["habits"]
    assert habit["id"] == FIRST_ID
    assert habit["scope"] == PYTHON
    assert habit["rule"] == RULE
    assert habit["why"] == WHY
    assert habit["count"] == 1
    assert habit["created"] == DAY_ONE
    assert habit["last_seen"] == DAY_ONE
    assert habit["sources"] == [
        {"ref": REF_A, "reviewer": REVIEWER, "date": DAY_ONE}
    ]


def test_add_with_recorded_source_changes_nothing(store: Path):
    add(store, PYTHON, REF_A)
    before = store.read_bytes()

    result = add(store, GLOBAL, REF_A, rule="Another rule")

    assert result.returncode == EXIT_OK
    assert result.stdout.strip() == FIRST_ID
    assert store.read_bytes() == before


def test_add_allocates_next_id(store: Path):
    add(store, PYTHON, REF_A)

    result = add(store, GLOBAL, REF_B)

    assert result.stdout.strip() == SECOND_ID


def test_bump_increments_count_and_appends_source(store: Path):
    add(store, PYTHON, REF_A)

    result = bump(store, FIRST_ID, REF_B)

    assert result.returncode == EXIT_OK
    [habit] = read_store(store)["habits"]
    assert habit["count"] == BUMP_TIMES
    assert habit["last_seen"] == DAY_TWO
    assert habit["created"] == DAY_ONE
    assert [s["ref"] for s in habit["sources"]] == [REF_A, REF_B]
    assert habit["sources"][1]["reviewer"] == OTHER_REVIEWER


def test_bump_with_recorded_source_changes_nothing(store: Path):
    add(store, PYTHON, REF_A)
    bump(store, FIRST_ID, REF_B)
    before = store.read_bytes()

    result = bump(store, FIRST_ID, REF_A)

    assert result.returncode == EXIT_OK
    assert store.read_bytes() == before


def test_bump_unknown_id_exits_2(store: Path):
    add(store, PYTHON, REF_A)
    before = store.read_bytes()

    result = bump(store, UNKNOWN_ID, REF_B)

    assert result.returncode == EXIT_USAGE
    assert UNKNOWN_ID in result.stderr
    assert store.read_bytes() == before


def test_drop_removes_habit_and_unknown_exits_2(store: Path):
    add(store, PYTHON, REF_A)

    dropped = run_habits(store, "drop", FIRST_ID)
    missing = run_habits(store, "drop", FIRST_ID)

    assert dropped.returncode == EXIT_OK
    assert read_store(store)["habits"] == []
    assert missing.returncode == EXIT_USAGE


def test_seen_reports_recorded_sources(store: Path):
    add(store, PYTHON, REF_A)

    assert run_habits(store, "seen", REF_A).returncode == EXIT_OK
    assert run_habits(store, "seen", REF_B).returncode == EXIT_NOT_FOUND


def test_invalid_scope_exits_2_without_writing(store: Path):
    result = add(store, "rust", REF_A)

    assert result.returncode == EXIT_USAGE
    assert "rust" in result.stderr
    assert not store.exists()


def seed_relevance_store(store: Path) -> None:
    add(store, GLOBAL, "g#1/1", rule="global rule")
    add(store, PYTHON, "p#1/1", rule="python rule")
    add(store, MY_REPO_SCOPE, "r#1/1", rule="repo rule")
    add(store, TYPESCRIPT, "t#1/1", rule="typescript rule")
    add(store, OTHER_REPO_SCOPE, "o#1/1", rule="other repo rule")
    bump(store, "H003", "r#1/2")
    bump(store, "H003", "r#1/3")
    bump(store, "H002", "p#1/2")


def test_list_prints_habits_relevant_to_repo_by_count(
    store: Path, tmp_path: Path
):
    repo = make_repo(tmp_path / "repo", ("src/app.py", "README.md"))
    seed_relevance_store(store)

    result = run_habits(store, "list", "--repo", str(repo))

    assert result.returncode == EXIT_OK
    lines = result.stdout.splitlines()
    assert lines[0] == f"{HEADER_PREFIX} (3):"
    assert lines[1] == f"H003 [{MY_REPO_SCOPE}] repo rule — {WHY} (3{TIMES})"
    assert lines[2] == f"H002 [{PYTHON}] python rule — {WHY} (2{TIMES})"
    assert lines[3] == f"H001 [{GLOBAL}] global rule — {WHY} (1{TIMES})"
    assert len(lines) == len(["header", "H003", "H002", "H001"])


def test_list_uses_cwd_repo_without_repo_option(store: Path, tmp_path: Path):
    repo = make_repo(tmp_path / "repo", ("src/app.py",))
    seed_relevance_store(store)

    result = run_habits(store, "list", cwd=repo / "src")

    assert "H002" in result.stdout
    assert "H003" in result.stdout
    assert "H004" not in result.stdout


def test_list_cap_ends_with_more_line(store: Path, tmp_path: Path):
    repo = make_repo(tmp_path / "repo", ("app.py",))
    for index in range(MANY_HABITS):
        add(store, GLOBAL, f"g#1/{index}", rule=f"rule number {index}")

    result = run_habits(
        store, "list", "--repo", str(repo), "--max-chars", str(SMALL_CAP)
    )

    lines = result.stdout.splitlines()
    assert len(result.stdout) <= SMALL_CAP
    assert lines[0] == f"{HEADER_PREFIX} ({MANY_HABITS}):"
    shown = len(lines) - len(["header", "more"])
    assert shown >= 1
    assert lines[-1] == f"… {MANY_HABITS - shown} {MORE_MARKER}"


def test_list_all_prints_every_habit(store: Path, tmp_path: Path):
    seed_relevance_store(store)

    result = run_habits(store, "list", "--all", cwd=tmp_path)

    assert result.stdout.count("\n") == len(["header"]) + SEEDED_HABITS


def test_list_without_relevant_habits_prints_nothing(
    store: Path, tmp_path: Path
):
    repo = make_repo(tmp_path / "repo", ("app.py",))
    add(store, TYPESCRIPT, "t#1/1")

    result = run_habits(store, "list", "--repo", str(repo))

    assert result.returncode == EXIT_OK
    assert result.stdout == ""


def test_list_with_missing_store_prints_nothing(store: Path, tmp_path: Path):
    result = run_habits(store, "list", cwd=tmp_path)

    assert result.returncode == EXIT_OK
    assert result.stdout == ""
    assert not store.exists()


def test_concurrent_adds_both_persist(store: Path):
    args = [
        [
            sys.executable,
            str(SCRIPT_PATH),
            "add",
            "--scope",
            GLOBAL,
            "--rule",
            RULE,
            "--why",
            WHY,
            "--source",
            ref,
            "--reviewer",
            REVIEWER,
        ]
        for ref in (REF_A, REF_B, REF_C)
    ]
    env = {"PATH": "/usr/bin:/bin", ENV_STORE: str(store)}
    processes = [
        subprocess.Popen(command, env=env, stdout=subprocess.PIPE)
        for command in args
    ]
    codes = [process.wait() for process in processes]
    for process in processes:
        assert process.stdout is not None
        process.stdout.close()

    assert codes == [EXIT_OK] * len(args)
    habits = read_store(store)["habits"]
    assert {h["sources"][0]["ref"] for h in habits} == {REF_A, REF_B, REF_C}
    assert sorted(h["id"] for h in habits) == ["H001", "H002", "H003"]


def test_add_on_corrupt_store_exits_2_and_keeps_file(store: Path):
    store.parent.mkdir(parents=True)
    store.write_bytes(CORRUPT_CONTENT)

    result = add(store, PYTHON, REF_A)

    assert result.returncode == EXIT_USAGE
    assert store.read_bytes() == CORRUPT_CONTENT


def test_add_on_wrong_shape_store_exits_2_and_keeps_file(store: Path):
    store.parent.mkdir(parents=True)
    content = b'{"version": 1, "habits": [{"id": "H001"}]}'
    store.write_bytes(content)

    result = add(store, PYTHON, REF_A)

    assert result.returncode == EXIT_USAGE
    assert store.read_bytes() == content


@pytest.fixture(scope="module")
def habits() -> ModuleType:
    return load_module()


def make_habit(
    habits: ModuleType,
    habit_id: str,
    count: int = 1,
    last_seen: str = DAY_ONE,
    scope: str = GLOBAL,
) -> object:
    return habits.Habit(
        id=habit_id,
        scope=scope,
        rule=RULE,
        why=WHY,
        count=count,
        created=DAY_ONE,
        last_seen=last_seen,
        sources=[],
    )


@pytest.mark.parametrize(
    ("url", "expected"),
    [
        ("git@bitbucket.org:acme/device-service.git", "acme/device-service"),
        ("git@bitbucket.org:acme/device-service", "acme/device-service"),
        (
            "https://seb@bitbucket.org/acme/device-service.git",
            "acme/device-service",
        ),
        ("https://bitbucket.org/acme/device-service", "acme/device-service"),
        ("ssh://git@bitbucket.org/acme/device-service", "acme/device-service"),
        (
            "ssh://git@bitbucket.org:22/acme/device-service.git",
            "acme/device-service",
        ),
        (
            "https://bitbucket.org/acme/device-service.git/\n",
            "acme/device-service",
        ),
        ("", None),
        ("device-service", None),
        ("git@bitbucket.org:device-service.git", None),
        ("https://bitbucket.org/acme/.git", None),
    ],
)
def test_parse_remote_slug(url: str, expected: str) -> None:
    assert parse_remote_slug(url) == expected


@pytest.mark.parametrize(
    "scope",
    [GLOBAL, PYTHON, TYPESCRIPT, "javascript", "c", "cpp", MY_REPO_SCOPE],
)
def test_validate_scope_accepts_known_scopes(habits: ModuleType, scope: str):
    assert habits.validate_scope(scope) == scope


@pytest.mark.parametrize(
    "scope",
    ["rust", "Global", "repo:", "repo:acme", "repo:a/b/c", "repo:a /b"],
)
def test_validate_scope_rejects_unknown_scopes(habits: ModuleType, scope: str):
    with pytest.raises(habits.argparse.ArgumentTypeError):
        habits.validate_scope(scope)


def test_next_habit_id_follows_highest_numeric_id(habits: ModuleType):
    existing = [
        make_habit(habits, "H001"),
        make_habit(habits, "H007"),
        make_habit(habits, "custom"),
    ]

    assert habits.next_habit_id([]) == FIRST_ID
    assert habits.next_habit_id(existing) == "H008"


def test_languages_of_maps_suffixes(habits: ModuleType):
    paths = [
        "a.py",
        "b.pyi",
        "c.ts",
        "d.tsx",
        "e.mts",
        "f.cts",
        "g.js",
        "h.jsx",
        "i.mjs",
        "j.cjs",
        "k.c",
        "l.h",
        "m.cpp",
        "n.cc",
        "o.cxx",
        "p.hpp",
        "q.hh",
        "README.md",
        "Makefile",
    ]

    assert habits.languages_of(paths) == {
        PYTHON,
        TYPESCRIPT,
        "javascript",
        "c",
        "cpp",
    }
    assert habits.languages_of(["x.md", "y.rs"]) == set()


def test_ordered_by_count_then_last_seen_then_id(habits: ModuleType):
    items = [
        make_habit(habits, "H004", count=1, last_seen=DAY_TWO),
        make_habit(habits, "H003", count=2, last_seen=DAY_ONE),
        make_habit(habits, "H002", count=1, last_seen=DAY_ONE),
        make_habit(habits, "H001", count=1, last_seen=DAY_ONE),
    ]

    result = [habit.id for habit in habits.ordered(items)]

    assert result == ["H003", "H004", "H001", "H002"]


def test_render_habits_without_cap_prints_all(habits: ModuleType):
    items = [make_habit(habits, f"H00{n}") for n in range(1, 4)]

    lines = habits.render_habits(items, None)

    assert lines[0] == f"{HEADER_PREFIX} (3):"
    assert len(lines) == len(["header", "one", "two", "three"])


def test_render_habits_cap_keeps_room_for_more_line(habits: ModuleType):
    items = [make_habit(habits, f"H00{n}") for n in range(1, 4)]
    full = "\n".join(habits.render_habits(items, None)) + "\n"
    cap = len(full) - 1

    lines = habits.render_habits(items, cap)

    assert len("\n".join(lines)) + 1 <= cap
    assert lines[-1].startswith("… ")
    assert lines[-1].endswith(MORE_MARKER)


def test_render_habits_exact_cap_prints_all(habits: ModuleType):
    items = [make_habit(habits, f"H00{n}") for n in range(1, 4)]
    full = "\n".join(habits.render_habits(items, None)) + "\n"

    assert habits.render_habits(items, len(full)) == full.splitlines()


def test_render_habits_tiny_cap_prints_header_and_more(habits: ModuleType):
    items = [make_habit(habits, "H001")]

    lines = habits.render_habits(items, 1)

    assert lines == [f"{HEADER_PREFIX} (1):", f"… 1 {MORE_MARKER}"]


def test_render_habits_empty_prints_nothing(habits: ModuleType):
    assert habits.render_habits([], None) == []


def test_render_habits_cap_reserves_room_for_more_line(habits: ModuleType):
    items = [make_habit(habits, f"H00{n}") for n in range(1, 4)]
    full = habits.render_habits(items, None)
    cap = len("\n".join(full[:-1])) + 1

    lines = habits.render_habits(items, cap)

    assert len("\n".join(lines)) + 1 <= cap
    assert lines[-1] == f"… 2 {MORE_MARKER}"


def test_add_on_empty_store_file_creates_first_habit(store: Path):
    store.parent.mkdir(parents=True)
    store.write_text("", encoding=ENCODING)

    result = add(store, PYTHON, REF_A)

    assert result.returncode == EXIT_OK
    assert result.stdout.strip() == FIRST_ID
    assert len(read_store(store)["habits"]) == 1


def test_add_creates_missing_parent_directories(tmp_path: Path):
    nested = tmp_path / "a" / "b" / "c" / STORE_NAME

    result = add(nested, PYTHON, REF_A)

    assert result.returncode == EXIT_OK
    assert read_store(nested)["habits"][0]["id"] == FIRST_ID


def test_list_outside_git_repo_prints_only_global(store: Path, tmp_path: Path):
    plain = tmp_path / "plain"
    plain.mkdir()
    (plain / "app.py").write_text("x\n", encoding=ENCODING)
    seed_relevance_store(store)

    result = run_habits(store, "list", "--repo", str(plain))

    lines = result.stdout.splitlines()
    assert result.returncode == EXIT_OK
    assert lines == [
        f"{HEADER_PREFIX} (1):",
        f"H001 [{GLOBAL}] global rule — {WHY} (1{TIMES})",
    ]


def test_list_in_repo_without_origin_has_no_repo_scope(
    store: Path, tmp_path: Path
):
    repo = make_repo(tmp_path / "repo", ("app.py",), origin=None)
    seed_relevance_store(store)

    result = run_habits(store, "list", "--repo", str(repo))

    assert "H003" not in result.stdout
    assert "H002" in result.stdout


def test_list_on_corrupt_store_exits_2(store: Path, tmp_path: Path):
    store.parent.mkdir(parents=True)
    store.write_bytes(CORRUPT_CONTENT)

    result = run_habits(store, "list", cwd=tmp_path)

    assert result.returncode == EXIT_USAGE
    assert result.stdout == ""
    assert store.read_bytes() == CORRUPT_CONTENT


def test_annotations_resolve_without_type_checking_imports(
    habits: ModuleType,
) -> None:
    defined = [
        member
        for _, member in inspect.getmembers(habits)
        if (inspect.isfunction(member) or inspect.isclass(member))
        and member.__module__ == MODULE_NAME
    ]

    annotations = [inspect.get_annotations(member) for member in defined]

    assert defined
    assert all(isinstance(found, dict) for found in annotations)


def runs(python: str | None) -> bool:
    if python is None:
        return False
    probe = subprocess.run(
        [python, "-c", ""],
        capture_output=True,
        check=False,
        timeout=PROBE_TIMEOUT_SECONDS,
    )
    return probe.returncode == EXIT_OK


@functools.cache
def eager_annotation_python() -> str | None:
    candidates = map(shutil.which, EAGER_ANNOTATION_PYTHONS)
    return next(filter(runs, candidates), None)


@pytest.mark.skipif(
    eager_annotation_python() is None, reason="no Python before 3.14"
)
def test_list_runs_on_python_with_eager_annotations(
    store: Path, tmp_path: Path
) -> None:
    add(store, GLOBAL, REF_A)
    python = eager_annotation_python()
    assert python is not None

    result = subprocess.run(
        [python, str(SCRIPT_PATH), "list", "--all"],
        capture_output=True,
        text=True,
        env={**os.environ, ENV_STORE: str(store)},
        cwd=tmp_path,
        check=False,
        timeout=PROBE_TIMEOUT_SECONDS,
    )

    assert result.returncode == EXIT_OK, result.stderr
    assert RULE in result.stdout
