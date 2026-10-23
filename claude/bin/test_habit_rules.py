from __future__ import annotations

import ast

import pytest

from habit_rules import (
    HabitContext,
    HabitRule,
    line_count_hits,
    python_habit_hits,
)
from locale_habits import (
    LocaleDocument,
    locale_habit_hits,
    parse_locale,
    sibling_path,
)
from script_habits import script_habit_hits
from source_lexer import StaticLanguage, tokenize_source

EVERYWHERE = frozenset(range(1, 3000))
CLOUD = "acme/cloud-platform"
DEVICE = "acme/device-service"
PYDANTIC_MODEL = (
    "from pydantic import BaseModel\nclass M(BaseModel):\n    a: int\n"
)
SQL_HEADER = "from sqlalchemy.orm import Session\n\n\n"


def context(
    path: str = "app/mod.py",
    slug: str | None = None,
    env: frozenset[str] | None = None,
    *,
    repositories: bool = False,
    old: int | None = None,
) -> HabitContext:
    return HabitContext(path, slug, env, repositories, old)


def codes(
    text: str,
    ctx: HabitContext | None = None,
    changed: frozenset[int] = EVERYWHERE,
) -> list[str]:
    found = python_habit_hits(ast.parse(text), text, changed, ctx or context())
    return [hit.rule.value for hit in found]


@pytest.mark.parametrize(
    ("text", "expected"),
    [
        (
            "from enum import StrEnum\nclass C(StrEnum):\n    RED = 'red'\n",
            ["HAB120"],
        ),
        (
            "import enum\nclass C(enum.StrEnum):\n    RED: str = 'red'\n",
            ["HAB120"],
        ),
        (
            (
                "from enum import StrEnum, auto\nclass C(StrEnum):\n"
                "    RED = auto()\n"
            ),
            [],
        ),
        (
            "from enum import StrEnum\nclass C(StrEnum):\n    RED = 'r'\n",
            [],
        ),
        (
            "from enum import Enum\nclass C(Enum):\n    RED = 'red'\n",
            [],
        ),
    ],
)
def test_hab120_flags_only_plain_strenum_names(
    text: str, expected: list[str]
) -> None:
    assert codes(text) == expected


def test_strenum_value_differs_from_name_is_kept() -> None:
    text = "from enum import StrEnum\nclass C(StrEnum):\n    RED = 'Red'\n"

    assert codes(text) == []


def test_strenum_with_generate_next_value_is_kept() -> None:
    text = (
        "from enum import StrEnum\nclass C(StrEnum):\n"
        "    def _generate_next_value_(name, start, count, last):\n"
        "        return name\n"
        "    RED = 'red'\n"
    )

    assert codes(text) == []


@pytest.mark.parametrize(
    ("text", "expected"),
    [
        ("HTTP_NOT_FOUND = 404\n", ["HAB084"]),
        ("STATUS_OK = 200\n", ["HAB084"]),
        ("HTTP_CODE_X: int = 503\n", ["HAB084"]),
        ("HTTP_STATUS_DEFAULT = 200\n", ["HAB084"]),
        ("NOT_FOUND = 404\n", ["HAB084"]),
        ("STATUS_CACHE_SIZE = 100\n", []),
        ("MAX_STATUS_HISTORY = 200\n", []),
        ("RESPONSE_STATUS: int = 503\n", []),
        ("HTTP_OK = 200\n", ["HAB084"]),
        ("HTTP_OK = 404\n", []),
        ("HTTP_TIMEOUT = 300\n", []),
        ("RETRY_COUNT = 404\n", []),
        ("HTTP_STATUS_LABEL = 'ok'\n", []),
        ("STATUS_FLAG = True\n", []),
        ("STATUS_UNKNOWN = 799\n", []),
    ],
)
def test_hab084_flags_http_status_constants(
    text: str, expected: list[str]
) -> None:
    assert codes(text) == expected


def test_http_timeout_constant_is_not_hab084() -> None:
    assert codes("HTTP_TIMEOUT = 300\n") == []


def test_hab084_ignores_function_local_constants() -> None:
    assert codes("def f():\n    HTTP_NOT_FOUND = 404\n") == []


@pytest.mark.parametrize(
    ("text", "expected"),
    [
        (
            "class P(Base):\n    o: Mapped['U'] = relationship('U')\n",
            ["HAB091"],
        ),
        (
            "class P(Base):\n    o: Mapped[U] = orm.relationship('U')\n",
            ["HAB091"],
        ),
        (
            "class P(Base):\n    o: Mapped[U] = relationship(U)\n",
            [],
        ),
        (
            "class P(Base):\n    o: Mapped[U] = relationship(back_ref='a')\n",
            [],
        ),
        ("class P(Base):\n    o = relationship('U')\n", []),
    ],
)
def test_hab091_flags_string_relationship_target(
    text: str, expected: list[str]
) -> None:
    assert codes(text) == expected


TEST_CTX = context("tests/test_a.py")


@pytest.mark.parametrize(
    ("text", "expected"),
    [
        ("import os\nos.environ.setdefault('A', '1')\n", ["HAB051"]),
        ("from os import environ\nenviron.setdefault('A', '1')\n", ["HAB051"]),
        ("import os\nos.environ['A'] = '1'\n", []),
        ("d = {}\nd.setdefault('A', '1')\n", []),
    ],
)
def test_hab051_flags_environ_setdefault_in_tests(
    text: str, expected: list[str]
) -> None:
    assert codes(text, TEST_CTX) == expected


def test_hab051_ignores_production_files() -> None:
    text = "import os\nos.environ.setdefault('A', '1')\n"

    assert codes(text) == []


@pytest.mark.parametrize(
    ("text", "expected"),
    [
        ("with patch('time.sleep'):\n    pass\n", ["HAB106"]),
        ("with mock.patch('time.time'):\n    pass\n", ["HAB106"]),
        ("with patch.object(time, 'sleep'):\n    pass\n", ["HAB106"]),
        ("monkeypatch.setattr(time, 'sleep', f)\n", ["HAB106"]),
        ("monkeypatch.setattr('time.sleep', f)\n", ["HAB106"]),
        ("with patch('app.clock.sleep'):\n    pass\n", []),
        ("with patch('timezone.now'):\n    pass\n", []),
        ("with patch.object(clock, 'sleep'):\n    pass\n", []),
        ("monkeypatch.setattr(clock, 'sleep', f)\n", []),
    ],
)
def test_hab106_flags_global_time_patches_in_tests(
    text: str, expected: list[str]
) -> None:
    assert codes(text, TEST_CTX) == expected


@pytest.mark.parametrize(
    ("text", "expected"),
    [
        ("import subprocess\nsubprocess.run(['ls'])\n", ["HAB052"]),
        ("import subprocess\nsubprocess.check_output(['ls'])\n", ["HAB052"]),
        (
            "import subprocess\nsubprocess.call(['ls'], check=False)\n",
            ["HAB052"],
        ),
        ("import subprocess\nsubprocess.run(['ls'], timeout=5)\n", []),
        ("import subprocess\nsubprocess.Popen(['ls'])\n", []),
    ],
)
def test_hab052_flags_subprocess_without_timeout_in_tests(
    text: str, expected: list[str]
) -> None:
    assert codes(text, TEST_CTX) == expected


def test_subprocess_run_with_kwargs_expansion_is_not_hab052() -> None:
    text = "import subprocess\nsubprocess.run(cmd, **options)\n"

    assert codes(text, TEST_CTX) == []


SESSION_CASES = [
    (SQL_HEADER + "def f(session):\n    session.add(1)\n", ["HAB118"]),
    (
        SQL_HEADER + "def f(db_session):\n    db_session.execute(q)\n",
        ["HAB118"],
    ),
    (
        SQL_HEADER
        + "class A:\n    def f(self):\n        self.session.merge(1)\n",
        ["HAB118"],
    ),
    (
        "from sqlalchemy import select\n\n\ndef f():\n    return select(U)\n",
        ["HAB118"],
    ),
    (SQL_HEADER + "def f(session):\n    session.get(User, 1)\n", []),
    (SQL_HEADER + "def f(cache):\n    cache.add(1)\n", []),
    ("def f(session):\n    session.add(1)\n", []),
    ("def f():\n    return select(User)\n", []),
    ("from sqlalchemy import func\n\n\ndef f():\n    return select(1)\n", []),
]


@pytest.mark.parametrize(("text", "expected"), SESSION_CASES)
def test_hab118_flags_database_access_outside_repositories(
    text: str, expected: list[str]
) -> None:
    assert codes(text, context(repositories=True)) == expected


@pytest.mark.parametrize(
    "path",
    [
        "app/repositories/user.py",
        "app/migrations/0001.py",
        "alembic/versions/a.py",
        "tests/test_user.py",
    ],
)
def test_hab118_skips_allowed_locations(path: str) -> None:
    text = SQL_HEADER + "def f(session):\n    session.add(1)\n"

    assert codes(text, context(path, repositories=True)) == []


def test_hab118_needs_a_repositories_directory() -> None:
    text = SQL_HEADER + "def f(session):\n    session.add(1)\n"

    assert codes(text, context(repositories=False)) == []


def test_flask_session_get_is_not_hab118() -> None:
    text = (
        "from flask import session\nfrom sqlalchemy import select\n\n\n"
        "def f():\n    return session.get('user_id')\n"
    )

    assert codes(text, context(repositories=True)) == []


@pytest.mark.parametrize(
    ("path", "text", "slug", "expected"),
    [
        ("pkg/__init__.py", "__all__ = ['a']\n", None, ["HAB077"]),
        ("pkg/__init__.py", "from .a import b\n", None, ["HAB077"]),
        ("pkg/__init__.py", "import pkg.a\n", None, ["HAB077"]),
        ("pkg/__init__.py", "__version__ = '1'\n", None, []),
        ("pkg/__init__.py", "from .a import b\nVALUE = b\n", None, []),
        ("pkg/__init__.py", "from __future__ import annotations\n", None, []),
        ("pkg/mod.py", "__all__ = ['a']\n", None, []),
        ("libs/pkg/__init__.py", "__all__ = ['a']\n", None, []),
        ("pkg/__init__.py", "__all__ = ['a']\n", "acme/acme-common", []),
    ],
)
def test_hab077_flags_init_reexports(
    path: str, text: str, slug: str | None, expected: list[str]
) -> None:
    assert codes(text, context(path, slug)) == expected


def test_init_import_used_in_module_is_not_hab077() -> None:
    text = "from .a import build\n\n\ndef make():\n    return build()\n"

    assert codes(text, context("pkg/__init__.py")) == []


def test_lib_path_all_is_not_hab077() -> None:
    assert codes("__all__ = ['a']\n", context("libs/x/__init__.py")) == []


@pytest.mark.parametrize(
    ("path", "text", "expected"),
    [
        ("app/mod.py", "def f():\n    print('x')\n", ["HAB083"]),
        ("app/mod.py", "def f():\n    log.info('x')\n", []),
        ("app/mod.py", "#!/usr/bin/env python\nprint('x')\n", []),
        ("app/mod.py", "if __name__ == '__main__':\n    print('x')\n", []),
        ("app/__main__.py", "print('x')\n", []),
        ("app/cli.py", "print('x')\n", []),
        ("scripts/run.py", "print('x')\n", []),
        ("app/bin/run.py", "print('x')\n", []),
        ("tools/run.py", "print('x')\n", []),
        ("tests/test_a.py", "print('x')\n", []),
    ],
)
def test_hab083_flags_print_in_importable_modules(
    path: str, text: str, expected: list[str]
) -> None:
    assert codes(text, context(path)) == expected


def test_main_function_module_print_is_not_hab083() -> None:
    text = "def main():\n    print('x')\n"

    assert codes(text) == []


@pytest.mark.parametrize(
    ("text", "slug", "expected"),
    [
        ("from common.tests import h\n", CLOUD, ["HAB104"]),
        ("from libs.common.tests.utils import h\n", CLOUD, ["HAB104"]),
        ("import common.tests.utils\n", CLOUD, ["HAB104"]),
        ("from common import tests\n", CLOUD, ["HAB104"]),
        ("from common import helper\n", CLOUD, []),
        ("from common.testing import h\n", CLOUD, []),
        ("from common.tests import h\n", "acme/other", []),
        ("from common.tests import h\n", None, []),
    ],
)
def test_hab104_flags_common_tests_imports_in_acme_cloud(
    text: str, slug: str | None, expected: list[str]
) -> None:
    assert codes(text, context(slug=slug)) == expected


DATACLASS = (
    "from dataclasses import dataclass\n\n\n@dataclass\nclass S:\n    a: int\n"
)


@pytest.mark.parametrize(
    ("path", "text", "slug", "expected"),
    [
        ("app/services/s.py", DATACLASS, CLOUD, ["HAB102"]),
        (
            "app/services/s.py",
            DATACLASS.replace("@dataclass", "@dataclass(frozen=True)"),
            CLOUD,
            ["HAB102"],
        ),
        ("app/models/s.py", DATACLASS, CLOUD, []),
        ("app/services/deep/s.py", DATACLASS, CLOUD, []),
        ("app/services/s.py", DATACLASS, "acme/other", []),
        ("app/services/s.py", DATACLASS, None, []),
        ("app/services/s.py", "class S:\n    a: int\n", CLOUD, []),
    ],
)
def test_hab102_flags_dataclass_in_services(
    path: str, text: str, slug: str | None, expected: list[str]
) -> None:
    assert codes(text, context(path, slug)) == expected


@pytest.mark.parametrize(
    ("path", "text", "slug", "expected"),
    [
        ("app/logic.py", "class E(Exception):\n    pass\n", DEVICE, ["HAB082"]),
        ("app/logic.py", "class E(ValueError):\n    pass\n", DEVICE, ["HAB082"]),
        ("app/errors.py", "class E(Exception):\n    pass\n", DEVICE, []),
        ("app/errors/base.py", "class E(Exception):\n    pass\n", DEVICE, []),
        (
            "app/logic.py",
            "from enum import Enum\nclass K(Enum):\n    A = 1\n",
            DEVICE,
            ["HAB082"],
        ),
        (
            "app/logic.py",
            PYDANTIC_MODEL,
            DEVICE,
            ["HAB082"],
        ),
        (
            "app/models.py",
            PYDANTIC_MODEL,
            DEVICE,
            [],
        ),
        ("app/logic.py", "class E(Exception):\n    pass\n", "acme/o", []),
        ("app/logic.py", "class E(Exception):\n    pass\n", None, []),
        ("app/logic.py", "class Plain:\n    pass\n", DEVICE, []),
    ],
)
def test_hab082_flags_misplaced_classes_in_device_service(
    path: str, text: str, slug: str | None, expected: list[str]
) -> None:
    assert codes(text, context(path, slug)) == expected


ENV = frozenset({"KNOWN"})


@pytest.mark.parametrize(
    ("text", "env", "expected"),
    [
        ("import os\nos.environ['NEW']\n", ENV, ["HAB092"]),
        ("import os\nos.environ.get('NEW')\n", ENV, ["HAB092"]),
        ("import os\nos.getenv('NEW', 'x')\n", ENV, ["HAB092"]),
        ("import os\nos.environ['KNOWN']\n", ENV, []),
        ("import os\nos.environ.get('HOME')\n", ENV, []),
        ("import os\nos.environ['NEW'] = '1'\n", ENV, []),
        ("import os\nos.environ.get(name)\n", ENV, []),
        ("import os\nos.environ['NEW']\n", None, []),
    ],
)
def test_hab092_flags_undeclared_environment_variables(
    text: str, env: frozenset[str] | None, expected: list[str]
) -> None:
    assert codes(text, context(env=env)) == expected


def test_env_example_absent_skips_env_rule() -> None:
    assert codes("import os\nos.getenv('NEW')\n", context(env=None)) == []


def test_hab092_skips_test_files() -> None:
    text = "import os\nos.getenv('NEW')\n"

    assert codes(text, context("tests/test_a.py", env=ENV)) == []


@pytest.mark.parametrize(
    ("text", "expected"),
    [
        ("ROOT = '/home/sam/project'\n", ["HAB070"]),
        ("ROOT = '/Users/anna/Code/x'\n", ["HAB070"]),
        ("ROOT = f'/home/sam/{name}'\n", ["HAB070"]),
        ("ROOT = '/opt/app/home/x/'\n", []),
        ("ROOT = '/home/'\n", []),
        ("ROOT = 'project'\n", []),
        ("def f():\n    '''See /home/sam/x/ for it.'''\n", []),
    ],
)
def test_hab070_flags_home_directory_literals(
    text: str, expected: list[str]
) -> None:
    assert codes(text) == expected


def test_hab070_skips_test_files() -> None:
    text = "ROOT = '/home/sam/project'\n"

    assert codes(text, TEST_CTX) == []


def test_unchanged_violation_line_is_not_reported() -> None:
    text = "HTTP_NOT_FOUND = 404\nOTHER = 1\n"

    assert codes(text, changed=frozenset({2})) == []
    assert codes(text, changed=frozenset({1})) == ["HAB084"]


def test_hits_are_ordered_by_position() -> None:
    text = "ROOT = '/home/a/b/'\nHTTP_NOT_FOUND = 404\n"

    found = python_habit_hits(ast.parse(text), text, EVERYWHERE, context())

    assert [(hit.line, hit.rule) for hit in found] == [
        (1, HabitRule.HOME_PATH),
        (2, HabitRule.HTTP_STATUS_NUMBER),
    ]


def test_hit_carries_habit_message_and_column() -> None:
    text = "x = 1\nHTTP_NOT_FOUND = 404\n"

    (hit,) = python_habit_hits(ast.parse(text), text, EVERYWHERE, context())

    assert hit.column == 1
    assert hit.message == (
        "H084: HTTP status as a bare number — use http.HTTPStatus"
    )


def lines(count: int) -> str:
    return "x = 1\n" * count


@pytest.mark.parametrize(
    ("count", "old", "expected"),
    [
        (1001, 999, 1),
        (1001, 1000, 1),
        (1001, None, 1),
        (1001, 1001, 0),
        (1500, 1200, 0),
        (1000, 999, 0),
        (999, None, 0),
    ],
)
def test_hab013_reports_only_the_crossing_of_the_limit(
    count: int, old: int | None, expected: int
) -> None:
    found = line_count_hits(lines(count), context(old=old))

    assert len(found) == expected
    assert [hit.rule for hit in found] == [HabitRule.LINE_LIMIT] * expected


def test_line_count_already_over_limit_not_reported() -> None:
    assert line_count_hits(lines(1200), context(old=1100)) == []


def test_hab013_skips_test_files() -> None:
    assert line_count_hits(lines(1500), context("tests/test_big.py")) == []


def test_hab013_counts_a_last_line_without_newline() -> None:
    text = lines(1000) + "x = 1"

    assert len(line_count_hits(text, context(old=10))) == 1


def test_hab104_common_tests_import_in_test_file_is_reported() -> None:
    text = "from common.tests import helper\n"

    assert codes(text, context("tests/test_a.py", CLOUD)) == ["HAB104"]


def test_status_cache_size_constant_is_not_hab084() -> None:
    assert codes("STATUS_CACHE_SIZE = 100\n") == []


def test_max_status_history_constant_is_not_hab084() -> None:
    assert codes("MAX_STATUS_HISTORY = 200\n") == []


@pytest.mark.parametrize(
    "ignore", ["['scratch']", "('scratch',)", "'scratch other'"]
)
def test_strenum_ignored_name_is_not_hab120(ignore: str) -> None:
    text = (
        "from enum import StrEnum\nclass C(StrEnum):\n"
        f"    _ignore_ = {ignore}\n    scratch = 'scratch'\n"
        "    red = 'red'\n"
    )

    assert codes(text) == ["HAB120"]


def test_strenum_comma_separated_ignore_is_not_hab120() -> None:
    text = (
        "from enum import StrEnum\nclass C(StrEnum):\n"
        "    _ignore_ = 'scratch, other'\n    scratch = 'scratch'\n"
        "    other = 'other'\n"
    )

    assert codes(text) == []


UI = "acme/web-ui"
CLK = "acme/kiosk-ui"
MENU = "acme/service-menu-ui"


def script_codes(
    text: str,
    ctx: HabitContext | None = None,
    changed: frozenset[int] = EVERYWHERE,
) -> list[str]:
    tokens = tokenize_source(text, StaticLanguage.SCRIPT)
    found = script_habit_hits(tokens, changed, ctx or context("src/a.ts"))
    return [hit.rule.value for hit in found]


@pytest.mark.parametrize(
    ("text", "expected"),
    [
        ("p.then(ok, fail);\n", ["HAB066"]),
        ("p.then(ok, fail,);\n", ["HAB066"]),
        ("p?.then((a) => a, (e) => { log(e, 1); });\n", ["HAB066"]),
        ("p.then(ok);\n", []),
        ("p.then(ok,);\n", []),
        ("p.then(f(a, b));\n", []),
        ("p.then(ok, fail, extra);\n", []),
        ("p.then();\n", []),
        ("then(ok, fail);\n", []),
        ("// p.then(ok, fail)\n", []),
    ],
)
def test_hab066_flags_then_with_two_arguments(
    text: str, expected: list[str]
) -> None:
    assert script_codes(text) == expected


def test_then_catch_chain_is_not_hab066() -> None:
    assert script_codes("p.then(onOk).catch(onErr);\n") == []


@pytest.mark.parametrize(
    ("text", "expected"),
    [
        ("try { go(); } catch { stop(); }\n", ["HAB005"]),
        ("p.catch(() => stop());\n", ["HAB005"]),
        ("p.catch(function () { stop(); });\n", ["HAB005"]),
        ("try { go(); } catch (err) { stop(err); }\n", []),
        ("p.catch((err) => stop(err));\n", []),
        ("p.catch(onErr);\n", []),
        ("p.catch(function (e) { stop(e); });\n", []),
    ],
)
def test_hab005_flags_catch_without_binding(
    text: str, expected: list[str]
) -> None:
    assert script_codes(text) == expected


def test_catch_with_binding_is_not_hab005() -> None:
    assert script_codes("try { a(); } catch (err) { b(err); }\n") == []


@pytest.mark.parametrize(
    ("text", "slug", "expected"),
    [
        ("import { U } from '@/api/types/user';\n", UI, ["HAB094"]),
        ('import type { U } from "@/api/types";\n', UI, ["HAB094"]),
        ("export * from '@/api/types/user';\n", UI, ["HAB094"]),
        ("const m = await import('@/api/types/user');\n", UI, ["HAB094"]),
        ("const m = require('@/api/types/user');\n", UI, ["HAB094"]),
        ("import { U } from '@/api/client';\n", UI, []),
        ("const p = '@/api/types/user';\n", UI, []),
        ("foo('@/api/types/user');\n", UI, []),
        ("import { U } from '@/api/types/user';\n", "acme/other", []),
        ("import { U } from '@/api/types/user';\n", None, []),
    ],
)
def test_hab094_flags_api_types_imports(
    text: str, slug: str | None, expected: list[str]
) -> None:
    assert script_codes(text, context("src/a.ts", slug)) == expected


def test_hab094_other_repo_is_silent() -> None:
    text = "import { U } from '@/api/types/user';\n"

    assert script_codes(text, context("src/a.ts", CLK)) == []


@pytest.mark.parametrize(
    ("text", "slug", "expected"),
    [
        ("const l = config.default_language;\n", CLK, ["HAB058"]),
        ("const l = config.default_language;\n", MENU, ["HAB058"]),
        ("const l = config['default_language'];\n", CLK, ["HAB058"]),
        ("const default_language = 1;\n", CLK, []),
        ("const l = config.default_language;\n", UI, []),
        ("const l = config.default_language;\n", None, []),
    ],
)
def test_hab058_flags_default_language(
    text: str, slug: str | None, expected: list[str]
) -> None:
    assert script_codes(text, context("src/a.ts", slug)) == expected


def test_hab058_other_repo_is_silent() -> None:
    text = "const l = config.default_language;\n"

    assert script_codes(text, context("src/a.ts", "acme/other")) == []


@pytest.mark.parametrize(
    ("text", "expected"),
    [
        ("const v = process.env.NEW_NAME;\n", ["HAB092"]),
        ("const v = process.env['NEW_NAME'];\n", ["HAB092"]),
        ('const v = process.env["NEW_NAME"];\n', ["HAB092"]),
        ("const v = import.meta.env.NEW_NAME;\n", ["HAB092"]),
        ("const v = process.env.KNOWN;\n", []),
        ("const v = import.meta.env.MODE;\n", []),
        ("const v = process.env.NODE_ENV;\n", []),
        ("const v = process.env[name];\n", []),
        ("const v = foo.process.env.NEW_NAME;\n", []),
    ],
)
def test_hab092_flags_undeclared_script_env(
    text: str, expected: list[str]
) -> None:
    assert script_codes(text, context("src/a.ts", env=ENV)) == expected


def test_hab092_script_needs_env_example_and_skips_tests() -> None:
    text = "const v = process.env.NEW_NAME;\n"

    assert script_codes(text, context("src/a.ts", env=None)) == []
    assert script_codes(text, context("src/a.test.ts", env=ENV)) == []


@pytest.mark.parametrize(
    ("text", "expected"),
    [
        ("const r = '/home/sam/app/';\n", ["HAB070"]),
        ('const r = "/Users/anna";\n', []),
        ('const r = "/Users/anna/code/";\n', ["HAB070"]),
        ("const r = '/opt/home/x/';\n", []),
        ("const r = 'home';\n", []),
    ],
)
def test_hab070_flags_script_home_paths(
    text: str, expected: list[str]
) -> None:
    assert script_codes(text) == expected


def test_hab070_script_skips_tests() -> None:
    text = "const r = '/home/sam/app/';\n"

    assert script_codes(text, context("src/a.spec.ts")) == []


def test_script_unchanged_line_is_not_reported() -> None:
    text = "p.then(a, b);\nq.then(c, d);\n"

    assert script_codes(text, changed=frozenset({2})) == ["HAB066"]


def locale_codes(
    path: str,
    text: str,
    changed: frozenset[int] = EVERYWHERE,
    slug: str | None = None,
    sibling_text: str | None = None,
) -> list[tuple[str, int]]:
    document = parse_locale(path, text)
    assert document is not None
    other = sibling_path(path, document.language)
    sibling = (
        parse_locale(other, sibling_text)
        if other and sibling_text is not None
        else None
    )
    found = locale_habit_hits(document, changed, context(path, slug), sibling)
    return [(hit.rule.value, hit.line) for hit in found]


def test_parse_locale_reports_dotted_keys_and_lines() -> None:
    text = (
        '{\n  "a": "x",\n  "nested": {\n    "b": "y",\n    "n": 3,\n'
        '    "deep": {\n      "c": "z"\n    }\n  },\n  "list": ["p", "q"]\n}\n'
    )

    document = parse_locale("src/locales/pl/translation.json", text)

    assert document is not None
    assert document.language == "pl"
    assert [(e.key, e.line, e.value) for e in document.entries] == [
        ("a", 2, "x"),
        ("nested.b", 4, "y"),
        ("nested.n", 5, None),
        ("nested.deep.c", 7, "z"),
        ("list.0", 10, "p"),
        ("list.1", 10, "q"),
    ]


@pytest.mark.parametrize("text", ["{", "[]", "", "{'a': 1}"])
def test_parse_locale_rejects_invalid_documents(text: str) -> None:
    assert parse_locale("src/locales/pl/a.json", text) is None


@pytest.mark.parametrize(
    ("path", "language"),
    [
        ("src/locales/pl/translation.json", "pl"),
        ("public/locales/en-GB/common.json", "en-GB"),
        ("i18n/pl.json", "pl"),
        ("ui/locales/en.json", "en"),
        ("src/locales/common.json", ""),
    ],
)
def test_parse_locale_language_comes_from_path(
    path: str, language: str
) -> None:
    document = parse_locale(path, "{}")

    assert document == LocaleDocument(language, path, ())


@pytest.mark.parametrize(
    ("path", "language", "expected"),
    [
        ("src/locales/pl/t.json", "pl", "src/locales/en/t.json"),
        ("src/locales/en/t.json", "en", "src/locales/pl/t.json"),
        ("i18n/pl.json", "pl", "i18n/en.json"),
        ("src/locales/de/t.json", "de", None),
        ("src/locales/common.json", "pl", None),
    ],
)
def test_sibling_path_swaps_the_language(
    path: str, language: str, expected: str | None
) -> None:
    assert sibling_path(path, language) == expected


PL = "src/locales/pl/translation.json"
EN = "src/locales/en/translation.json"
PL_FAMILY = (
    '{\n  "k_one": "{{count}} a",\n  "k_few": "{{count}} b",\n'
    '  "k_many": "{{count}} c",\n  "k_other": "{{count}} d"\n}\n'
)
EN_FAMILY = '{\n  "k_one": "{{count}} a",\n  "k_other": "{{count}} b"\n}\n'


def test_hab023_flags_count_key_without_plural_forms() -> None:
    text = '{\n  "items": "{{count}} items"\n}\n'

    assert locale_codes(EN, text) == [("HAB023", 2)]


def test_complete_plural_family_is_not_hab023() -> None:
    assert locale_codes(PL, PL_FAMILY, sibling_text=EN_FAMILY) == []
    assert locale_codes(EN, EN_FAMILY, sibling_text=PL_FAMILY) == []


def test_polish_family_without_other_is_not_hab023() -> None:
    text = (
        '{\n  "k_one": "{{count}} a",\n  "k_few": "{{count}} b",\n'
        '  "k_many": "{{count}} c"\n}\n'
    )

    assert locale_codes(PL, text, sibling_text=EN_FAMILY) == []


def test_hab023_flags_every_entry_of_an_incomplete_family() -> None:
    text = '{\n  "k_one": "{{count}} a",\n  "k_other": "{{count}} b"\n}\n'

    assert locale_codes(PL, text) == [("HAB023", 2), ("HAB023", 3)]
    assert locale_codes(EN, text) == []


def test_hab023_family_check_only_covers_changed_lines() -> None:
    text = '{\n  "k_one": "{{count}} a",\n  "k_other": "{{count}} b"\n}\n'

    assert locale_codes(PL, text, changed=frozenset({3})) == [("HAB023", 3)]


def test_hab023_flags_keys_missing_in_the_sibling() -> None:
    text = '{\n  "title": "T",\n  "extra": "E"\n}\n'
    sibling = '{\n  "title": "T"\n}\n'

    assert locale_codes(PL, text, sibling_text=sibling) == [("HAB023", 3)]
    assert locale_codes(EN, sibling, sibling_text=text) == []


def test_hab023_parity_compares_base_keys_of_plural_forms() -> None:
    sibling = '{\n  "k_one": "a",\n  "k_other": "b"\n}\n'

    assert locale_codes(PL, PL_FAMILY, sibling_text=sibling) == []


def test_locale_without_sibling_skips_parity() -> None:
    text = '{\n  "title": "T"\n}\n'

    assert locale_codes(PL, text, sibling_text=None) == []


def test_hab023_parity_is_limited_to_pl_and_en() -> None:
    text = '{\n  "title": "T"\n}\n'

    assert locale_codes("src/locales/de/t.json", text) == []


@pytest.mark.parametrize(
    ("value", "slug", "path", "expected"),
    [
        ("Wybierz automat", UI, PL, [("HAB057", 2)]),
        ("Ten Automat jest pusty", MENU, PL, [("HAB057", 2)]),
        ("Z automatów", UI, PL, [("HAB057", 2)]),
        ("Automatycznie", UI, PL, []),
        ("automatyczny", UI, PL, []),
        ("Wybierz automat", CLK, PL, []),
        ("Wybierz automat", None, PL, []),
        ("Pick an automat", UI, EN, []),
    ],
)
def test_hab057_flags_the_word_automat_in_pl(
    value: str, slug: str | None, path: str, expected: list[tuple[str, int]]
) -> None:
    text = f'{{\n  "pick": "{value}"\n}}\n'

    assert locale_codes(path, text, slug=slug) == expected


def test_automatycznie_is_not_hab057() -> None:
    text = '{\n  "a": "Zapisz automatycznie"\n}\n'

    assert locale_codes(PL, text, slug=UI) == []


def test_en_locale_automat_is_not_hab057() -> None:
    text = '{\n  "a": "Pick an automat"\n}\n'

    assert locale_codes(EN, text, slug=UI) == []


def test_lone_other_suffix_key_is_not_hab023() -> None:
    text = '{\n  "payment_method_other": "Inna metoda"\n}\n'

    assert locale_codes(PL, text) == []


def test_lone_other_suffix_key_parity_uses_full_key() -> None:
    text = '{\n  "title": "T",\n  "payment_method_other": "I"\n}\n'
    sibling = '{\n  "title": "T",\n  "payment_method": "M"\n}\n'

    assert locale_codes(PL, text, sibling_text=sibling) == [("HAB023", 3)]


def test_then_with_generic_arguments_is_not_hab066() -> None:
    text = "p.then(x => new Map<string, number>());\n"

    assert script_codes(text) == []


def test_api_typescript_import_is_not_hab094() -> None:
    text = "import { U } from '@/api/typescript';\n"

    assert script_codes(text, context("src/a.ts", UI)) == []


def test_deeply_nested_locale_reports_not_parsable() -> None:
    depth = 1200
    text = '{"a":' * depth + "1" + "}" * depth

    assert parse_locale(PL, text) is None


def test_value_on_separate_line_is_hab057() -> None:
    text = '{\n  "key":\n    "Wybierz automat"\n}\n'

    found = locale_codes(PL, text, changed=frozenset({3}), slug=UI)

    assert found == [("HAB057", 3)]


def test_value_line_is_kept_apart_from_key_line() -> None:
    text = '{\n  "key":\n    "Wybierz"\n}\n'

    document = parse_locale(PL, text)

    assert document is not None
    assert [(e.line, e.value_line) for e in document.entries] == [(2, 3)]
