from __future__ import annotations

import ast
import json

import pytest
from source_lexer import StaticLanguage, tokenize_source
from version_rules import (
    ES_NO_LIMIT,
    FloorResolver,
    Floors,
    VersionRule,
    load_jsonc,
    python_pin_floor,
    python_version_hits,
    range_floor,
    requires_python_floor,
    script_version_hits,
)

EVERYWHERE = frozenset(range(1, 3000))
PY314 = Floors(python_minor=14)
PY315 = Floors(python_minor=15)
REACT19 = Floors(react=(19, 0))
LOOP_IN_ASYNC = (
    "import asyncio\n\n\nasync def run():\n    asyncio.get_event_loop()\n"
)


NO_FLOORS = Floors()


def python_rules(
    text: str, floors: Floors = NO_FLOORS, changed: frozenset[int] = EVERYWHERE
) -> list[str]:
    hits = python_version_hits(ast.parse(text), changed, floors)
    return [str(hit.rule) for hit in hits]


def script_rules(
    text: str, floors: Floors = REACT19, changed: frozenset[int] = EVERYWHERE
) -> list[str]:
    tokens = tokenize_source(text, StaticLanguage.SCRIPT)
    return [str(h.rule) for h in script_version_hits(tokens, changed, floors)]


def resolver(files: dict[str, str]) -> FloorResolver:
    def tsconfigs(directory: str) -> list[str]:
        prefix = "" if directory == "." else f"{directory}/"
        return sorted(
            name
            for name in files
            if name.startswith(prefix)
            and name.rsplit("/", 1)[-1].startswith("tsconfig")
            and "node_modules" not in name
        )

    return FloorResolver(files.get, tsconfigs)


def test_get_event_loop_in_async_def_is_ver002() -> None:
    assert python_rules(LOOP_IN_ASYNC) == ["VER002"]


def test_get_event_loop_imported_by_name_in_async_is_ver002() -> None:
    text = (
        "from asyncio import get_event_loop as g\n\n\n"
        "async def f():\n    g()\n"
    )

    assert python_rules(text) == ["VER002"]


def test_get_event_loop_in_plain_def_is_not_ver002() -> None:
    text = "import asyncio\n\n\ndef run():\n    asyncio.get_event_loop()\n"

    assert python_rules(text) == []


def test_get_event_loop_at_module_level_is_not_ver002() -> None:
    assert python_rules("import asyncio\n\nasyncio.get_event_loop()\n") == []


def test_get_event_loop_in_nested_def_inside_async_is_not_ver002() -> None:
    text = (
        "import asyncio\n\n\nasync def run():\n"
        "    def inner():\n        asyncio.get_event_loop()\n"
        "    f = lambda: asyncio.get_event_loop()\n"
    )

    assert python_rules(text) == []


def test_get_event_loop_in_nested_async_is_reported_once() -> None:
    text = (
        "import asyncio\n\n\nasync def run():\n"
        "    async def inner():\n        asyncio.get_event_loop()\n"
    )

    assert python_rules(text) == ["VER002"]


def test_get_event_loop_without_asyncio_import_is_silent() -> None:
    text = "async def run():\n    asyncio.get_event_loop()\n"

    assert python_rules(text) == []


def test_unchanged_get_event_loop_is_silent() -> None:
    assert python_rules(LOOP_IN_ASYNC, changed=frozenset({1})) == []


@pytest.mark.parametrize(
    "name",
    ["iscoroutinefunction", "set_event_loop_policy", "get_event_loop_policy"],
)
def test_ver003_deprecated_asyncio_api_at_py314(name: str) -> None:
    assert python_rules(f"import asyncio\nasyncio.{name}\n", PY314) == [
        "VER003"
    ]


def test_ver003_below_py314_is_silent() -> None:
    text = "import asyncio\nasyncio.iscoroutinefunction(f)\n"

    assert python_rules(text, Floors(python_minor=13)) == []


def test_ver003_unknown_floor_is_silent() -> None:
    assert (
        python_rules("import asyncio\nasyncio.iscoroutinefunction(f)\n") == []
    )


def test_ver007_re_match_at_py315() -> None:
    assert python_rules("import re\nre.match('a', s)\n", PY315) == ["VER007"]


def test_ver007_below_py315_is_silent() -> None:
    assert python_rules("import re\nre.match('a', s)\n", PY314) == []


def test_ver007_other_match_is_silent() -> None:
    assert (
        python_rules("import re\nre.fullmatch('a', s)\nm.match(s)\n", PY315)
        == []
    )


def test_ver201_forward_ref_calls() -> None:
    text = "export const A = React.forwardRef<T, P>((p, r) => null);\n"

    assert script_rules(text) == ["VER201"]
    assert script_rules("const A = forwardRef(f);\n") == ["VER201"]


def test_react18_forward_ref_is_silent() -> None:
    assert (
        script_rules("const A = forwardRef(f);\n", Floors(react=(18, 3))) == []
    )


def test_unknown_react_forward_ref_is_silent() -> None:
    assert script_rules("const A = forwardRef(f);\n", Floors()) == []


def test_ver202_context_provider() -> None:
    text = "const A = () => <ThemeContext.Provider value={v} />;\n"

    assert script_rules(text) == ["VER202"]


def test_custom_provider_not_ending_in_context_is_not_ver202() -> None:
    assert script_rules("const A = <Store.Provider value={v} />;\n") == []


def test_generic_type_argument_provider_is_not_ver202() -> None:
    assert script_rules("const x: Wrapper<ThemeContext.Provider> = y;\n") == []


def test_returned_provider_is_ver202() -> None:
    assert script_rules("return <AppContext.Provider value={v} />;\n") == [
        "VER202"
    ]


def test_ver203_use_form_state_import_and_call() -> None:
    text = "import { useFormState } from 'react-dom';\nuseFormState(a, b);\n"

    assert script_rules(text) == ["VER203", "VER203"]


def test_ver203_use_action_state_is_silent() -> None:
    assert script_rules("useActionState(a, b);\n") == []


def test_ver204_prop_types_assignment() -> None:
    assert script_rules("A.propTypes = {};\n") == ["VER204"]


def test_ver204_comparison_is_silent() -> None:
    assert (
        script_rules("if (A.propTypes == null) {}\nx = A.propTypes;\n") == []
    )


def test_unchanged_react_line_is_silent() -> None:
    assert script_rules("A.propTypes = {};\n", changed=frozenset({5})) == []


def test_rule_codes() -> None:
    assert [rule.value for rule in VersionRule] == [
        "VER002",
        "VER003",
        "VER007",
        "VER201",
        "VER202",
        "VER203",
        "VER204",
    ]


@pytest.mark.parametrize(
    ("requirement", "minor"),
    [
        (">=3.12", 12),
        (">3.9", 9),
        ("~=3.11", 11),
        ("==3.13.*", 13),
        (">=3.11,<3.14", 11),
        ("  >=  3.10 , < 4", 10),
        (">=3.9,>=3.11", 9),
        ("<3.14", None),
        (">=3", None),
        ("!=3.9.*", None),
        ("garbage", None),
    ],
)
def test_requires_python_floor_forms(
    requirement: str, minor: int | None
) -> None:
    assert requires_python_floor(requirement) == minor


def test_requires_python_gt_form_floor() -> None:
    files = {"pyproject.toml": '[project]\nrequires-python = ">3.9"\n'}

    assert resolver(files).python_floors("app/a.py").python_minor == 9


def test_python_pin_floor() -> None:
    assert python_pin_floor("3.14.3\n") == 14
    assert python_pin_floor("pypy3.10") is None


def test_unparsable_requires_python_disables_floor() -> None:
    files = {
        "pyproject.toml": '[project]\nrequires-python = "garbage"\n',
        ".python-version": "3.14\n",
    }

    assert resolver(files).python_floors("a.py").python_minor is None


def test_python_version_file_used_without_requires_python() -> None:
    files = {
        "pyproject.toml": '[project]\nname = "x"\n',
        ".python-version": "3.13\n",
    }

    assert resolver(files).python_floors("a.py").python_minor == 13


def test_dockerfile_alone_gives_no_floor() -> None:
    files = {"Dockerfile": "FROM python:3.14\n"}

    assert resolver(files).python_floors("a.py").python_minor is None


def test_nearest_pyproject_wins() -> None:
    files = {
        "pyproject.toml": '[project]\nrequires-python = ">=3.14"\n',
        "svc/pyproject.toml": '[project]\nrequires-python = ">=3.11"\n',
    }

    found = resolver(files)

    assert found.python_floors("svc/a.py").python_minor == 11
    assert found.python_floors("other/a.py").python_minor == 14


def test_python_floor_is_cached_per_directory() -> None:
    reads: list[str] = []
    files = {"pyproject.toml": '[project]\nrequires-python = ">=3.12"\n'}

    def read(path: str) -> str | None:
        reads.append(path)
        return files.get(path)

    found = FloorResolver(read, lambda _directory: [])
    found.python_floors("a.py")
    count = len(reads)
    found.python_floors("b.py")

    assert len(reads) == count


def tsconfig(options: str, extra: str = "") -> str:
    return f'{{{extra}"compilerOptions": {{{options}}}}}'


def test_tsconfig_lib_year() -> None:
    files = {
        "package.json": "{}",
        "tsconfig.json": tsconfig('"lib": ["ES2022", "DOM"]'),
    }

    assert resolver(files).script_floors("src/a.ts").es_year == 2022


def test_tsconfig_target_used_without_lib() -> None:
    files = {
        "package.json": "{}",
        "tsconfig.json": tsconfig('"target": "ES2020"'),
    }

    assert resolver(files).script_floors("a.ts").es_year == 2020


def test_tsconfig_min_over_package_tree() -> None:
    files = {
        "package.json": "{}",
        "tsconfig.json": tsconfig('"lib": ["ES2017"]'),
        "tsconfig.app.json": tsconfig('"lib": ["ES2022"]'),
        "node_modules/x/tsconfig.json": tsconfig('"lib": ["ES5"]'),
    }

    assert resolver(files).script_floors("src/a.ts").es_year == 2017


def test_tsconfig_relative_extends_resolved() -> None:
    files = {
        "package.json": "{}",
        "tsconfig.json": '{"extends": "./config/base"}',
        "config/base.json": tsconfig('"target": "ES2021"'),
    }

    assert resolver(files).script_floors("a.ts").es_year == 2021


def test_tsconfig_child_lib_overrides_extended() -> None:
    files = {
        "package.json": "{}",
        "tsconfig.json": (
            '{"extends": "./base.json",'
            ' "compilerOptions": {"lib": ["ES2023"]}}'
        ),
        "base.json": tsconfig('"lib": ["ES2015"]'),
    }

    assert resolver(files).script_floors("a.ts").es_year == 2023


def test_tsconfig_package_extends_disables_floor() -> None:
    files = {
        "package.json": "{}",
        "tsconfig.json": '{"extends": "@tsconfig/node20/tsconfig.json"}',
        "tsconfig.app.json": tsconfig('"lib": ["ES2022"]'),
    }

    assert resolver(files).script_floors("a.ts").es_year is None


def test_tsconfig_unparsable_disables_floor() -> None:
    files = {
        "package.json": "{}",
        "tsconfig.json": "{ not json",
        "tsconfig.app.json": tsconfig('"lib": ["ES2022"]'),
    }

    assert resolver(files).script_floors("a.ts").es_year is None


def test_tsconfig_extends_cycle_disables_floor() -> None:
    files = {
        "package.json": "{}",
        "tsconfig.json": '{"extends": "./tsconfig.json"}',
    }

    assert resolver(files).script_floors("a.ts").es_year is None


def test_tsconfig_esnext_is_no_limit() -> None:
    files = {
        "package.json": "{}",
        "tsconfig.json": tsconfig('"lib": ["ESNext"]'),
    }

    assert resolver(files).script_floors("a.ts").es_year == ES_NO_LIMIT


def test_solution_style_tsconfig_without_options_is_ignored() -> None:
    files = {
        "package.json": "{}",
        "tsconfig.json": '{"files": [], "references": []}',
        "tsconfig.app.json": tsconfig('"target": "ES2022"'),
    }

    assert resolver(files).script_floors("a.ts").es_year == 2022


def test_no_tsconfig_gives_no_es_floor() -> None:
    assert (
        resolver({"package.json": "{}"}).script_floors("a.ts").es_year is None
    )


def test_jsonc_comments_and_trailing_commas() -> None:
    text = '{\n // c\n "a": "x//y", /* b */ "l": [1, 2,],\n}\n'

    assert load_jsonc(text) == {"a": "x//y", "l": [1, 2]}


def test_jsonc_rejects_non_object() -> None:
    assert load_jsonc("[1]") is None


def react_package(**sections: dict[str, str]) -> dict[str, str]:
    return {"package.json": json.dumps(sections)}


@pytest.mark.parametrize(
    ("spec", "bound"),
    [
        ("^19.1.1", (19, 1)),
        ("~19.0", (19, 0)),
        (">=19", (19, 0)),
        ("19.2.0", (19, 2)),
        ("18.3.1 || 19", (18, 3)),
        (">=18 <20", (18, 0)),
        ("19.x", (19, 0)),
        ("workspace:*", None),
        ("latest", None),
        ("git+https://x/y.git", None),
        ("<20", None),
        ("*", None),
    ],
)
def test_range_floor_forms(spec: str, bound: tuple[int, int] | None) -> None:
    assert range_floor(spec) == bound


def test_react_peer_lower_bound_wins() -> None:
    files = react_package(
        dependencies={"react": "^18.3.1"}, peerDependencies={"react": ">=19"}
    )

    assert resolver(files).script_floors("a.tsx").react == (18, 3)


def test_react_dev_dependency_alone_is_floor() -> None:
    files = react_package(devDependencies={"react": "^19.0.0"})

    assert resolver(files).script_floors("a.tsx").react == (19, 0)


def test_react_workspace_version_disables_floor() -> None:
    files = react_package(
        dependencies={"react": "workspace:*"},
        peerDependencies={"react": "^19"},
    )

    assert resolver(files).script_floors("a.tsx").react is None


def test_no_react_dependency_gives_no_floor() -> None:
    files = react_package(dependencies={"vue": "^3"})

    assert resolver(files).script_floors("a.tsx").react is None


def test_script_without_package_json_has_no_floors() -> None:
    files = {"tsconfig.json": tsconfig('"target": "ES2022"')}

    assert resolver(files).script_floors("src/a.tsx") == Floors()


def test_nearest_package_json_wins() -> None:
    files = {
        "package.json": json.dumps({"dependencies": {"react": "^18"}}),
        "web/package.json": json.dumps({"dependencies": {"react": "^19"}}),
    }

    found = resolver(files)

    assert found.script_floors("web/src/a.tsx").react == (19, 0)
    assert found.script_floors("src/a.tsx").react == (18, 0)


def test_react_hook_form_use_form_state_is_not_ver203() -> None:
    text = (
        "import { useFormState } from 'react-hook-form';\n"
        "const s = useFormState({ control });\n"
    )

    assert script_rules(text) == []


def test_jsx_text_use_form_state_is_not_ver203() -> None:
    assert script_rules("const A = () => <p>useFormState</p>;\n") == []


def test_aliased_react_dom_use_form_state_is_ver203() -> None:
    text = (
        "import { useFormState as useFs } from 'react-dom';\n"
        "const s = useFs(a, b);\n"
    )

    assert script_rules(text) == ["VER203", "VER203"]


def test_react_use_form_state_import_is_ver203() -> None:
    text = 'import { useState, useFormState } from "react";\n'

    assert script_rules(text) == ["VER203"]


def test_tsconfig_without_target_disables_floor() -> None:
    files = {
        "package.json": "{}",
        "tsconfig.json": '{"compilerOptions": {"strict": true}}',
        "tsconfig.app.json": tsconfig('"lib": ["ES2022"]'),
    }

    assert resolver(files).script_floors("a.ts").es_year is None


def test_solution_style_tsconfig_is_skipped() -> None:
    files = {
        "package.json": "{}",
        "tsconfig.json": '{"files": [], "references": []}',
        "tsconfig.app.json": tsconfig('"lib": ["ES2022"]'),
    }

    assert resolver(files).script_floors("a.ts").es_year == 2022


def test_solution_style_tsconfig_with_compiler_options_is_skipped() -> None:
    files = {
        "package.json": "{}",
        "tsconfig.json": '{"files": [], "compilerOptions": {"strict": true}}',
        "tsconfig.app.json": tsconfig('"lib": ["ES2022"]'),
    }

    assert resolver(files).script_floors("a.ts").es_year == 2022


def test_files_empty_with_include_is_not_solution_style() -> None:
    files = {
        "package.json": "{}",
        "tsconfig.json": '{"files": [], "include": ["src"]}',
        "tsconfig.app.json": tsconfig('"lib": ["ES2022"]'),
    }

    assert resolver(files).script_floors("a.ts").es_year is None
