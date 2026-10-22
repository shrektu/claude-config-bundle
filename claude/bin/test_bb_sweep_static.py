from __future__ import annotations

import ast
import importlib.machinery
import importlib.util
import json
import os
import shutil
import subprocess
import sys
from dataclasses import dataclass, field
from pathlib import Path
from typing import TYPE_CHECKING, Any, NamedTuple

import magic_numbers
import pytest

if TYPE_CHECKING:
    from types import ModuleType

TOOL = Path(__file__).resolve().with_name("bb-sweep")
MODULE_NAME = "bb_sweep_static_under_test"
PLACEHOLDER = "@@"
MAGIC = "magic-number"
COMMENTED = "commented-code"
LITERAL_ATTR = "literal-attr"
EMPTY_CATCH = "empty-catch"
DUPLICATION = "duplication"
USAGE_EXIT = 2
FORMATTING_PREFIXES = ("E1", "E2", "E3", "E5", "W", "I", "D", "Q", "COM")
HARMLESS_LINES = {
    ".py": "MARKER = True\n",
    ".c": "/* done */\n",
    ".cpp": "/* done */\n",
    ".ts": "/* done */\n",
    ".tsx": "/* done */\n",
}

PY_STMT = "def run(self, data, slot_id):\n    @@\n    return None\n"
PY_KWARG = "def run(data):\n    return Diag(\n        @@\n    )\n"
PY_QUANT = (
    "def price(self):\n    return [\n        @@\n"
    '            Decimal("0.01")\n        )\n    ]\n'
)
PY_BLOCK = "def run(machine_instance):\n    @@\n        print(ns_provider)\n"
PY_OR = (
    'def run(operation):\n    @@\n        operation, "__name__", None\n    )\n'
)
PY_ELSE = (
    "def run(x):\n    return (\n        {0}\n        if x\n        @@\n    )\n"
)
C_STMT = "void run(void) {\n    @@\n}\n"
TS_STMT = "function run() {\n    @@\n}\n"


class Case(NamedTuple):
    ext: str
    category: str
    template: str
    code: str


EXEMPT_CASES = [
    Case(
        ".py",
        MAGIC,
        PY_QUANT,
        "(Decimal(str(self.price)) * Decimal(100)).quantize(",
    ),
    Case(
        ".cpp",
        MAGIC,
        C_STMT,
        "lv_obj_set_size(continue_button_obj, 220, 54);",
    ),
    Case(
        ".py",
        MAGIC,
        PY_KWARG,
        'machine_id=data[14:24].decode("ascii", errors="replace")'
        '.rstrip("\\x00 "),',
    ),
    Case(".py", MAGIC, PY_QUANT, "(value * Decimal(100)).quantize("),
    Case(".py", MAGIC, PY_ELSE, "else {0x48, 0x49}"),
    Case(
        ".ts",
        MAGIC,
        TS_STMT,
        "return moduleIds.length > SINGLE_MODULE_THRESHOLD ? 5 : 4;",
    ),
    Case(
        ".c",
        MAGIC,
        C_STMT,
        "return (voltage - data->voltage_temp0) * 50.0 / "
        "(data->voltage_temp50 - data->voltage_temp0);",
    ),
    Case(".c", MAGIC, C_STMT, "int32_t base_idx = pos_q8 / 256;"),
    Case(".cpp", MAGIC, C_STMT, "lv_obj_set_size(chk, 26, 26);"),
    Case(
        ".c",
        MAGIC,
        C_STMT,
        "snprintf(voltage_string, sizeof(voltage_string), "
        '"%d.%d", voltage[0], voltage[1]/1000);',
    ),
    Case(".tsx", MAGIC, TS_STMT, "doc.setFontSize(16);"),
]

CASES = [
    Case(".cpp", MAGIC, C_STMT, "if (temp > 37) {}"),
    Case(".ts", MAGIC, TS_STMT, "if (count === 7) {}"),
    Case(".tsx", MAGIC, TS_STMT, "return voltage >= 3300;"),
    Case(".py", MAGIC, PY_BLOCK, "if machine_instance > 37:"),
    Case(
        ".py",
        COMMENTED,
        PY_STMT,
        "#self._control.set_active_slot_led(slot_id, False)",
    ),
    Case(
        ".py",
        LITERAL_ATTR,
        PY_STMT,
        'config = getattr(self, "_config", None)',
    ),
    Case(".py", COMMENTED, PY_STMT, "# try:"),
    Case(".py", COMMENTED, PY_STMT, "# time.sleep(0.3)"),
    Case(
        ".py",
        LITERAL_ATTR,
        PY_BLOCK,
        'for ns_provider in getattr(machine_instance, "namespaces", []):',
    ),
    Case(
        ".py",
        COMMENTED,
        PY_STMT,
        "# PaymentStatus.REFUNDED: PaymentStatuses.REFUNDED,",
    ),
    Case(
        ".py",
        LITERAL_ATTR,
        PY_BLOCK,
        'if hasattr(self, "_listen_socket"):',
    ),
    Case(
        ".ts",
        COMMENTED,
        TS_STMT,
        "// const promotion_url = `${path}/api/promotion`;",
    ),
    Case(
        ".py",
        LITERAL_ATTR,
        PY_OR,
        'operation_name = getattr(operation, "__qualname__", None) '
        "or getattr(",
    ),
    Case(".c", COMMENTED, C_STMT, "//     if (ret < 0)"),
    Case(
        ".ts",
        COMMENTED,
        TS_STMT,
        "// const controller_url = `http://192.168.18.47:8000/pm01/v1/`;",
    ),
    Case(
        ".c",
        COMMENTED,
        C_STMT,
        "//(void)get_motor_connection(dev, &motor);",
    ),
    Case(
        ".c",
        COMMENTED,
        C_STMT,
        "//\t\tif (timestamp_is_timestamp_older_than("
        "is_alive_timestamp, 5 * 1000))",
    ),
    Case(
        ".tsx",
        COMMENTED,
        TS_STMT,
        "// <IdleTimerProvider timeout={clientTimeoutIdle} onIdle={onIdle}>",
    ),
    Case(
        ".tsx",
        COMMENTED,
        TS_STMT,
        "// const response2 = await api.editPermissionRoles("
        "user_id, updatedPermissions, token);",
    ),
]

RUFF_SOURCE = (
    """\
import os, sys


class my_class:
    camelCase = 1


mixedCase = 2


def Run(Flag, items=[]):
    if Flag == None:
        pass
    if Flag == True:
        pass
    try:
        risky()
    except:
        pass
    try:
        risky()
    except Exception:
        return None
    try:
        risky()
    except ValueError:
        pass
    for item in items:
        try:
            risky()
        except KeyError:
            continue
    MyVar = 5
"""
    "    \x23 compute(item, 3)\n    return None\n"
)
EXPECTED_RUFF_RULES = {
    "ERA001",
    "BLE001",
    "E722",
    "S110",
    "S112",
    "B006",
    "E711",
    "E712",
    "N801",
    "N802",
    "N803",
    "N806",
    "N815",
    "N816",
    "F841",
}
LONG_LINE = "VALUE_NAME_FOR_LENGTH = '" + "x" * 120 + "'\n"
CLONE_BLOCK = """\
function summarize(values, weights, offset) {
  let total = offset;
  let count = values.length;
  for (let i = 0; i < count; i++) {
    total += values[i] * weights[i] + offset;
    if (total > weights[i]) {
      total -= values[i];
    }
  }
  const average = total / count;
  const label = String(average) + ":" + String(total);
  return { average, label, total, count };
}
"""
UNRELATED_BLOCK = """\
function greet(person) {
  const message = "hello " + person.name;
  console.log(message);
  return message;
}
"""
CLONE_LABEL_PREFIX = "zduplikowany kod — jak w src/first.js:"


class Report(NamedTuple):
    findings: list[dict[str, Any]]
    not_checked: list[str]


def git(repo: Path, *args: str) -> str:
    done = subprocess.run(
        [
            "git",
            "-C",
            str(repo),
            "-c",
            "user.name=tester",
            "-c",
            "user.email=tester@example.com",
            "-c",
            "commit.gpgsign=false",
            *args,
        ],
        check=True,
        capture_output=True,
        text=True,
    )
    return done.stdout.strip()


def write_files(repo: Path, files: dict[str, str | bytes | None]) -> None:
    for name, content in files.items():
        target = repo / name
        if content is None:
            target.unlink()
            continue
        target.parent.mkdir(parents=True, exist_ok=True)
        data = content if isinstance(content, bytes) else content.encode()
        target.write_bytes(data)


@dataclass
class RepoOptions:
    moves: dict[str, str] = field(default_factory=dict)
    config: dict[str, str] = field(default_factory=dict)
    gitlinks: list[str] = field(default_factory=list)


def make_repo(
    tmp_path: Path,
    base_files: dict[str, str | bytes],
    pr_files: dict[str, str | bytes | None],
    options: RepoOptions | None = None,
) -> tuple[Path, str]:
    options = options or RepoOptions()
    repo = tmp_path / "repo"
    repo.mkdir()
    git(repo, "init", "-q", "-b", "main")
    git(repo, "config", "diff.renames", "false")
    for key, value in options.config.items():
        git(repo, "config", key, value)
    write_files(repo, {"README.md": "readme\n", **base_files})
    git(repo, "add", "-A")
    git(repo, "commit", "-q", "-m", "base")
    base = git(repo, "rev-parse", "HEAD")
    git(repo, "switch", "-q", "-c", "pr")
    for old, new in options.moves.items():
        (repo / new).parent.mkdir(parents=True, exist_ok=True)
        git(repo, "mv", old, new)
    write_files(repo, pr_files)
    git(repo, "add", "-A")
    for link in options.gitlinks:
        git(
            repo,
            "update-index",
            "--add",
            "--cacheinfo",
            f"160000,{base},{link}",
        )
    git(repo, "commit", "-q", "-m", "pr")
    return repo, base


def run_static(
    repo: Path, base: str, path: str | None = None
) -> subprocess.CompletedProcess[str]:
    env = {
        **os.environ,
        "HOME": str(repo.parent / "home"),
        "BB_SWEEP_CACHE_DIR": str(repo.parent / "cache"),
    }
    if path is not None:
        env["PATH"] = path
    return subprocess.run(
        [
            sys.executable,
            str(TOOL),
            "static",
            "--repo",
            str(repo),
            "--base",
            base,
            "--json",
        ],
        capture_output=True,
        text=True,
        env=env,
        check=False,
    )


def report_of(proc: subprocess.CompletedProcess[str]) -> Report:
    assert proc.returncode == 0, proc.stderr
    document = json.loads(proc.stdout)
    return Report(document["findings"], document["not_checked"])


def analyse(
    tmp_path: Path,
    base_files: dict[str, str | bytes],
    pr_files: dict[str, str | bytes | None],
) -> Report:
    repo, base = make_repo(tmp_path, base_files, pr_files)
    return report_of(run_static(repo, base))


def hits(report: Report, category: str) -> list[tuple[str, int]]:
    return [
        (item["path"], item["line"])
        for item in report.findings
        if item["category"] == category
    ]


def labels(report: Report, category: str) -> list[str]:
    return [
        item["label"]
        for item in report.findings
        if item["category"] == category
    ]


def line_of(source: str, code: str) -> int:
    lines = [text.strip() for text in source.split("\n")]
    return lines.index(code.strip()) + 1


def case_source(case: Case) -> str:
    return case.template.replace(PLACEHOLDER, case.code)


def case_id(case: Case) -> str:
    return f"{case.ext[1:]}-{case.category}-{case.code[:24]}"


def path_free_of_tools(tmp_path: Path) -> str:
    bin_dir = tmp_path / "bin-only-git"
    bin_dir.mkdir()
    git_path = shutil.which("git")
    assert git_path is not None
    (bin_dir / "git").symlink_to(git_path)
    return str(bin_dir)


@pytest.mark.parametrize("case", CASES, ids=case_id)
def test_case_code_on_added_line_is_reported(
    tmp_path: Path, case: Case
) -> None:
    source = case_source(case)
    name = f"src/sample{case.ext}"
    report = analyse(tmp_path, {}, {name: source})
    expected = (name, line_of(source, case.code))
    assert expected in hits(report, case.category)


@pytest.mark.parametrize("case", EXEMPT_CASES, ids=case_id)
def test_case_code_in_an_exempt_context_is_not_reported(
    tmp_path: Path, case: Case
) -> None:
    source = case_source(case)
    name = f"src/sample{case.ext}"
    report = analyse(tmp_path, {}, {name: source})
    assert hits(report, MAGIC) == []


@pytest.mark.parametrize("case", CASES, ids=case_id)
def test_case_code_on_context_line_is_not_reported(
    tmp_path: Path, case: Case
) -> None:
    source = case_source(case)
    name = f"src/sample{case.ext}"
    harmless = HARMLESS_LINES[case.ext]
    report = analyse(tmp_path, {name: source}, {name: source + harmless})
    assert report.findings == []


def test_numeric_string_for_the_model_is_not_a_static_finding(
    tmp_path: Path,
) -> None:
    source = TS_STMT.replace(
        PLACEHOLDER, 'const [expiryHours, setExpiryHours] = useState("24");'
    )
    report = analyse(tmp_path, {}, {"src/form.tsx": source})
    assert hits(report, MAGIC) == []


@pytest.mark.parametrize(
    ("name", "source"),
    [
        ("src/consts.py", "TIMEOUT_S = 37\nfirst = 37\nsecond = 37\n"),
        (
            "src/colors.py",
            (
                "from enum import Enum\n\n\nclass Color(Enum):\n"
                "    A = 37\n\n\nfirst = 37\nsecond = 37\n"
            ),
        ),
        (
            "src/consts.c",
            "#define MAX_RETRIES 37\nint first = 37;\nint second = 37;\n",
        ),
        (
            "src/consts.cpp",
            (
                "static const int kLimit = 37;\n"
                "int first = 37;\nint second = 37;\n"
            ),
        ),
        (
            "src/consts.ts",
            "const MAX_ITEMS = 37;\nlet first = 37;\nlet second = 37;\n",
        ),
        (
            "src/consts.ts",
            (
                "export const MAX_ITEMS: number = 37;\n"
                "let first = 37;\nlet second = 37;\n"
            ),
        ),
        (
            "src/state.h",
            (
                "enum State { IDLE = 37, BUSY = 38 };\n"
                "int first = 37;\nint second = 37;\n"
            ),
        ),
    ],
)
def test_constant_definitions_are_not_reported(
    tmp_path: Path, name: str, source: str
) -> None:
    report = analyse(tmp_path, {}, {name: source})
    assert hits(report, MAGIC) == []


ENUM_WITH_METHODS = (
    "from enum import Enum\n\n\nclass Color(Enum):\n    A = 37\n\n"
    "    def low(self) -> int:\n        return 37\n\n"
    "    def high(self) -> int:\n        return 37\n"
)


def test_enum_member_does_not_count_toward_repetition(
    tmp_path: Path,
) -> None:
    report = analyse(tmp_path, {}, {"src/colors.py": ENUM_WITH_METHODS})
    assert hits(report, MAGIC) == []


def test_enum_method_literals_are_counted(tmp_path: Path) -> None:
    source = (
        ENUM_WITH_METHODS.replace("    A = 37\n", "    A = 5\n")
        + "\n    def mid(self) -> int:\n        return 37\n"
    )
    report = analyse(tmp_path, {}, {"src/colors.py": source})
    assert hits(report, MAGIC) == [
        ("src/colors.py", 8),
        ("src/colors.py", 11),
        ("src/colors.py", 14),
    ]


def test_other_statement_on_a_constant_line_is_reported(
    tmp_path: Path,
) -> None:
    source = "const LIMIT = 37; if (x > 99) {}\n"
    report = analyse(tmp_path, {}, {"src/limit.ts": source})
    found = labels(report, MAGIC)
    assert len(found) == 1
    assert "99" in found[0]
    assert "37" not in found[0]


@pytest.mark.parametrize(
    ("name", "source"),
    [
        (
            "src/small.py",
            (
                "def pick(items: list[int]) -> int:\n"
                "    return items[0] == 0 or items[1] >= 1 or abs(-1) > -1\n"
            ),
        ),
        (
            "src/small.c",
            (
                "int pick(int *a) {\n"
                "    return a[0] > 0 && a[1] != -1 && a[2] < 1;\n}\n"
            ),
        ),
        ("src/small.ts", "const pick = (a) => a[0] === 0 || a[1] !== -1;\n"),
    ],
)
def test_zero_one_and_minus_one_are_never_magic(
    tmp_path: Path, name: str, source: str
) -> None:
    report = analyse(tmp_path, {}, {name: source})
    assert hits(report, MAGIC) == []


COMPARES_BY_SUFFIX = {
    ".py": "def run(x):\n    return x > 37\n",
    ".ts": "const ok = count === 37;\n",
    ".c": "int ok(int x) { return x > 37; }\n",
}


@pytest.mark.parametrize(
    "name",
    [
        "tests/helper.py",
        "pkg/test_values.py",
        "pkg/values_test.py",
        "web/values.test.ts",
        "web/values.spec.ts",
        "src/values_test.c",
    ],
)
def test_test_files_are_excluded_from_magic_numbers(
    tmp_path: Path, name: str
) -> None:
    source = COMPARES_BY_SUFFIX[Path(name).suffix]
    report = analyse(tmp_path, {}, {name: source})
    assert hits(report, MAGIC) == []


def test_test_files_report_nothing_at_all(tmp_path: Path) -> None:
    source = (
        'def check(obj, items=[]):\n    return getattr(obj, "name")\n'
        "\x23 value = compute(5)\n"
    )
    report = analyse(tmp_path, {}, {"tests/test_obj.py": source})
    assert report.findings == []


def test_test_file_clones_are_not_reported(tmp_path: Path) -> None:
    report = analyse(
        tmp_path,
        {"tests/first.js": CLONE_BLOCK},
        {"tests/second.js": CLONE_BLOCK},
    )
    assert hits(report, DUPLICATION) == []


def test_missing_annotations_are_never_candidates(tmp_path: Path) -> None:
    source = "def run(data):\n    return data\n"
    report = analyse(tmp_path, {}, {"src/plain.py": source})
    assert "missing-annotation" not in {
        item["category"] for item in report.findings
    }


@pytest.mark.parametrize(
    "name",
    [
        "node_modules/pkg/index.ts",
        "dist/bundle.ts",
        "build/out.ts",
        "vendor/lib.ts",
        "app/migrations/0001_initial.py",
        "app/service_pb2.py",
        "web/app.min.js",
    ],
)
def test_generated_and_vendored_paths_are_skipped(
    tmp_path: Path, name: str
) -> None:
    source = (
        "if answer > 42:\n    pass\n"
        if name.endswith(".py")
        else "if (a > 42) {}\n"
    )
    report = analyse(tmp_path, {}, {name: source})
    assert report.findings == []


def test_template_literal_interpolation_is_code(tmp_path: Path) -> None:
    source = "const style = `${index > 37 ? 1 : 0}s`;\n"
    report = analyse(tmp_path, {}, {"src/anim.ts": source})
    found = labels(report, MAGIC)
    assert len(found) == 1
    assert "37" in found[0]


def test_numbers_in_strings_and_comments_are_not_reported(
    tmp_path: Path,
) -> None:
    source = (
        'const a = "value 42";\n'
        "// 43 items remain\n"
        "const b = `abc 44`;\n"
        "/* 45 and 46 */\n"
    )
    report = analyse(tmp_path, {}, {"src/text.ts": source})
    assert hits(report, MAGIC) == []


def test_getattr_family_with_literal_name_is_reported(
    tmp_path: Path,
) -> None:
    source = (
        "def run(obj):\n"
        "    a = getattr(obj, 'x')\n"
        "    b = getattr(obj, 'y', None)\n"
        "    setattr(obj, 'z', a)\n"
        "    c = hasattr(obj, 'w')\n"
        "    delattr(obj, 'v')\n"
        "    return b, c\n"
    )
    report = analyse(tmp_path, {}, {"src/attrs.py": source})
    expected = [("src/attrs.py", number) for number in (2, 3, 4, 5, 6)]
    assert hits(report, LITERAL_ATTR) == expected


def test_getattr_with_non_literal_name_is_not_reported(
    tmp_path: Path,
) -> None:
    source = "def run(obj, name):\n    return getattr(obj, name)\n"
    report = analyse(tmp_path, {}, {"src/attrs.py": source})
    assert hits(report, LITERAL_ATTR) == []


def test_ruff_set_reports_every_curated_rule(tmp_path: Path) -> None:
    report = analyse(tmp_path, {}, {"src/sloppy.py": RUFF_SOURCE})
    found = {item["rule"] for item in report.findings}
    assert found >= EXPECTED_RUFF_RULES


def test_ruff_reports_typed_except_pass(tmp_path: Path) -> None:
    source = (
        "def run() -> None:\n"
        "    try:\n"
        "        risky()\n"
        "    except ValueError:\n"
        "        pass\n"
    )
    report = analyse(tmp_path, {}, {"src/typed.py": source})
    assert "S110" in {item["rule"] for item in report.findings}


def test_ruff_ignores_noqa_comments(tmp_path: Path) -> None:
    source = (
        "def run() -> None:\n"
        "    \x23 x = compute(5)  \x23 noqa: ERA001\n"
        "    return None\n"
    )
    report = analyse(tmp_path, {}, {"src/noqa.py": source})
    assert hits(report, COMMENTED) == [("src/noqa.py", 2)]


def test_no_formatting_rule_ever_appears(tmp_path: Path) -> None:
    source = "import sys,os\n" + LONG_LINE + "def f( a ):\n  return a\n"
    report = analyse(tmp_path, {}, {"src/ugly.py": source})
    rules = [item["rule"] for item in report.findings]
    assert not [rule for rule in rules if rule.startswith(FORMATTING_PREFIXES)]


@pytest.mark.parametrize(
    "header", ["} catch (e) { }", "} catch { }", "} catch (e) { /* skip */ }"]
)
def test_empty_catch_is_reported(tmp_path: Path, header: str) -> None:
    source = f"function run() {{\n  try {{\n    go();\n  {header}\n}}\n"
    report = analyse(tmp_path, {}, {"src/catch.ts": source})
    assert hits(report, EMPTY_CATCH) == [("src/catch.ts", 4)]


def test_non_empty_catch_is_not_reported(tmp_path: Path) -> None:
    source = (
        "function run() {\n  try {\n    go();\n  } catch (e) {\n"
        "    handle(e);\n  }\n}\n"
    )
    report = analyse(tmp_path, {}, {"src/catch.ts": source})
    assert hits(report, EMPTY_CATCH) == []


@pytest.mark.skipif(shutil.which("jscpd") is None, reason="jscpd missing")
def test_clone_overlapping_added_lines_names_the_other_fragment(
    tmp_path: Path,
) -> None:
    report = analyse(
        tmp_path,
        {"src/first.js": CLONE_BLOCK},
        {"src/second.js": CLONE_BLOCK},
    )
    clones = [
        item for item in report.findings if item["category"] == DUPLICATION
    ]
    assert [item["path"] for item in clones] == ["src/second.js"]
    assert clones[0]["label"].startswith(CLONE_LABEL_PREFIX)


def test_clone_not_overlapping_added_lines_is_not_reported(
    tmp_path: Path,
) -> None:
    report = analyse(
        tmp_path,
        {"src/first.js": CLONE_BLOCK, "src/second.js": CLONE_BLOCK},
        {"src/second.js": CLONE_BLOCK + UNRELATED_BLOCK},
    )
    assert hits(report, DUPLICATION) == []


def test_pure_rename_yields_no_findings(tmp_path: Path) -> None:
    source = "answer = 42\n\n\ndef run(obj):\n    return getattr(obj, 'a')\n"
    repo, base = make_repo(
        tmp_path,
        {"src/old.py": source},
        {},
        options=RepoOptions(moves={"src/old.py": "src/new.py"}),
    )
    assert report_of(run_static(repo, base)).findings == []


def test_missing_ruff_and_jscpd_are_listed_not_checked(
    tmp_path: Path,
) -> None:
    repo, base = make_repo(
        tmp_path,
        {},
        {
            "src/a.py": "a = 42\nb = 42\nc = 42\n",
            "src/b.ts": "if (a > 42) {}\n",
        },
    )
    path = path_free_of_tools(tmp_path)
    report = report_of(run_static(repo, base, path))
    assert any("ruff" in entry for entry in report.not_checked)
    assert any("jscpd" in entry for entry in report.not_checked)
    assert len(hits(report, MAGIC)) == 4


def test_unparseable_python_has_no_hits(tmp_path: Path) -> None:
    source = "def broken(:\n    a = 37\n    b = 37\n    c = 37\n"
    report = analyse(tmp_path, {}, {"src/bad.py": source})
    assert report.findings == []


def test_python_syntax_error_is_skipped_and_listed(tmp_path: Path) -> None:
    report = analyse(
        tmp_path,
        {},
        {"src/bad.py": "def broken(:\n    answer = 42\n"},
    )
    assert any("src/bad.py" in entry for entry in report.not_checked)
    assert report.findings == []


def test_deleted_and_binary_files_are_ignored(tmp_path: Path) -> None:
    binary = b"\x00\xff\x01" * 50
    report = analyse(
        tmp_path,
        {"src/gone.py": "answer = 42\n"},
        {"src/gone.py": None, "src/blob.c": binary, "img/pic.png": binary},
    )
    assert report.findings == []


def test_unresolvable_base_exits_with_usage_status(tmp_path: Path) -> None:
    repo, _ = make_repo(tmp_path, {}, {"src/a.py": "x = 1\n"})
    proc = run_static(repo, "no-such-ref")
    assert proc.returncode == USAGE_EXIT
    assert "no-such-ref" in proc.stderr


def load_module() -> ModuleType:
    loader = importlib.machinery.SourceFileLoader(MODULE_NAME, str(TOOL))
    spec = importlib.util.spec_from_loader(MODULE_NAME, loader)
    assert spec is not None
    module = importlib.util.module_from_spec(spec)
    sys.modules[MODULE_NAME] = module
    loader.exec_module(module)
    return module


bb = load_module()
NATIVE = "NATIVE"
SCRIPT = "SCRIPT"


ALL_LINES = frozenset(range(1, 100))


def magic_texts(text: str, name: str) -> list[str]:
    language = bb.StaticLanguage[name]
    tokens = bb.tokenize_source(text, language)
    code = [t for t in tokens if t.kind is not bb.TokenKind.COMMENT]
    hits_ = magic_numbers.token_magic_hits(code, language, ALL_LINES)
    return [value for hit in hits_ for value in hit.values]


def comment_hit_lines(text: str, added: set[int]) -> list[int]:
    tokens = bb.tokenize_source(text, bb.StaticLanguage.NATIVE)
    hits = bb.commented_code_hits(tokens, frozenset(added))
    return [hit.line for hit in hits]


@pytest.mark.parametrize(
    ("text", "expected"),
    [
        ("x > 10U;", ["10U"]),
        ("x > 1e3;", ["1e3"]),
        ("x > 0x48;", ["0x48"]),
        ("x > 0x1F;", ["0x1F"]),
        ("x > 0b101;", ["0b101"]),
        ("x > 1'000;", ["1'000"]),
        ("x > 2.5f;", ["2.5f"]),
        ("x > 0;", []),
        ("x > 1;", []),
        ("x > 1.0;", []),
        ("x > 0x0;", []),
        ("x > 0x01;", []),
        ("x > 1U;", []),
        ("x > 0u;", []),
        ("x > -1;", []),
        ("x > -5;", ["-5"]),
        ("x = a[2] + a[0];", []),
    ],
)
def test_native_numeric_literal_forms(text: str, expected: list[str]) -> None:
    assert magic_texts(text, NATIVE) == expected


def test_script_numeric_separator_is_one_literal() -> None:
    assert magic_texts("if (x > 1_000) {}", SCRIPT) == ["1_000"]


def test_nested_template_literals_expose_every_interpolation() -> None:
    text = "const s = `a ${b > `c ${d > 7 ? 1 : 0}`} ${x > 9 ? 1 : 0}`;"
    assert magic_texts(text, SCRIPT) == ["7", "9"]


def test_block_comment_spanning_lines_hides_numbers() -> None:
    tokens = bb.tokenize_source(
        "/* a\n 42\n */ x = 5;", bb.StaticLanguage.NATIVE
    )
    numbers = [t for t in tokens if t.kind is bb.TokenKind.NUMBER]
    assert [(t.text, t.line) for t in numbers] == [("5", 3)]


def test_block_comment_lines_are_judged_one_by_one() -> None:
    text = "/*\n * if (x) {\n * plain words\n */\n"
    assert comment_hit_lines(text, {2, 3}) == [2]


def test_double_slash_inside_a_string_is_not_a_comment() -> None:
    text = 'const u = "http://x.test"; if (u > 7) {}'
    tokens = bb.tokenize_source(text, bb.StaticLanguage.SCRIPT)
    assert not [t for t in tokens if t.kind is bb.TokenKind.COMMENT]
    assert magic_texts(text, SCRIPT) == ["7"]


def test_regex_literal_with_a_quote_does_not_open_a_string() -> None:
    text = 'const r = /"/.test(s); if (s > 8) {}'
    assert magic_texts(text, SCRIPT) == ["8"]


def test_division_is_not_mistaken_for_a_regex() -> None:
    text = "const q = a / 37 / b;\n" * 3
    assert magic_texts(text, SCRIPT) == ["37", "37", "37"]


def test_cpp_raw_string_hides_its_content() -> None:
    text = 'auto s = R"(42 "quoted")"; if (s > 6) {}'
    assert magic_texts(text, NATIVE) == ["6"]


def test_quote_char_literal_does_not_open_a_string() -> None:
    assert magic_texts("char c = '\"'; if (c > 5) {}", NATIVE) == ["5"]


def test_unterminated_string_stops_at_the_line_end() -> None:
    assert magic_texts('const a = "abc\nif (a > 4) {}', SCRIPT) == ["4"]


def test_object_like_define_body_is_a_constant_definition() -> None:
    assert magic_texts("#define LIMIT \\\n  37\n", NATIVE) == []


def test_function_like_define_body_is_a_constant_definition() -> None:
    text = "#define ABOVE(x) \\\n  ((x) > 9)\n"
    assert magic_texts(text, NATIVE) == []


def test_other_directives_are_ignored() -> None:
    assert (
        magic_texts("#if VERSION > 5\n#pragma pack(4)\n#endif\n", NATIVE) == []
    )


def test_javascript_asi_const_does_not_swallow_the_next_statement() -> None:
    text = "const MAX_ITEMS = 20\nif (x > 99) {}\n"
    assert magic_texts(text, SCRIPT) == ["99"]


def test_multiline_constant_initializer_is_excluded() -> None:
    text = "static const int kTotal =\n    37 > 5;\n"
    assert magic_texts(text, NATIVE) == []


def test_lowercase_const_is_not_a_constant_definition() -> None:
    assert magic_texts("const int total = x > 37;", NATIVE) == ["37"]


def test_const_function_parameter_does_not_start_a_definition() -> None:
    text = "void f(const char *p) { if (n > 3) {} }"
    assert magic_texts(text, NATIVE) == ["3"]


def python_hit_lines(source: str) -> list[tuple[int, tuple[str, ...]]]:
    hits_ = magic_numbers.python_magic_hits(
        ast.parse(source), ALL_LINES, source
    )
    return [(hit.line, hit.values) for hit in hits_]


def test_python_constant_assignments_are_excluded() -> None:
    source = (
        "x = 37\nTIMEOUT = 37\n__version__ = 37\nLIMIT: int = 37\n"
        "class C:\n    LIMIT = 37\n    other = 37\ny = 37\n"
    )
    assert python_hit_lines(source) == [
        (1, ("37",)),
        (7, ("37",)),
        (8, ("37",)),
    ]


def test_python_upper_assignment_inside_function_is_a_constant() -> None:
    source = "def f():\n    LIMIT = 37\n    a = 37\n    b = 37\n"
    assert python_hit_lines(source) == []


def test_python_bool_complex_and_obvious_values_never_repeat() -> None:
    source = "".join(
        f"{name} = {value}\n"
        for name in "abc"
        for value in ("True", "2j", "0", "1.0", "-1")
    )
    assert python_hit_lines(source) == []


def test_python_numbers_in_fstrings_are_counted() -> None:
    source = 'a = f"{x * 37}"\nb = f"{x * 37}"\nc = f"{x * 37}"\n'
    assert python_hit_lines(source) == [
        (1, ("37",)),
        (2, ("37",)),
        (3, ("37",)),
    ]


@pytest.mark.parametrize(
    ("source", "expected"),
    [
        ("class A(Enum):\n    pass\n", True),
        ("class A(enum.IntEnum):\n    pass\n", True),
        ("class A(MyEnum):\n    pass\n", True),
        ("class A(Base):\n    pass\n", False),
    ],
)
def test_enum_class_detection(source: str, expected: bool) -> None:
    node = ast.parse(source).body[0]
    assert isinstance(node, ast.ClassDef)
    assert magic_numbers.is_enum_class(node) is expected


@pytest.mark.parametrize(
    ("text", "expected"),
    [
        ("10U", 10),
        ("0x48", 72),
        ("0x1F", 31),
        ("0xFFul", 255),
        ("0b11", 3),
        ("1'000", 1000),
        ("1e3", 1000.0),
        ("2.5f", 2.5),
        ("0x1.8p3", None),
    ],
)
def test_literal_key_of_numeric_forms(
    text: str, expected: float | None
) -> None:
    assert magic_numbers.literal_key(text) == expected


@pytest.mark.parametrize(
    "text",
    [
        "foo(bar)",
        "x = 5",
        "} else {",
        "const a = 1",
        "}",
        "if (ready)",
        "<Provider timeout={t}>",
        "#include <stdio.h>",
    ],
)
def test_comment_text_that_looks_like_code(text: str) -> None:
    assert bb.looks_like_code(text) is True


@pytest.mark.parametrize(
    "text",
    [
        "",
        "TODO: fix this",
        "this is the retry limit",
        "if you want to change it",
        "return the value to the caller",
        "see https://example.test/docs",
        "eslint-disable-next-line",
        "x == y is checked first",
    ],
)
def test_comment_text_that_is_prose(text: str) -> None:
    assert bb.looks_like_code(text) is False


def test_patch_parser_reads_new_side_lines_per_file() -> None:
    patch = (
        "diff --git a/x.py b/x.py\n--- a/x.py\n+++ b/x.py\n"
        "@@ -3,0 +4,2 @@\n+one\n+two\n"
        "@@ -9,2 +12,0 @@\n-gone\n-gone too\n"
        "@@ -20 +21 @@\n-old\n+new\n"
    )
    assert bb.parse_added_lines(patch) == {"x.py": frozenset({4, 5, 21})}


def test_patch_parser_does_not_take_content_for_a_file_header() -> None:
    patch = (
        "diff --git a/x.py b/x.py\n--- a/x.py\n+++ b/x.py\n"
        "@@ -1,0 +2,2 @@\n+++ b/fake.py\n+two\n"
    )
    assert bb.parse_added_lines(patch) == {"x.py": frozenset({2, 3})}


def test_patch_parser_ignores_deleted_and_binary_files() -> None:
    patch = (
        "diff --git a/gone.py b/gone.py\ndeleted file mode 100644\n"
        "--- a/gone.py\n+++ /dev/null\n@@ -1 +0,0 @@\n-x\n"
        "diff --git a/img.png b/img.png\nBinary files differ\n"
    )
    assert bb.parse_added_lines(patch) == {}


@pytest.mark.parametrize(
    ("path", "expected"),
    [
        ("tests/a.py", True),
        ("src/test_a.py", True),
        ("src/a_test.go", True),
        ("web/a.spec.ts", True),
        ("src/latest.py", False),
        ("src/contest.py", False),
    ],
)
def test_test_file_detection(path: str, expected: bool) -> None:
    assert bb.static_is_test(path) is expected


@pytest.mark.parametrize(
    ("path", "expected"),
    [
        ("node_modules/a/b.js", True),
        ("src/migrations/0001.py", True),
        ("a/b_pb2.py", True),
        ("a/b.min.js", True),
        ("src/build_tools.py", False),
        ("src/vendors.py", False),
    ],
)
def test_skipped_path_detection(path: str, expected: bool) -> None:
    assert bb.static_is_skipped(path) is expected


def test_crlf_file_keeps_git_line_numbers(tmp_path: Path) -> None:
    source = "void run(void) {\r\n    if (n > 200) {}\r\n}\r\n"
    report = analyse(tmp_path, {}, {"src/crlf.c": source})
    assert hits(report, MAGIC) == [("src/crlf.c", 2)]


def test_non_utf8_bytes_do_not_break_the_scan(tmp_path: Path) -> None:
    source = (
        b"void run(void) {\n    /* \xff\xfe */\n\n    if (n > 200) {}\n}\n"
    )
    report = analyse(tmp_path, {}, {"src/latin.c": source})
    assert hits(report, MAGIC) == [("src/latin.c", 4)]


def test_non_utf8_python_file_is_still_analysed(tmp_path: Path) -> None:
    source = b"NAME = '\xff'\nif value > 42:\n    pass\n"
    report = analyse(tmp_path, {}, {"src/latin.py": source})
    assert hits(report, MAGIC) == [("src/latin.py", 2)]


def test_static_text_output_has_one_line_per_finding(
    tmp_path: Path,
) -> None:
    repo, base = make_repo(tmp_path, {}, {"src/a.c": "int a = x > 42;\n"})
    env = {**os.environ, "HOME": str(tmp_path / "home")}
    done = subprocess.run(
        [
            sys.executable,
            str(TOOL),
            "static",
            "--repo",
            str(repo),
            "--base",
            base,
        ],
        capture_output=True,
        text=True,
        env=env,
        check=False,
    )
    assert done.returncode == 0
    assert done.stdout.splitlines()[0].startswith(
        "src/a.c:1 magic-number — magiczna liczba w porównaniu 42"
    )


def test_define_group_swallows_following_code_unit() -> None:
    text = "#define LIMIT 5\nif (x > 77) {}\n"
    assert magic_texts(text, NATIVE) == ["77"]


def test_define_group_swallows_following_code_integration(
    tmp_path: Path,
) -> None:
    source = (
        "#define MAX_RETRIES 5\nvoid run(void) {\n"
        "    if (retries > 77) {}\n}\n"
    )
    report = analyse(tmp_path, {}, {"src/io.c": source})
    assert hits(report, MAGIC) == [("src/io.c", 3)]


def test_unreadable_file_silently_dropped_unit(tmp_path: Path) -> None:
    repo, _ = make_repo(tmp_path, {}, {"src/a.c": "int a;\n"})
    sources, not_checked = bb.load_sources(
        repo, {"src/missing.c": frozenset({1})}
    )
    assert sources == []
    assert any("src/missing.c" in entry for entry in not_checked)


def test_unreadable_file_silently_dropped_integration(
    tmp_path: Path,
) -> None:
    repo, base = make_repo(tmp_path, {}, {}, RepoOptions(gitlinks=["sub.c"]))
    report = report_of(run_static(repo, base))
    assert any("sub.c" in entry for entry in report.not_checked)


HUNK_WITH_CONTEXT = (
    "diff --git a/x.c b/x.c\n--- a/x.c\n+++ b/x.c\n"
    "@@ -2,4 +2,4 @@\n kept\n-old\n+new\n kept too\n kept three\n"
    "@@ -9 +9 @@\n-old\n+newer\n"
    "diff --git a/y.c b/y.c\n--- a/y.c\n+++ b/y.c\n"
    "@@ -1 +1 @@\n-a\n+b\n"
)


def test_hunk_context_lines_marked_added_unit() -> None:
    assert bb.parse_added_lines(HUNK_WITH_CONTEXT) == {
        "x.c": frozenset({3, 9}),
        "y.c": frozenset({1}),
    }


def test_hunk_context_lines_marked_added_integration(
    tmp_path: Path,
) -> None:
    lines = [f"int v{number} = 0;" for number in range(1, 13)]
    base_lines = [*lines]
    base_lines[5] = "int kept = x > 42;"
    pr_lines = [*base_lines]
    pr_lines[1] = "int v2 = 0; /* edited */"
    pr_lines[9] = "int v10 = 0; /* edited */"
    report = analyse_with(
        tmp_path,
        {"src/a.c": "\n".join(base_lines) + "\n"},
        {"src/a.c": "\n".join(pr_lines) + "\n"},
        {"diff.interHunkContext": "10"},
    )
    assert hits(report, MAGIC) == []


def analyse_with(
    tmp_path: Path,
    base_files: dict[str, str | bytes],
    pr_files: dict[str, str | bytes | None],
    config: dict[str, str],
) -> Report:
    repo, base = make_repo(
        tmp_path, base_files, pr_files, RepoOptions(config=config)
    )
    return report_of(run_static(repo, base))


@pytest.mark.parametrize(
    ("header", "expected"),
    [
        ('+++ "b/src/a\\tb.c"', "src/a\tb.c"),
        ('+++ "b/src/\\305\\202.c"', "src/\u0142.c"),
        ('+++ "b/src/q\\"x.c"', 'src/q"x.c'),
        ("+++ b/src/plain.c", "src/plain.c"),
        ("+++ /dev/null", None),
    ],
)
def test_quoted_path_dropped_unit(header: str, expected: str | None) -> None:
    assert bb.new_side_path(header) == expected


def test_quoted_path_dropped_integration(tmp_path: Path) -> None:
    name = "src/a\tb.c"
    report = analyse(tmp_path, {}, {name: "int a = x > 42;\n"})
    assert hits(report, MAGIC) == [(name, 1)]


def test_worktree_text_vs_head_lines_unit(tmp_path: Path) -> None:
    repo, _ = make_repo(tmp_path, {}, {"src/a.c": "int a = x > 42;\n"})
    (repo / "src/a.c").write_text("\n\n\nlocal edit\nint a = x > 42;\n")
    sources, not_checked = bb.load_sources(repo, {"src/a.c": frozenset({1})})
    assert not_checked == []
    assert sources[0].text == "int a = x > 42;\n"


def test_worktree_text_vs_head_lines_integration(tmp_path: Path) -> None:
    repo, base = make_repo(tmp_path, {}, {"src/a.c": "int a = x > 42;\n"})
    (repo / "src/a.c").write_text("\n\n\nint a = x > 42;\n")
    report = report_of(run_static(repo, base))
    assert hits(report, MAGIC) == [("src/a.c", 1)]


COMMENT_BLOCK_TS = (
    "const a = 1;\n"
    "// const path = 'https://x.test';\n"
    "// const first_url = `${path}/api/first`;\n"
    "// const second_url = `${path}/api/second`;\n"
)


def test_commented_template_literal_missed_unit() -> None:
    found = bb.commented_code_hits(
        bb.tokenize_source(COMMENT_BLOCK_TS, bb.StaticLanguage.SCRIPT),
        frozenset({2, 3, 4}),
    )
    assert [hit.line for hit in found] == [2, 3, 4]


def test_commented_template_literal_missed_integration(
    tmp_path: Path,
) -> None:
    report = analyse(tmp_path, {}, {"src/API.ts": COMMENT_BLOCK_TS})
    assert hits(report, COMMENTED) == [
        ("src/API.ts", 2),
        ("src/API.ts", 3),
        ("src/API.ts", 4),
    ]


def test_commented_block_of_bare_if_unit() -> None:
    hit = bb.StaticHit(
        5, bb.StaticCategory.COMMENTED_CODE, "zakomentowany kod", "r"
    )
    follower = bb.StaticHit(
        6, bb.StaticCategory.COMMENTED_CODE, "zakomentowany kod", "r"
    )
    source = bb.StaticSource(
        "a.c",
        bb.StaticLanguage.NATIVE,
        frozenset({5, 6}),
        "\n" * 4 + "//     if (ret < 0)\n//         return ret;\n",
    )
    found = bb.build_findings({"a.c": source}, {"a.c": [hit, follower]})
    assert [item.line for item in found] == [5, 6]


def test_commented_block_of_bare_if_integration(tmp_path: Path) -> None:
    source = (
        "int run(void) {\n"
        "//     if (ret < 0)\n"
        "//     if (ret > 3)\n"
        "    return 0;\n}\n"
    )
    report = analyse(tmp_path, {}, {"src/h.c": source})
    assert hits(report, COMMENTED) == [("src/h.c", 2), ("src/h.c", 3)]


MULTILINE_ATTR_SOURCE = (
    "def run(obj):\n"
    "    return getattr(\n"
    "        obj,\n"
    '        "name",\n'
    "        None,\n"
    "    )\n"
)


def test_literal_attr_multiline_call_start_line_unit() -> None:
    found = bb.literal_attr_hits(ast.parse(MULTILINE_ATTR_SOURCE))
    assert [hit.line for hit in found] == [4]


def test_literal_attr_multiline_call_start_line_integration(
    tmp_path: Path,
) -> None:
    edited = MULTILINE_ATTR_SOURCE.replace('"name"', '"title"')
    report = analyse(
        tmp_path,
        {"src/a.py": MULTILINE_ATTR_SOURCE},
        {"src/a.py": edited},
    )
    assert hits(report, LITERAL_ATTR) == [("src/a.py", 4)]


JSX_APOSTROPHE_SOURCE = (
    "const view = () => (\n  <p>Don't retry</p>\n);\nif (n > 5) {}\n"
)


def test_jsx_apostrophe_swallows_code_unit() -> None:
    assert magic_texts(JSX_APOSTROPHE_SOURCE, SCRIPT) == ["5"]


def test_jsx_apostrophe_swallows_code_integration(tmp_path: Path) -> None:
    report = analyse(tmp_path, {}, {"src/view.tsx": JSX_APOSTROPHE_SOURCE})
    assert hits(report, MAGIC) == [("src/view.tsx", 4)]


HUGE_HEX = "0x" + "F" * 300
HUGE_BINARY = "0b" + "1" * 1100


def test_bigint_hex_overflow_crash_unit() -> None:
    assert magic_numbers.literal_key(HUGE_HEX) is not None
    assert magic_numbers.literal_key(HUGE_BINARY) is not None
    assert magic_numbers.literal_key("0x1n") == 1


def test_bigint_hex_overflow_crash_integration(tmp_path: Path) -> None:
    source = f"if (m > {HUGE_HEX}n) {{}}\nif (b > {HUGE_BINARY}) {{}}\n"
    report = analyse(tmp_path, {}, {"src/big.ts": source})
    assert hits(report, MAGIC) == [("src/big.ts", 1), ("src/big.ts", 2)]


EXEMPT_C_SOURCE = (
    "void run(int h, int v, int zl) {\n"
    "    delay(DEBOUNCE_MS);\n"
    "    lv_obj_set_size(o, 26, 26);\n"
    "    x = buf[12];\n"
    "    y = v >> 4;\n"
    "    secs = h * 3600;\n"
    "    cents = zl * 100;\n"
    "}\n"
)
REPEATED_LINES = [
    "int first(void) { return 37; }",
    "int second(void) { return 37; }",
    "int third(void) { return 37; }",
]


def test_acceptance_exempt_contexts_are_not_magic(tmp_path: Path) -> None:
    report = analyse(tmp_path, {}, {"src/a.cpp": EXEMPT_C_SOURCE})
    assert hits(report, MAGIC) == []


@pytest.mark.parametrize(
    ("name", "source", "line"),
    [
        ("src/a.c", "void run(int t) {\n    if (temp > 37) {}\n}\n", 2),
        ("src/a.ts", "function run() {\n  if (count === 7) {}\n}\n", 2),
        ("src/a.py", "def run(x):\n    if x > 37:\n        pass\n", 2),
    ],
)
def test_acceptance_comparison_with_a_number_is_magic(
    tmp_path: Path, name: str, source: str, line: int
) -> None:
    report = analyse(tmp_path, {}, {name: source})
    assert hits(report, MAGIC) == [(name, line)]
    assert "w porównaniu" in labels(report, MAGIC)[0]


def test_acceptance_value_on_three_lines_is_reported_where_added(
    tmp_path: Path,
) -> None:
    base = "\n".join(REPEATED_LINES[:2]) + "\n"
    report = analyse(
        tmp_path, {"src/r.c": base}, {"src/r.c": "\n".join(REPEATED_LINES)}
    )
    assert hits(report, MAGIC) == [("src/r.c", 3)]
    assert labels(report, MAGIC) == ["powtórzona magiczna liczba 37"]


def test_acceptance_value_on_two_lines_is_not_reported(
    tmp_path: Path,
) -> None:
    source = "\n".join(REPEATED_LINES[:2]) + "\n"
    report = analyse(tmp_path, {}, {"src/r.c": source})
    assert hits(report, MAGIC) == []


DELAY_LABEL = "opóźnienie bez stałej ani komentarza"
C_DELAY = "void run(void) {{\n    {}\n}}\n"
PY_DELAY = "import time\n\n\ndef run() -> None:\n    {}\n"
TS_DELAY = "function run() {{\n  {}\n}}\n"


@pytest.mark.parametrize(
    ("name", "source", "line", "value"),
    [
        ("src/a.cpp", C_DELAY.format("delay(200);"), 2, "200"),
        ("src/a.c", C_DELAY.format("k_sleep(K_MSEC(10));"), 2, "10"),
        ("src/a.ts", TS_DELAY.format("setTimeout(fn, 500);"), 2, "500"),
        ("src/a.py", PY_DELAY.format("time.sleep(5)"), 5, "5"),
        ("src/b.c", C_DELAY.format("sleep(5 * 60);"), 2, "5"),
    ],
)
def test_acceptance_delay_literal_is_magic(
    tmp_path: Path, name: str, source: str, line: int, value: str
) -> None:
    report = analyse(tmp_path, {}, {name: source})
    assert hits(report, MAGIC) == [(name, line)]
    assert labels(report, MAGIC) == [f"{DELAY_LABEL} {value}"]


@pytest.mark.parametrize(
    "statement",
    [
        "delay(0);",
        "delay(DEBOUNCE_MS);",
        "delay(200); // debounce of the relay contact",
        "// relay needs 200 ms to settle\n    delay(200);",
    ],
)
def test_acceptance_named_or_explained_delay_is_not_magic(
    tmp_path: Path, statement: str
) -> None:
    source = C_DELAY.format(statement)
    report = analyse(tmp_path, {}, {"src/a.cpp": source})
    assert hits(report, MAGIC) == []


@pytest.mark.parametrize(
    ("name", "source"),
    [
        ("src/a.c", "int ok(int t) {\n    return t > 37; // fever limit\n}\n"),
        ("src/a.ts", "if (temp > 37) // 37 degrees is the fever limit\n{}\n"),
        ("src/a.py", "def run(x):\n    return x > 37  \x23 fever limit\n"),
    ],
)
def test_acceptance_commented_comparison_is_not_magic(
    tmp_path: Path, name: str, source: str
) -> None:
    report = analyse(tmp_path, {}, {name: source})
    assert hits(report, MAGIC) == []


def test_acceptance_comment_does_not_hide_repetition(tmp_path: Path) -> None:
    lines = [f"{line} // note" for line in REPEATED_LINES]
    report = analyse(tmp_path, {}, {"src/r.c": "\n".join(lines) + "\n"})
    assert hits(report, MAGIC) == [("src/r.c", n) for n in (1, 2, 3)]


@pytest.mark.parametrize(
    ("statement", "expected"),
    [
        ("setTimeout(() => { counter = 37; }, 500);", "500"),
        ("setTimeout(() => render(42), 250);", "250"),
        ("setTimeout(function () { counter = 37; }, 500);", "500"),
    ],
)
def test_delay_callback_body_is_not_a_delay_argument_integration(
    tmp_path: Path, statement: str, expected: str
) -> None:
    source = TS_DELAY.format(statement)
    report = analyse(tmp_path, {}, {"src/a.ts": source})
    assert labels(report, MAGIC) == [f"{DELAY_LABEL} {expected}"]


def test_clone_of_test_file_code_is_not_reported(tmp_path: Path) -> None:
    report = analyse(
        tmp_path,
        {"tests/first.js": CLONE_BLOCK},
        {"src/second.js": CLONE_BLOCK},
    )
    assert hits(report, DUPLICATION) == []


def test_clone_input_list_excludes_test_files_unit(tmp_path: Path) -> None:
    repo, _ = make_repo(
        tmp_path,
        {"tests/first.js": CLONE_BLOCK, "src/real.js": CLONE_BLOCK},
        {"notes.txt": "pr\n"},
    )
    assert bb.tracked_clone_files(repo) == ["src/real.js"]


PLR_MESSAGE = (
    "Magic value used in comparison, consider replacing `{}` "
    "with a constant variable"
)
COMPARISON_LABEL = "magiczna liczba w porównaniu"


def plr_record(value: str) -> dict[str, Any]:
    return {
        "code": "PLR2004",
        "filename": "a.py",
        "location": {"row": 3},
        "message": PLR_MESSAGE.format(value),
    }


def test_python_comparison_label_names_the_value_unit(
    tmp_path: Path,
) -> None:
    found = bb.ruff_records(tmp_path, [plr_record("42")], {})
    assert [hit.label for hit in found["a.py"]] == [f"{COMPARISON_LABEL} 42"]


def test_two_python_comparisons_on_one_line_merge_once_unit(
    tmp_path: Path,
) -> None:
    found = bb.ruff_records(tmp_path, [plr_record("42"), plr_record("7")], {})
    merged = bb.merge_magic_hits(found["a.py"])
    assert [hit.label for hit in merged] == [f"{COMPARISON_LABEL} 42, 7"]


def test_python_comparison_label_names_the_value(tmp_path: Path) -> None:
    source = "def f(v):\n    return v > 42\n"
    report = analyse(tmp_path, {}, {"src/one.py": source})
    assert labels(report, MAGIC) == [f"{COMPARISON_LABEL} 42"]


def test_two_python_comparisons_on_one_line_merge_once(
    tmp_path: Path,
) -> None:
    source = "def f(v):\n    return v > 42 or v < 7\n"
    report = analyse(tmp_path, {}, {"src/two.py": source})
    assert labels(report, MAGIC) == [f"{COMPARISON_LABEL} 42, 7"]


def test_parenthesised_negative_literal_keeps_its_sign_integration(
    tmp_path: Path,
) -> None:
    source = "int x = (-37);\nint y = -37;\nint z = -37;\n"
    report = analyse(tmp_path, {}, {"src/neg.c": source})
    assert hits(report, MAGIC) == [("src/neg.c", n) for n in (1, 2, 3)]


def test_c_octal_literal_key_integration(tmp_path: Path) -> None:
    source = "int a = 010;\nint b = 8;\nint c = 8;\n"
    report = analyse(tmp_path, {}, {"src/oct.c": source})
    assert hits(report, MAGIC) == [("src/oct.c", n) for n in (1, 2, 3)]


def test_jsx_text_number_is_not_a_comparison_integration(
    tmp_path: Path,
) -> None:
    source = (
        "export const view = <div>37</div>;\n"
        "export const wide = <div>{n > 37}</div>;\n"
    )

    report = analyse(tmp_path, {}, {"src/a.tsx": source})

    assert hits(report, MAGIC) == [("src/a.tsx", 2)]
