from __future__ import annotations

import ast
import re
from collections.abc import Callable
from dataclasses import dataclass
from enum import StrEnum
from http import HTTPStatus
from pathlib import PurePosixPath
from typing import TYPE_CHECKING

from magic_numbers import is_enum_class
from source_lexer import static_is_test

if TYPE_CHECKING:
    from collections.abc import Iterator

CLOUD_REPO = "acme/cloud-platform"
DEVICE_REPO = "acme/device-service"
COMMON_SLUG_PART = "common"
MAX_FILE_LINES = 1000
NEWLINE = "\n"
STRENUM_NAMES = frozenset({"StrEnum", "enum.StrEnum"})
GENERATE_NEXT_VALUE = "_generate_next_value_"
IGNORE_NAME = "_ignore_"
STAR_IMPORT = "*"
COMMA = ","
SPACE = " "
STATUS_CODES = frozenset(status.value for status in HTTPStatus)
STATUS_PART = "STATUS"
HTTP_PART = "HTTP"
CODE_PART = "CODE"
STATUS_PREFIXES = ("HTTP_STATUS_", "STATUS_CODE_", "HTTP_", "STATUS_")
MAPPED = "Mapped"
RELATIONSHIP = "relationship"
ENVIRON_NAMES = frozenset({"os.environ", "environ"})
ENVIRON_SETDEFAULT = frozenset({"os.environ.setdefault", "environ.setdefault"})
ENV_READ_CALLS = frozenset(
    {"os.environ.get", "environ.get", "os.getenv", "getenv"}
)
STANDARD_ENV_NAMES = frozenset(
    {
        "HOME",
        "PATH",
        "TZ",
        "USER",
        "PWD",
        "LANG",
        "LC_ALL",
        "TMPDIR",
        "TMP",
        "TEMP",
        "CI",
        "NODE_ENV",
        "SHELL",
        "TERM",
        "HOSTNAME",
        "LOGNAME",
        "MODE",
        "DEV",
        "PROD",
        "BASE_URL",
        "SSR",
    }
)
PATCH_NAMES = frozenset({"patch", "mock.patch", "unittest.mock.patch"})
PATCH_OBJECT_NAMES = frozenset(
    {"patch.object", "mock.patch.object", "unittest.mock.patch.object"}
)
MONKEYPATCH_SETATTR = "monkeypatch.setattr"
TIME_MODULE = "time"
TIME_PREFIX = "time."
SUBPROCESS_CALLS = frozenset(
    {
        "subprocess.run",
        "subprocess.call",
        "subprocess.check_call",
        "subprocess.check_output",
    }
)
TIMEOUT_KEYWORD = "timeout"
SESSION_SUFFIX = "session"
SESSION_METHODS = frozenset(
    {"add", "add_all", "execute", "scalar", "scalars", "merge", "delete"}
)
QUERY_BUILDERS = frozenset({"select", "insert", "update", "delete"})
SQL_PACKAGES = frozenset({"sqlalchemy", "sqlmodel"})
SQLALCHEMY = "sqlalchemy"
REPOSITORIES_DIR = "repositories"
SCHEMA_DIRS = frozenset({"migrations", "alembic"})
INIT_FILE = "__init__.py"
FUTURE_MODULE = "__future__"
ALL_NAME = "__all__"
LIBS_DIR = "libs"
PRINT_NAME = "print"
MAIN_NAME = "main"
MAIN_GUARD_NAME = "__name__"
MAIN_GUARD_VALUE = "__main__"
SCRIPT_FILES = frozenset({"__main__.py", "cli.py"})
SCRIPT_DIRS = frozenset({"scripts", "bin", "tools"})
SHEBANG = "#!"
COMMON_TESTS_MODULES = ("common.tests", "libs.common.tests")
SERVICES_DIR = "services"
DATACLASS_NAMES = frozenset({"dataclass", "dataclasses.dataclass"})
EXCEPTION_SUFFIXES = ("Exception", "Error")
ERRORS_FILE = "errors.py"
ERRORS_DIR = "errors"
MODELS_FILE = "models.py"
MODELS_DIR = "models"
BASE_MODEL = "BaseModel"
HOME_PATH = re.compile(r"(?<![\w.])/(?:home|Users)/[^/\s'\"]+/")


class HabitRule(StrEnum):
    """The review habits lint-strict checks, by code."""

    STRENUM_LITERAL = "HAB120"
    HTTP_STATUS_NUMBER = "HAB084"
    RELATIONSHIP_STRING = "HAB091"
    ENVIRON_SETDEFAULT = "HAB051"
    TIME_PATCH = "HAB106"
    SUBPROCESS_TIMEOUT = "HAB052"
    SESSION_OUTSIDE_REPOSITORY = "HAB118"
    INIT_REEXPORT = "HAB077"
    PRINT_CALL = "HAB083"
    COMMON_TESTS_IMPORT = "HAB104"
    SERVICE_DATACLASS = "HAB102"
    MISPLACED_CLASS = "HAB082"
    UNDECLARED_ENV = "HAB092"
    HOME_PATH = "HAB070"
    LINE_LIMIT = "HAB013"
    THEN_ARGUMENTS = "HAB066"
    CATCH_WITHOUT_BINDING = "HAB005"
    API_TYPES_IMPORT = "HAB094"
    DEFAULT_LANGUAGE = "HAB058"
    PLURAL_FORMS = "HAB023"
    AUTOMAT_WORD = "HAB057"


HABIT_MESSAGES = {
    HabitRule.STRENUM_LITERAL: (
        "H120: StrEnum value repeats the member name — use auto()"
    ),
    HabitRule.HTTP_STATUS_NUMBER: (
        "H084: HTTP status as a bare number — use http.HTTPStatus"
    ),
    HabitRule.RELATIONSHIP_STRING: (
        "H091: relationship target as a string — pass the class"
    ),
    HabitRule.ENVIRON_SETDEFAULT: (
        "H051: os.environ.setdefault in a test — use monkeypatch.setenv"
    ),
    HabitRule.TIME_PATCH: (
        "H106: patching the global time module — patch the code's own clock"
    ),
    HabitRule.SUBPROCESS_TIMEOUT: (
        "H052: subprocess call in a test without timeout — pass timeout="
    ),
    HabitRule.SESSION_OUTSIDE_REPOSITORY: (
        "H118: database access outside repositories/ — move it there"
    ),
    HabitRule.INIT_REEXPORT: (
        "H077: re-export in __init__.py — import from the defining module"
    ),
    HabitRule.PRINT_CALL: "H083: print in a module — use a logger",
    HabitRule.COMMON_TESTS_IMPORT: (
        "H104: import of common tests — import from common.testing"
    ),
    HabitRule.SERVICE_DATACLASS: (
        "H102: dataclass in services/ — move the type to models"
    ),
    HabitRule.MISPLACED_CLASS: (
        "H082: exception, enum or model outside errors.py/models.py"
        " — move it there"
    ),
    HabitRule.UNDECLARED_ENV: (
        "H092: environment variable missing from .env.example — add it"
    ),
    HabitRule.HOME_PATH: (
        "H070: hard-coded home directory — build the path from config"
    ),
    HabitRule.LINE_LIMIT: (
        "H013: file grew past 1000 lines — split it into modules"
    ),
    HabitRule.THEN_ARGUMENTS: (
        "H066: .then with two arguments — chain .catch for the rejection"
    ),
    HabitRule.CATCH_WITHOUT_BINDING: (
        "H005: catch without an error binding — name the error and use it"
    ),
    HabitRule.API_TYPES_IMPORT: (
        "H094: import from @/api/types — import the type from @/api"
    ),
    HabitRule.DEFAULT_LANGUAGE: (
        "H058: default_language access — use ui.languages[0]"
    ),
    HabitRule.PLURAL_FORMS: (
        "H023: plural keys incomplete or not mirrored — add every form"
        " in both locales"
    ),
    HabitRule.AUTOMAT_WORD: (
        "H057: the word automat in Polish text — write maszyna"
    ),
}


@dataclass(frozen=True, slots=True)
class HabitHit:
    """A habit violation at a source position."""

    rule: StrEnum
    line: int
    column: int
    message: str


@dataclass(frozen=True, slots=True)
class HabitContext:
    """What the repo says about the file a detector looks at."""

    path: str
    repo_slug: str | None
    env_example_names: frozenset[str] | None
    has_repositories_dir: bool
    old_line_count: int | None


@dataclass(frozen=True, slots=True)
class PythonSource:
    """A parsed Python file with its text and repo context."""

    tree: ast.Module
    text: str
    context: HabitContext


Detector = Callable[[PythonSource], "Iterator[HabitHit]"]


def make_hit(rule: HabitRule, node: ast.stmt | ast.expr) -> HabitHit:
    """Build the hit of a rule at the position of a node."""
    return HabitHit(
        rule, node.lineno, node.col_offset + 1, HABIT_MESSAGES[rule]
    )


def dotted_name(node: ast.AST) -> str:
    """Return a.b.c for a name or attribute chain, else an empty string."""
    if isinstance(node, ast.Name):
        return node.id
    if isinstance(node, ast.Attribute):
        owner = dotted_name(node.value)
        return f"{owner}.{node.attr}" if owner else ""
    return ""


def call_name(node: ast.AST) -> str:
    """Return the dotted name a call invokes, else an empty string."""
    return dotted_name(node.func) if isinstance(node, ast.Call) else ""


def calls(tree: ast.AST) -> Iterator[ast.Call]:
    """Yield every call in the tree."""
    return (node for node in ast.walk(tree) if isinstance(node, ast.Call))


def string_argument(call: ast.Call) -> str | None:
    """Return the first positional argument when it is a str literal."""
    if call.args and isinstance(call.args[0], ast.Constant):
        value = call.args[0].value
        return value if isinstance(value, str) else None
    return None


def named_value(statement: ast.stmt) -> tuple[str, ast.expr] | None:
    """Return the single name and value an assignment binds."""
    if isinstance(statement, ast.Assign) and len(statement.targets) == 1:
        target, value = statement.targets[0], statement.value
    elif isinstance(statement, ast.AnnAssign) and statement.value is not None:
        target, value = statement.target, statement.value
    else:
        return None
    if isinstance(target, ast.Name):
        return target.id, value
    return None


def int_value(node: ast.expr) -> int | None:
    """Return the value of an int literal, else None."""
    if isinstance(node, ast.Constant):
        value = node.value
        if isinstance(value, int) and not isinstance(value, bool):
            return value
    return None


def path_directories(path: str) -> frozenset[str]:
    """Return the directory names of a repo path."""
    return frozenset(PurePosixPath(path).parts[:-1])


def is_plain_strenum(node: ast.ClassDef) -> bool:
    """Tell whether a class is a StrEnum without custom value generation."""
    if len(node.bases) != 1 or dotted_name(node.bases[0]) not in STRENUM_NAMES:
        return False
    return not any(
        isinstance(statement, ast.FunctionDef | ast.AsyncFunctionDef)
        and statement.name == GENERATE_NEXT_VALUE
        for statement in node.body
    )


def literal_names(value: ast.expr) -> frozenset[str]:
    """Return the names a str, list, tuple or set literal spells out."""
    if isinstance(value, ast.Constant) and isinstance(value.value, str):
        return frozenset(value.value.replace(COMMA, SPACE).split())
    if isinstance(value, ast.List | ast.Tuple | ast.Set):
        return frozenset(
            element.value
            for element in value.elts
            if isinstance(element, ast.Constant)
            and isinstance(element.value, str)
        )
    return frozenset()


def ignored_names(node: ast.ClassDef) -> frozenset[str]:
    """Return the names an enum class lists in _ignore_."""
    for statement in node.body:
        pair = named_value(statement)
        if pair is not None and pair[0] == IGNORE_NAME:
            return literal_names(pair[1])
    return frozenset()


def repeats_member_name(statement: ast.stmt, ignored: frozenset[str]) -> bool:
    """Tell whether a member is assigned its own lower-case name."""
    pair = named_value(statement)
    if pair is None:
        return False
    name, value = pair
    return (
        not name.startswith("_")
        and name not in ignored
        and isinstance(value, ast.Constant)
        and value.value == name.lower()
    )


def strenum_hits(source: PythonSource) -> Iterator[HabitHit]:
    """Yield StrEnum members whose value is their own lower-case name."""
    for node in ast.walk(source.tree):
        if isinstance(node, ast.ClassDef) and is_plain_strenum(node):
            ignored = ignored_names(node)
            for statement in node.body:
                if repeats_member_name(statement, ignored):
                    yield make_hit(HabitRule.STRENUM_LITERAL, statement)


def names_status_member(name: str, code: int) -> bool:
    """Tell whether a name, minus its prefix, is the member with the code."""
    member = next(
        (
            name.removeprefix(prefix)
            for prefix in STATUS_PREFIXES
            if name.startswith(prefix)
        ),
        name,
    )
    return member in HTTPStatus.__members__ and HTTPStatus[member] == code


def has_http_status_tokens(name: str) -> bool:
    """Tell whether a name has an HTTP token and a STATUS or CODE token."""
    tokens = set(name.split("_"))
    return HTTP_PART in tokens and bool({STATUS_PART, CODE_PART} & tokens)


def is_status_constant(name: str, value: ast.expr) -> bool:
    """Tell whether a constant is an HTTP status held in a bare int."""
    code = int_value(value)
    if code is None or code not in STATUS_CODES or name != name.upper():
        return False
    return names_status_member(name, code) or has_http_status_tokens(name)


def http_status_hits(source: PythonSource) -> Iterator[HabitHit]:
    """Yield module constants that hold an HTTP status number."""
    for statement in source.tree.body:
        pair = named_value(statement)
        if pair is not None and is_status_constant(*pair):
            yield make_hit(HabitRule.HTTP_STATUS_NUMBER, statement)


def relationship_hits(source: PythonSource) -> Iterator[HabitHit]:
    """Yield Mapped relationships declared with a string target."""
    for node in ast.walk(source.tree):
        if (
            isinstance(node, ast.AnnAssign)
            and isinstance(node.annotation, ast.Subscript)
            and dotted_name(node.annotation.value).endswith(MAPPED)
            and isinstance(node.value, ast.Call)
            and call_name(node.value).endswith(RELATIONSHIP)
            and string_argument(node.value) is not None
        ):
            yield make_hit(HabitRule.RELATIONSHIP_STRING, node)


def environ_setdefault_hits(source: PythonSource) -> Iterator[HabitHit]:
    """Yield os.environ.setdefault calls."""
    for call in calls(source.tree):
        if call_name(call) in ENVIRON_SETDEFAULT:
            yield make_hit(HabitRule.ENVIRON_SETDEFAULT, call)


def patches_time(call: ast.Call) -> bool:
    """Tell whether a call patches the global time module."""
    name = call_name(call)
    if name in PATCH_NAMES or name == MONKEYPATCH_SETATTR:
        target = string_argument(call)
        if target is not None and target.startswith(TIME_PREFIX):
            return True
    if name in PATCH_OBJECT_NAMES or name == MONKEYPATCH_SETATTR:
        return bool(call.args) and dotted_name(call.args[0]) == TIME_MODULE
    return False


def time_patch_hits(source: PythonSource) -> Iterator[HabitHit]:
    """Yield calls that patch the global time module."""
    for call in calls(source.tree):
        if patches_time(call):
            yield make_hit(HabitRule.TIME_PATCH, call)


def lacks_timeout(call: ast.Call) -> bool:
    """Tell whether a call passes neither timeout nor ** options."""
    return all(
        keyword.arg is not None and keyword.arg != TIMEOUT_KEYWORD
        for keyword in call.keywords
    )


def subprocess_timeout_hits(source: PythonSource) -> Iterator[HabitHit]:
    """Yield subprocess calls made without a timeout."""
    for call in calls(source.tree):
        if call_name(call) in SUBPROCESS_CALLS and lacks_timeout(call):
            yield make_hit(HabitRule.SUBPROCESS_TIMEOUT, call)


def receiver_name(node: ast.expr) -> str:
    """Return the last name of an expression, lower-cased."""
    if isinstance(node, ast.Attribute):
        return node.attr.lower()
    return node.id.lower() if isinstance(node, ast.Name) else ""


def is_session_call(call: ast.Call) -> bool:
    """Tell whether a call is a write or query on a session object."""
    function = call.func
    return (
        isinstance(function, ast.Attribute)
        and function.attr in SESSION_METHODS
        and receiver_name(function.value).endswith(SESSION_SUFFIX)
    )


def imports_sql_package(tree: ast.Module) -> bool:
    """Tell whether the module imports sqlalchemy or sqlmodel."""
    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            roots = [alias.name.split(".")[0] for alias in node.names]
        elif isinstance(node, ast.ImportFrom) and node.module:
            roots = [node.module.split(".")[0]]
        else:
            continue
        if SQL_PACKAGES.intersection(roots):
            return True
    return False


def query_builder_names(tree: ast.Module) -> frozenset[str]:
    """Return the local names of select/insert/update/delete."""
    names: set[str] = set()
    for node in ast.walk(tree):
        if (
            isinstance(node, ast.ImportFrom)
            and node.module
            and node.module.split(".")[0] == SQLALCHEMY
        ):
            names.update(
                alias.asname or alias.name
                for alias in node.names
                if alias.name in QUERY_BUILDERS
            )
    return frozenset(names)


def database_access_hits(source: PythonSource) -> Iterator[HabitHit]:
    """Yield database access made outside a repositories directory."""
    context = source.context
    directories = path_directories(context.path)
    if (
        not context.has_repositories_dir
        or REPOSITORIES_DIR in directories
        or SCHEMA_DIRS & directories
        or not imports_sql_package(source.tree)
    ):
        return
    builders = query_builder_names(source.tree)
    for call in calls(source.tree):
        if is_session_call(call) or call_name(call) in builders:
            yield make_hit(HabitRule.SESSION_OUTSIDE_REPOSITORY, call)


def is_reexport_exempt(context: HabitContext) -> bool:
    """Tell whether re-exports are the norm for the file's location."""
    return LIBS_DIR in path_directories(context.path) or COMMON_SLUG_PART in (
        context.repo_slug or ""
    )


def bound_names(node: ast.Import | ast.ImportFrom) -> list[str]:
    """Return the names an import statement binds."""
    if isinstance(node, ast.ImportFrom):
        if node.module == FUTURE_MODULE:
            return []
        return [alias.asname or alias.name for alias in node.names]
    return [alias.asname or alias.name.split(".")[0] for alias in node.names]


def assigns_all(statement: ast.stmt) -> bool:
    """Tell whether a statement assigns the module's __all__."""
    if isinstance(statement, ast.Assign):
        targets = statement.targets
    elif isinstance(statement, ast.AnnAssign | ast.AugAssign):
        targets = [statement.target]
    else:
        return False
    return any(
        isinstance(target, ast.Name) and target.id == ALL_NAME
        for target in targets
    )


def init_reexport_hits(source: PythonSource) -> Iterator[HabitHit]:
    """Yield __all__ assignments and unused imports in an __init__.py."""
    context = source.context
    if PurePosixPath(context.path).name != INIT_FILE:
        return
    if is_reexport_exempt(context):
        return
    used = {
        node.id for node in ast.walk(source.tree) if isinstance(node, ast.Name)
    }
    for node in ast.walk(source.tree):
        if (isinstance(node, ast.stmt) and assigns_all(node)) or (
            isinstance(node, ast.Import | ast.ImportFrom)
            and any(
                name not in used and name != STAR_IMPORT
                for name in bound_names(node)
            )
        ):
            yield make_hit(HabitRule.INIT_REEXPORT, node)


def is_main_guard(statement: ast.stmt) -> bool:
    """Tell whether a statement is if __name__ == "__main__"."""
    if not (
        isinstance(statement, ast.If)
        and isinstance(statement.test, ast.Compare)
        and len(statement.test.comparators) == 1
    ):
        return False
    test = statement.test
    comparator = test.comparators[0]
    return (
        dotted_name(test.left) == MAIN_GUARD_NAME
        and isinstance(comparator, ast.Constant)
        and comparator.value == MAIN_GUARD_VALUE
    )


def defines_main(statement: ast.stmt) -> bool:
    """Tell whether a statement defines a function named main."""
    return (
        isinstance(statement, ast.FunctionDef | ast.AsyncFunctionDef)
        and statement.name == MAIN_NAME
    )


def is_script_module(source: PythonSource) -> bool:
    """Tell whether a module is a script or declares an entry point."""
    path = PurePosixPath(source.context.path)
    return (
        path.name in SCRIPT_FILES
        or bool(SCRIPT_DIRS & path_directories(source.context.path))
        or source.text.startswith(SHEBANG)
        or any(
            is_main_guard(statement) or defines_main(statement)
            for statement in source.tree.body
        )
    )


def print_hits(source: PythonSource) -> Iterator[HabitHit]:
    """Yield print calls in importable modules."""
    if is_script_module(source):
        return
    for call in calls(source.tree):
        if call_name(call) == PRINT_NAME:
            yield make_hit(HabitRule.PRINT_CALL, call)


def imported_modules(node: ast.AST) -> list[str]:
    """Return the dotted modules an import statement refers to."""
    if isinstance(node, ast.Import):
        return [alias.name for alias in node.names]
    if isinstance(node, ast.ImportFrom) and node.module and not node.level:
        return [
            node.module,
            *(f"{node.module}.{alias.name}" for alias in node.names),
        ]
    return []


def is_common_tests_module(module: str) -> bool:
    """Tell whether a dotted module is, or lies under, the common tests."""
    return any(
        module == prefix or module.startswith(f"{prefix}.")
        for prefix in COMMON_TESTS_MODULES
    )


def common_tests_hits(source: PythonSource) -> Iterator[HabitHit]:
    """Yield imports of the shared common tests in cloud-platform."""
    if source.context.repo_slug != CLOUD_REPO:
        return
    for node in ast.walk(source.tree):
        if isinstance(node, ast.stmt) and any(
            map(is_common_tests_module, imported_modules(node))
        ):
            yield make_hit(HabitRule.COMMON_TESTS_IMPORT, node)


def dataclass_decorator(node: ast.ClassDef) -> ast.expr | None:
    """Return the @dataclass decorator of a class, if any."""
    for decorator in node.decorator_list:
        target = (
            decorator.func if isinstance(decorator, ast.Call) else decorator
        )
        if dotted_name(target) in DATACLASS_NAMES:
            return decorator
    return None


def service_dataclass_hits(source: PythonSource) -> Iterator[HabitHit]:
    """Yield dataclasses declared directly under a services directory."""
    context = source.context
    parent = PurePosixPath(context.path).parent.name
    if context.repo_slug != CLOUD_REPO or parent != SERVICES_DIR:
        return
    for node in ast.walk(source.tree):
        if isinstance(node, ast.ClassDef):
            decorator = dataclass_decorator(node)
            if decorator is not None:
                yield make_hit(HabitRule.SERVICE_DATACLASS, decorator)


def base_names(node: ast.ClassDef) -> list[str]:
    """Return the dotted names of a class's bases."""
    return [dotted_name(base) for base in node.bases]


def is_exception_class(node: ast.ClassDef) -> bool:
    """Tell whether a class derives from an exception by name."""
    return any(
        name.rsplit(".", 1)[-1].endswith(EXCEPTION_SUFFIXES)
        for name in base_names(node)
    )


def is_model_class(node: ast.ClassDef) -> bool:
    """Tell whether a class is an enum or a pydantic model by name."""
    return is_enum_class(node) or any(
        name.rsplit(".", 1)[-1] == BASE_MODEL for name in base_names(node)
    )


def misplaced_class_hits(source: PythonSource) -> Iterator[HabitHit]:
    """Yield exception and model classes outside their home module."""
    context = source.context
    if context.repo_slug != DEVICE_REPO:
        return
    path = PurePosixPath(context.path)
    directories = path_directories(context.path)
    in_errors = path.name == ERRORS_FILE or ERRORS_DIR in directories
    in_models = path.name == MODELS_FILE or MODELS_DIR in directories
    for node in ast.walk(source.tree):
        if not isinstance(node, ast.ClassDef):
            continue
        misplaced = (is_exception_class(node) and not in_errors) or (
            is_model_class(node) and not in_models
        )
        if misplaced:
            yield make_hit(HabitRule.MISPLACED_CLASS, node)


def env_variable(node: ast.AST) -> tuple[ast.expr, str] | None:
    """Return the node and name of an environment variable read."""
    if isinstance(node, ast.Call) and call_name(node) in ENV_READ_CALLS:
        name = string_argument(node)
        return None if name is None else (node, name)
    if (
        isinstance(node, ast.Subscript)
        and isinstance(node.ctx, ast.Load)
        and dotted_name(node.value) in ENVIRON_NAMES
        and isinstance(node.slice, ast.Constant)
        and isinstance(node.slice.value, str)
    ):
        return node, node.slice.value
    return None


def undeclared_env_hits(source: PythonSource) -> Iterator[HabitHit]:
    """Yield environment reads missing from the repo's .env.example."""
    declared = source.context.env_example_names
    if declared is None:
        return
    for node in ast.walk(source.tree):
        read = env_variable(node)
        if read is not None and read[1] not in declared | STANDARD_ENV_NAMES:
            yield make_hit(HabitRule.UNDECLARED_ENV, read[0])


def docstring_constants(tree: ast.Module) -> set[int]:
    """Return the ids of constants that stand alone as statements."""
    return {
        id(node.value)
        for node in ast.walk(tree)
        if isinstance(node, ast.Expr) and isinstance(node.value, ast.Constant)
    }


def home_path_hits(source: PythonSource) -> Iterator[HabitHit]:
    """Yield string literals that contain a user home directory."""
    standalone = docstring_constants(source.tree)
    for node in ast.walk(source.tree):
        if (
            isinstance(node, ast.Constant)
            and isinstance(node.value, str)
            and id(node) not in standalone
            and HOME_PATH.search(node.value)
        ):
            yield make_hit(HabitRule.HOME_PATH, node)


COMMON_DETECTORS: tuple[Detector, ...] = (
    strenum_hits,
    http_status_hits,
    relationship_hits,
    init_reexport_hits,
    common_tests_hits,
)
TEST_DETECTORS: tuple[Detector, ...] = (
    environ_setdefault_hits,
    time_patch_hits,
    subprocess_timeout_hits,
)
PRODUCTION_DETECTORS: tuple[Detector, ...] = (
    database_access_hits,
    print_hits,
    service_dataclass_hits,
    misplaced_class_hits,
    undeclared_env_hits,
    home_path_hits,
)


def python_habit_hits(
    tree: ast.Module,
    text: str,
    changed: frozenset[int],
    context: HabitContext,
) -> list[HabitHit]:
    """Return the habit hits of a Python file on its changed lines."""
    source = PythonSource(tree, text, context)
    group = (
        TEST_DETECTORS
        if static_is_test(context.path)
        else PRODUCTION_DETECTORS
    )
    hits = {
        hit
        for detector in (*COMMON_DETECTORS, *group)
        for hit in detector(source)
        if hit.line in changed
    }
    return sorted(hits, key=lambda hit: (hit.line, hit.column, hit.rule))


def line_count(text: str) -> int:
    """Count lines the way git numbers them."""
    return text.count(NEWLINE) + (not text.endswith(NEWLINE) and bool(text))


def line_count_hits(text: str, context: HabitContext) -> list[HabitHit]:
    """Return a hit when a non-test file grows past the line limit."""
    if static_is_test(context.path):
        return []
    was_over = (
        context.old_line_count is not None
        and context.old_line_count > MAX_FILE_LINES
    )
    if was_over or line_count(text) <= MAX_FILE_LINES:
        return []
    return [
        HabitHit(
            HabitRule.LINE_LIMIT,
            MAX_FILE_LINES + 1,
            1,
            HABIT_MESSAGES[HabitRule.LINE_LIMIT],
        )
    ]
