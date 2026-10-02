"""Which files are code and which comment syntax they use, shared by the hooks."""
import os
from enum import Enum

SHEBANG = "#!"
PYTHON_MARK = "python"


class Language(Enum):
    PYTHON = "python"
    C_LIKE = "c_like"
    HASH = "hash"
    DASH = "dash"


SUFFIXES = {
    Language.PYTHON: frozenset({"py", "pyi", "ipynb"}),
    Language.C_LIKE: frozenset({
        "ts", "tsx", "js", "jsx", "mjs", "cjs", "go", "rs", "c", "h", "cc", "cpp", "cxx", "hpp", "hh", "java",
        "kt", "kts", "cs", "swift", "scala", "dart", "m", "mm", "php", "vue", "svelte", "ino",
    }),
    Language.HASH: frozenset({"sh", "bash", "rb", "ex", "exs"}),
    Language.DASH: frozenset({"sql", "lua"}),
}
CODE_SUFFIXES = frozenset().union(*SUFFIXES.values())


def suffix_of(path):
    stem, dot, suffix = os.path.basename(path).rpartition(".")
    return suffix.lower() if dot and stem else None


def first_line(content):
    return content.split("\n", 1)[0]


def language_of(path, content):
    suffix = suffix_of(path)
    if suffix is not None:
        return next((language for language, suffixes in SUFFIXES.items() if suffix in suffixes), None)
    line = first_line(content)
    if not line.startswith(SHEBANG):
        return None
    return Language.PYTHON if PYTHON_MARK in line else Language.HASH
