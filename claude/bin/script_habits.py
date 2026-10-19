from __future__ import annotations

from dataclasses import dataclass
from typing import TYPE_CHECKING

from habit_rules import (
    HABIT_MESSAGES,
    HOME_PATH,
    STANDARD_ENV_NAMES,
    HabitContext,
    HabitHit,
    HabitRule,
)
from source_lexer import Token, TokenKind, static_is_test

if TYPE_CHECKING:
    from collections.abc import Iterator
    from enum import StrEnum

UI_REPO = "acme/web-ui"
CLK_REPOS = frozenset({"acme/kiosk-ui", "acme/service-menu-ui"})
THEN_ARGUMENT_COUNT = 2
OPENING = "([{"
CLOSING = ")]}"
DOT = "."
ANGLE_OPEN = "<"
COMMA = ","
THEN = "then"
CATCH = "catch"
NO_PARAMETER_FUNCTION = ("function", "(", ")")
NO_PARAMETER_ARROW = ("(", ")", "=", ">")
API_TYPES_PREFIX = "@/api/types"
IMPORT_KEYWORDS = frozenset({"from", "import"})
IMPORT_CALLS = frozenset({"import", "require"})
DEFAULT_LANGUAGE_NAME = "default_language"
PROCESS_ENV = ("process", ".", "env")
META_ENV = ("import", ".", "meta", ".", "env")
ENV_PREFIXES = (PROCESS_ENV, META_ENV)
QUOTES = "\"'"
MIN_QUOTED_LENGTH = 2


@dataclass(frozen=True, slots=True)
class ScriptSource:
    """The code tokens of a JavaScript or TypeScript file and its context."""

    code: list[Token]
    context: HabitContext


def located_hit(rule: StrEnum, token: Token, message: str) -> HabitHit:
    """Build a hit with a message at the position of a token."""
    return HabitHit(rule, token.line, token.column, message)


def token_hit(rule: HabitRule, token: Token) -> HabitHit:
    """Build the hit of a rule at the position of a token."""
    return located_hit(rule, token, HABIT_MESSAGES[rule])


def is_punct(token: Token | None, text: str) -> bool:
    """Tell whether a token is the given punctuation."""
    return (
        token is not None
        and token.kind is TokenKind.PUNCT
        and token.text == text
    )


def is_ident(token: Token | None, text: str) -> bool:
    """Tell whether a token is the given identifier."""
    return (
        token is not None
        and token.kind is TokenKind.IDENT
        and token.text == text
    )


def at(code: list[Token], index: int) -> Token | None:
    """Return the token at an index, None outside the list."""
    return code[index] if 0 <= index < len(code) else None


def unquoted(token: Token) -> str | None:
    """Return the contents of a quoted string token."""
    text = token.text
    if (
        token.kind is TokenKind.STRING
        and len(text) >= MIN_QUOTED_LENGTH
        and text[0] in QUOTES
        and text[0] == text[-1]
    ):
        return text[1:-1]
    return None


def texts(code: list[Token], start: int, length: int) -> tuple[str, ...]:
    """Return the texts of length tokens from start."""
    return tuple(token.text for token in code[start : start + length])


def closing_index(code: list[Token], opening: int) -> int | None:
    """Return the index of the bracket that closes the one at opening."""
    depth = 0
    for index in range(opening, len(code)):
        token = code[index]
        if token.kind is not TokenKind.PUNCT:
            continue
        depth += token.text in OPENING
        depth -= token.text in CLOSING
        if depth == 0:
            return index
    return None


def argument_count(code: list[Token], opening: int, closing: int) -> int:
    """Count the top-level arguments of a call, ignoring a trailing comma."""
    depth = 0
    filled = False
    count = 0
    for token in code[opening + 1 : closing]:
        if token.kind is TokenKind.PUNCT:
            depth += token.text in OPENING
            depth -= token.text in CLOSING
            if depth == 0 and token.text == COMMA:
                count += filled
                filled = False
                continue
        filled = True
    return count + filled


def has_top_level_angle(code: list[Token], opening: int, closing: int) -> bool:
    """Tell whether a < appears directly inside a call's arguments."""
    depth = 0
    for token in code[opening + 1 : closing]:
        if token.kind is not TokenKind.PUNCT:
            continue
        depth += token.text in OPENING
        depth -= token.text in CLOSING
        if depth == 0 and token.text == ANGLE_OPEN:
            return True
    return False


def method_calls(code: list[Token], name: str) -> Iterator[int]:
    """Yield the index of the ( of every .name( call."""
    for index, token in enumerate(code):
        if (
            is_ident(token, name)
            and is_punct(at(code, index - 1), DOT)
            and is_punct(at(code, index + 1), "(")
        ):
            yield index + 1


def then_hits(source: ScriptSource) -> Iterator[HabitHit]:
    """Yield .then calls given a fulfilment and a rejection handler."""
    code = source.code
    for opening in method_calls(code, THEN):
        closing = closing_index(code, opening)
        if (
            closing is not None
            and not has_top_level_angle(code, opening, closing)
            and argument_count(code, opening, closing) == THEN_ARGUMENT_COUNT
        ):
            yield token_hit(HabitRule.THEN_ARGUMENTS, code[opening - 1])


def has_no_parameters(code: list[Token], start: int) -> bool:
    """Tell whether the tokens at start open a zero-parameter function."""
    return (
        texts(code, start, len(NO_PARAMETER_FUNCTION))
        == (NO_PARAMETER_FUNCTION)
        or texts(code, start, len(NO_PARAMETER_ARROW)) == NO_PARAMETER_ARROW
    )


def catch_hits(source: ScriptSource) -> Iterator[HabitHit]:
    """Yield catch clauses and handlers that take no error."""
    code = source.code
    for index, token in enumerate(code):
        if is_ident(token, CATCH) and is_punct(at(code, index + 1), "{"):
            yield token_hit(HabitRule.CATCH_WITHOUT_BINDING, token)
    for opening in method_calls(code, CATCH):
        if has_no_parameters(code, opening + 1):
            yield token_hit(HabitRule.CATCH_WITHOUT_BINDING, code[opening - 1])


def is_import_specifier(code: list[Token], index: int) -> bool:
    """Tell whether a string token is a module specifier."""
    before = at(code, index - 1)
    if before is not None and before.text in IMPORT_KEYWORDS:
        return before.kind is TokenKind.IDENT
    caller = at(code, index - 2)
    return (
        is_punct(before, "(")
        and caller is not None
        and caller.kind is TokenKind.IDENT
        and caller.text in IMPORT_CALLS
    )


def is_api_types(value: str) -> bool:
    """Tell whether a specifier is the API types alias or lies under it."""
    return value == API_TYPES_PREFIX or value.startswith(
        f"{API_TYPES_PREFIX}/"
    )


def api_types_hits(source: ScriptSource) -> Iterator[HabitHit]:
    """Yield imports from the shared API types alias."""
    if source.context.repo_slug != UI_REPO:
        return
    for index, token in enumerate(source.code):
        value = unquoted(token)
        if (
            value is not None
            and is_api_types(value)
            and is_import_specifier(source.code, index)
        ):
            yield token_hit(HabitRule.API_TYPES_IMPORT, token)


def default_language_hits(source: ScriptSource) -> Iterator[HabitHit]:
    """Yield uses of the default_language setting."""
    if source.context.repo_slug not in CLK_REPOS:
        return
    for index, token in enumerate(source.code):
        is_access = is_ident(token, DEFAULT_LANGUAGE_NAME) and is_punct(
            at(source.code, index - 1), DOT
        )
        if is_access or unquoted(token) == DEFAULT_LANGUAGE_NAME:
            yield token_hit(HabitRule.DEFAULT_LANGUAGE, token)


def env_name_at(code: list[Token], start: int) -> Token | None:
    """Return the token naming the variable read after an env prefix."""
    if is_punct(at(code, start), DOT):
        name = at(code, start + 1)
        return (
            name if name is not None and name.kind is TokenKind.IDENT else None
        )
    if is_punct(at(code, start), "[") and is_punct(at(code, start + 2), "]"):
        name = at(code, start + 1)
        return name if name is not None and unquoted(name) else None
    return None


def env_reads(code: list[Token]) -> Iterator[tuple[Token, str]]:
    """Yield the token and variable name of every environment read."""
    for index in range(len(code)):
        for prefix in ENV_PREFIXES:
            if texts(code, index, len(prefix)) != prefix:
                continue
            if is_punct(at(code, index - 1), DOT):
                continue
            name = env_name_at(code, index + len(prefix))
            if name is not None:
                yield name, unquoted(name) or name.text


def undeclared_env_hits(source: ScriptSource) -> Iterator[HabitHit]:
    """Yield environment reads missing from the repo's .env.example."""
    declared = source.context.env_example_names
    if declared is None:
        return
    for token, name in env_reads(source.code):
        if name not in declared | STANDARD_ENV_NAMES:
            yield token_hit(HabitRule.UNDECLARED_ENV, token)


def home_path_hits(source: ScriptSource) -> Iterator[HabitHit]:
    """Yield string literals that contain a user home directory."""
    for token in source.code:
        if token.kind is TokenKind.STRING and HOME_PATH.search(token.text):
            yield token_hit(HabitRule.HOME_PATH, token)


def script_habit_hits(
    tokens: list[Token],
    changed: frozenset[int],
    context: HabitContext,
) -> list[HabitHit]:
    """Return the habit hits of a script file on its changed lines."""
    source = ScriptSource(
        [token for token in tokens if token.kind is not TokenKind.COMMENT],
        context,
    )
    detectors = [then_hits, catch_hits, api_types_hits, default_language_hits]
    if not static_is_test(context.path):
        detectors += [undeclared_env_hits, home_path_hits]
    hits = {
        hit
        for detector in detectors
        for hit in detector(source)
        if hit.line in changed
    }
    return sorted(hits, key=lambda hit: (hit.line, hit.column, hit.rule))
