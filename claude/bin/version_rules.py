from __future__ import annotations

import ast
import json
import posixpath
import re
import tomllib
from dataclasses import dataclass, field
from enum import StrEnum
from pathlib import PurePosixPath
from typing import TYPE_CHECKING

from habit_rules import HabitHit, dotted_name
from script_habits import at, is_ident, is_punct, located_hit, unquoted
from source_lexer import Token, TokenKind

if TYPE_CHECKING:
    from collections.abc import Callable, Iterator

ASYNCIO_POLICY_MINOR = 14
PREFIXMATCH_MINOR = 15
PYTHON_EXPLICIT_OVERRIDE_MINOR = 12
OBJECT_HAS_OWN_YEAR = 2022
ES_NO_LIMIT = 9999
ES_LEGACY_OFFSET = 2009
FIRST_YEAR_DIGITS = 2000
REACT_19 = (19, 0)
MAX_EXTENDS_DEPTH = 10
PYPROJECT = "pyproject.toml"
PYTHON_VERSION_FILE = ".python-version"
PACKAGE_JSON = "package.json"
REQUIRES_PYTHON_KEY = "requires-python"
DEPENDENCY_SECTIONS = ("dependencies", "devDependencies", "peerDependencies")
REACT_PACKAGE = "react"
GET_EVENT_LOOP = "asyncio.get_event_loop"
ASYNCIO_DEPRECATED = frozenset(
    {
        "asyncio.iscoroutinefunction",
        "asyncio.set_event_loop_policy",
        "asyncio.get_event_loop_policy",
    }
)
RE_MATCH = "re.match"
FORWARD_REF = "forwardRef"
USE_FORM_STATE = "useFormState"
FORM_STATE_MODULES = frozenset({"react", "react-dom"})
IMPORT = "import"
FROM = "from"
AS = "as"
PROP_TYPES = "propTypes"
PROVIDER = "Provider"
CONTEXT_SUFFIX = "Context"
RETURN = "return"
FUNCTION = "function"
DOT = "."
EQUALS = "="
OPEN_CALL = "("
OPEN_GENERIC = "<"
ELEMENT_CLOSERS = ")]"
RELATIVE_EXTENDS = "."
JSON_SUFFIX = ".json"
ASYNC_SCOPE_BOUNDARIES = (
    ast.FunctionDef,
    ast.AsyncFunctionDef,
    ast.Lambda,
    ast.ClassDef,
    ast.GeneratorExp,
)
REQUIRES_PYTHON_CLAUSE = re.compile(r"^(?:>=|>|~=|==)\s*3\.(\d+)(?!\w)")
PYTHON_PIN = re.compile(r"^\s*3\.(\d+)")
ES_NAME = re.compile(r"^(?:lib\.)?es(next|\d+)", re.IGNORECASE)
REACT_ALTERNATIVE = re.compile(r"^\s*(?:\^|~|>=|=|v)?\s*(\d+)(?:\.(\d+))?")
JSON_STRING_OR_COMMENT = re.compile(
    r'("(?:\\.|[^"\\])*")|//[^\n]*|/\*.*?\*/', re.DOTALL
)
JSON_STRING_OR_COMMA = re.compile(r'("(?:\\.|[^"\\])*")|,(?=\s*[}\]])')


class VersionRule(StrEnum):
    """The version-gated modern idiom rules."""

    GET_EVENT_LOOP = "VER002"
    ASYNCIO_DEPRECATED = "VER003"
    RE_MATCH = "VER007"
    FORWARD_REF = "VER201"
    CONTEXT_PROVIDER = "VER202"
    USE_FORM_STATE = "VER203"
    PROP_TYPES = "VER204"


VERSION_MESSAGES = {
    VersionRule.GET_EVENT_LOOP: (
        "VER002: asyncio.get_event_loop() inside async def"
        " — use asyncio.get_running_loop() (since 3.7)"
    ),
    VersionRule.ASYNCIO_DEPRECATED: (
        "VER003: deprecated asyncio API — use inspect.iscoroutinefunction"
        " or asyncio.run(..., loop_factory=...) (since 3.14)"
    ),
    VersionRule.RE_MATCH: "VER007: re.match — use re.prefixmatch (since 3.15)",
    VersionRule.FORWARD_REF: (
        "VER201: forwardRef — take ref as a normal prop (since React 19)"
    ),
    VersionRule.CONTEXT_PROVIDER: (
        "VER202: <Context.Provider> — render <Context value=...>"
        " (since React 19)"
    ),
    VersionRule.USE_FORM_STATE: (
        "VER203: useFormState — use useActionState (since React 19)"
    ),
    VersionRule.PROP_TYPES: (
        "VER204: propTypes are ignored — type the props (since React 19)"
    ),
}


@dataclass(frozen=True, slots=True)
class Floors:
    """The oldest language and library versions a file must support."""

    python_minor: int | None = None
    es_year: int | None = None
    react: tuple[int, int] | None = None

    def python_at_least(self, minor: int) -> bool:
        """Tell whether every supported Python has at least this minor."""
        return self.python_minor is not None and self.python_minor >= minor

    def es_at_least(self, year: int) -> bool:
        """Tell whether every supported ES edition is at least this year."""
        return self.es_year is not None and self.es_year >= year

    def react_at_least(self, version: tuple[int, int]) -> bool:
        """Tell whether every supported React is at least this version."""
        return self.react is not None and self.react >= version


def requires_python_floor(requirement: str) -> int | None:
    """Return the minor of the lowest lower bound of a requires-python."""
    minors = [
        int(found[1])
        for clause in requirement.split(",")
        if (found := REQUIRES_PYTHON_CLAUSE.match(clause.strip()))
    ]
    return min(minors, default=None)


def python_pin_floor(text: str) -> int | None:
    """Return the minor a .python-version file pins."""
    found = PYTHON_PIN.match(text)
    return None if found is None else int(found[1])


def load_jsonc(text: str) -> dict[str, object] | None:
    """Parse a JSON object that may hold comments and trailing commas."""
    plain = JSON_STRING_OR_COMMENT.sub(
        lambda found: found[1] or " ", text.lstrip("\ufeff")
    )
    clean = JSON_STRING_OR_COMMA.sub(lambda found: found[1] or "", plain)
    try:
        document = json.loads(clean)
    except ValueError:
        return None
    return document if isinstance(document, dict) else None


def es_year(name: str) -> int | None:
    """Return the ES edition year a lib or target name stands for."""
    found = ES_NAME.match(name)
    if found is None:
        return None
    if found[1].lower() == "next":
        return ES_NO_LIMIT
    number = int(found[1])
    return number if number >= FIRST_YEAR_DIGITS else number + ES_LEGACY_OFFSET


def options_es_year(options: dict[str, object]) -> int | None:
    """Return the lowest ES edition a tsconfig's lib, else target, names."""
    lib = options.get("lib")
    if isinstance(lib, list):
        years = [
            year
            for item in lib
            if isinstance(item, str) and (year := es_year(item)) is not None
        ]
        if years:
            return min(years)
    target = options.get("target")
    return es_year(target) if isinstance(target, str) else None


def range_floor(spec: object) -> tuple[int, int] | None:
    """Return the lowest (major, minor) a semver range admits."""
    if not isinstance(spec, str):
        return None
    found = [REACT_ALTERNATIVE.match(part) for part in spec.split("||")]
    if any(match is None for match in found):
        return None
    return min((int(match[1]), int(match[2] or 0)) for match in found if match)


def react_floor(manifest: dict[str, object]) -> tuple[int, int] | None:
    """Return the lowest React version a package.json admits."""
    bounds: list[tuple[int, int]] = []
    for section in DEPENDENCY_SECTIONS:
        dependencies = manifest.get(section)
        if not isinstance(dependencies, dict) or (
            REACT_PACKAGE not in dependencies
        ):
            continue
        bound = range_floor(dependencies[REACT_PACKAGE])
        if bound is None:
            return None
        bounds.append(bound)
    return min(bounds, default=None)


def extends_paths(directory: str, extends: object) -> list[str] | None:
    """Return the config paths a relative extends names, else None."""
    names = [extends] if isinstance(extends, str) else extends
    if names is None:
        return []
    if not isinstance(names, list) or not all(
        isinstance(name, str) and name.startswith(RELATIVE_EXTENDS)
        for name in names
    ):
        return None
    return [
        path if path.endswith(JSON_SUFFIX) else path + JSON_SUFFIX
        for path in (
            posixpath.normpath(posixpath.join(directory, n)) for n in names
        )
    ]


@dataclass(slots=True)
class FloorResolver:
    """Resolves the version floors of files through injected readers."""

    read: Callable[[str], str | None]
    tsconfigs: Callable[[str], list[str]]
    python_cache: dict[str, int | None] = field(default_factory=dict)
    es_cache: dict[str, int | None] = field(default_factory=dict)
    react_cache: dict[str, tuple[int, int] | None] = field(
        default_factory=dict
    )

    def python_floors(self, path: str) -> Floors:
        """Return the Python floor of a source file."""
        directory = str(PurePosixPath(path).parent)
        if directory not in self.python_cache:
            self.python_cache[directory] = self.python_floor(
                PurePosixPath(directory)
            )
        return Floors(python_minor=self.python_cache[directory])

    def script_floors(self, path: str) -> Floors:
        """Return the ES and React floors of a script file."""
        package = self.package_dir(PurePosixPath(path).parent)
        if package is None:
            return Floors()
        return Floors(
            es_year=self.es_floor(package),
            react=self.react_floor_of(package),
        )

    def python_floor(self, start: PurePosixPath) -> int | None:
        """Walk up from a directory to the first Python declaration."""
        for directory in (start, *start.parents):
            declared, minor = self.declared_minor(directory)
            if declared:
                return minor
        return None

    def declared_minor(
        self, directory: PurePosixPath
    ) -> tuple[bool, int | None]:
        """Return whether a directory declares Python, and its minor."""
        text = self.read(str(directory / PYPROJECT))
        try:
            project = tomllib.loads(text or "").get("project", {})
        except tomllib.TOMLDecodeError:
            project = {}
        if isinstance(project, dict) and REQUIRES_PYTHON_KEY in project:
            requirement = project[REQUIRES_PYTHON_KEY]
            if isinstance(requirement, str):
                return True, requires_python_floor(requirement)
            return True, None
        pin = self.read(str(directory / PYTHON_VERSION_FILE))
        minor = None if pin is None else python_pin_floor(pin)
        return minor is not None, minor

    def package_dir(self, start: PurePosixPath) -> str | None:
        """Return the nearest directory above a path with a package.json."""
        for directory in (start, *start.parents):
            if self.read(str(directory / PACKAGE_JSON)) is not None:
                return str(directory)
        return None

    def react_floor_of(self, package: str) -> tuple[int, int] | None:
        """Return the React floor a package's manifest declares."""
        if package not in self.react_cache:
            text = self.read(str(PurePosixPath(package) / PACKAGE_JSON))
            manifest = None if text is None else load_jsonc(text)
            self.react_cache[package] = (
                None if manifest is None else react_floor(manifest)
            )
        return self.react_cache[package]

    def es_floor(self, package: str) -> int | None:
        """Return the lowest ES edition over a package's tsconfig files."""
        if package not in self.es_cache:
            self.es_cache[package] = self.tsconfig_floor(package)
        return self.es_cache[package]

    def tsconfig_floor(self, package: str) -> int | None:
        """Compute the lowest ES edition over a package's tsconfig files."""
        years: list[int] = []
        for path in self.tsconfigs(package):
            options = self.compiler_options(path, 0)
            if options is None:
                return None
            year = options_es_year(options)
            if year is not None:
                years.append(year)
            elif not self.is_solution_style(path):
                return None
        return min(years, default=None)

    def is_solution_style(self, path: str) -> bool:
        """Tell whether a tsconfig lists no files of its own."""
        text = self.read(path)
        config = None if text is None else load_jsonc(text)
        return (
            config is not None
            and config.get("files") == []
            and config.get("include", []) == []
        )

    def compiler_options(
        self, path: str, depth: int
    ) -> dict[str, object] | None:
        """Return a tsconfig's compilerOptions merged over its extends."""
        text = self.read(path)
        config = None if text is None else load_jsonc(text)
        if config is None or depth > MAX_EXTENDS_DEPTH:
            return None
        parents = extends_paths(posixpath.dirname(path), config.get("extends"))
        if parents is None:
            return None
        merged: dict[str, object] = {}
        for parent in parents:
            inherited = self.compiler_options(parent, depth + 1)
            if inherited is None:
                return None
            merged.update(inherited)
        own = config.get("compilerOptions")
        merged.update(own if isinstance(own, dict) else {})
        return merged


def node_hit(rule: VersionRule, node: ast.expr) -> HabitHit:
    """Build the hit of a version rule at the position of a node."""
    return HabitHit(
        rule, node.lineno, node.col_offset + 1, VERSION_MESSAGES[rule]
    )


def import_table(tree: ast.AST) -> dict[str, str]:
    """Map the names a module binds by import to what they stand for."""
    table: dict[str, str] = {}
    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            for alias in node.names:
                local = alias.asname or alias.name.partition(DOT)[0]
                table[local] = alias.name if alias.asname else local
        elif (
            isinstance(node, ast.ImportFrom) and node.module and not node.level
        ):
            for alias in node.names:
                table[alias.asname or alias.name] = (
                    f"{node.module}.{alias.name}"
                )
    return table


def qualified_name(node: ast.AST, table: dict[str, str]) -> str:
    """Return the imported dotted name a node refers to, else empty."""
    head, dot, rest = dotted_name(node).partition(DOT)
    target = table.get(head)
    return "" if target is None else f"{target}{dot}{rest}"


def references(
    tree: ast.AST, table: dict[str, str], names: frozenset[str]
) -> Iterator[ast.expr]:
    """Yield the nodes that refer to one of the imported names."""
    for node in ast.walk(tree):
        if (
            isinstance(node, ast.Name | ast.Attribute)
            and qualified_name(node, table) in names
        ):
            yield node


def coroutine_body(function: ast.AsyncFunctionDef) -> Iterator[ast.AST]:
    """Yield the nodes that run inside a coroutine, not in nested scopes."""
    pending: list[ast.AST] = list(function.body)
    while pending:
        node = pending.pop()
        yield node
        if not isinstance(node, ASYNC_SCOPE_BOUNDARIES):
            pending.extend(ast.iter_child_nodes(node))


def event_loop_hits(
    tree: ast.AST, table: dict[str, str]
) -> Iterator[HabitHit]:
    """Yield get_event_loop calls made directly inside a coroutine."""
    for function in ast.walk(tree):
        if not isinstance(function, ast.AsyncFunctionDef):
            continue
        for node in coroutine_body(function):
            if (
                isinstance(node, ast.Call)
                and qualified_name(node.func, table) == GET_EVENT_LOOP
            ):
                yield node_hit(VersionRule.GET_EVENT_LOOP, node)


def python_version_hits(
    tree: ast.Module, changed: frozenset[int], floors: Floors
) -> list[HabitHit]:
    """Return the version-gated hits of a Python file on changed lines."""
    table = import_table(tree)
    hits = list(event_loop_hits(tree, table))
    if floors.python_at_least(ASYNCIO_POLICY_MINOR):
        hits += [
            node_hit(VersionRule.ASYNCIO_DEPRECATED, node)
            for node in references(tree, table, ASYNCIO_DEPRECATED)
        ]
    if floors.python_at_least(PREFIXMATCH_MINOR):
        hits += [
            node_hit(VersionRule.RE_MATCH, node)
            for node in references(tree, table, frozenset({RE_MATCH}))
        ]
    return sorted(
        {hit for hit in hits if hit.line in changed},
        key=lambda hit: (hit.line, hit.column, hit.rule),
    )


def starts_element(code: list[Token], index: int) -> bool:
    """Tell whether the < at index can open a JSX element."""
    previous = at(code, index - 1)
    if previous is None:
        return True
    if previous.kind is TokenKind.PUNCT:
        return previous.text not in ELEMENT_CLOSERS
    return is_ident(previous, RETURN)


def forward_ref_hits(code: list[Token]) -> Iterator[HabitHit]:
    """Yield forwardRef calls."""
    for index, token in enumerate(code):
        following = at(code, index + 1)
        if (
            is_ident(token, FORWARD_REF)
            and (
                is_punct(following, OPEN_CALL)
                or is_punct(following, OPEN_GENERIC)
            )
            and not is_ident(at(code, index - 1), FUNCTION)
        ):
            yield located_hit(
                VersionRule.FORWARD_REF,
                token,
                VERSION_MESSAGES[VersionRule.FORWARD_REF],
            )


def provider_hits(code: list[Token]) -> Iterator[HabitHit]:
    """Yield <XContext.Provider elements."""
    for index, token in enumerate(code):
        context = at(code, index - 2)
        if (
            is_ident(token, PROVIDER)
            and is_punct(at(code, index - 1), DOT)
            and context is not None
            and context.kind is TokenKind.IDENT
            and context.text.endswith(CONTEXT_SUFFIX)
            and is_punct(at(code, index - 3), OPEN_GENERIC)
            and starts_element(code, index - 3)
        ):
            yield located_hit(
                VersionRule.CONTEXT_PROVIDER,
                code[index - 3],
                VERSION_MESSAGES[VersionRule.CONTEXT_PROVIDER],
            )


def import_list_end(code: list[Token], opening: int) -> int | None:
    """Return the index of the } closing an import's named list."""
    for index in range(opening, len(code)):
        if is_punct(code[index], "}"):
            return index
    return None


def form_state_bindings(code: list[Token]) -> Iterator[tuple[int, str]]:
    """Yield the specifier index and local name of each useFormState import."""
    for index, token in enumerate(code):
        if not (
            is_ident(token, IMPORT) and is_punct(at(code, index + 1), "{")
        ):
            continue
        end = import_list_end(code, index + 1)
        source = None if end is None else at(code, end + 2)
        if (
            end is None
            or not is_ident(at(code, end + 1), FROM)
            or source is None
            or unquoted(source) not in FORM_STATE_MODULES
        ):
            continue
        for position in range(index + 2, end):
            if not is_ident(code[position], USE_FORM_STATE):
                continue
            alias = at(code, position + 2)
            renamed = is_ident(at(code, position + 1), AS) and alias
            yield position, alias.text if alias and renamed else USE_FORM_STATE


def form_state_hits(code: list[Token]) -> Iterator[HabitHit]:
    """Yield the useFormState imports from React and their uses."""
    bindings = dict(form_state_bindings(code))
    names = set(bindings.values())
    for index, token in enumerate(code):
        if index in bindings or (
            token.kind is TokenKind.IDENT
            and token.text in names
            and not is_punct(at(code, index - 1), DOT)
            and not is_ident(at(code, index - 1), AS)
        ):
            yield located_hit(
                VersionRule.USE_FORM_STATE,
                token,
                VERSION_MESSAGES[VersionRule.USE_FORM_STATE],
            )


def prop_types_hits(code: list[Token]) -> Iterator[HabitHit]:
    """Yield X.propTypes = assignments."""
    for index, token in enumerate(code):
        if (
            is_ident(token, PROP_TYPES)
            and is_punct(at(code, index - 1), DOT)
            and is_punct(at(code, index + 1), EQUALS)
            and not is_punct(at(code, index + 2), EQUALS)
        ):
            yield located_hit(
                VersionRule.PROP_TYPES,
                token,
                VERSION_MESSAGES[VersionRule.PROP_TYPES],
            )


def script_version_hits(
    tokens: list[Token], changed: frozenset[int], floors: Floors
) -> list[HabitHit]:
    """Return the version-gated hits of a script file on changed lines."""
    if not floors.react_at_least(REACT_19):
        return []
    code = [token for token in tokens if token.kind is not TokenKind.COMMENT]
    hits = {
        hit
        for detector in (
            forward_ref_hits,
            provider_hits,
            form_state_hits,
            prop_types_hits,
        )
        for hit in detector(code)
        if hit.line in changed
    }
    return sorted(hits, key=lambda hit: (hit.line, hit.column, hit.rule))
