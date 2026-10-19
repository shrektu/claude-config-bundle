from __future__ import annotations

import bisect
import json
import re
from dataclasses import dataclass
from pathlib import PurePosixPath

from habit_rules import HABIT_MESSAGES, HabitContext, HabitHit, HabitRule

LOCALE_DIRS = frozenset({"locales", "locale", "i18n"})
LANGUAGE_TAG = re.compile(r"[a-z]{2}(?:-[A-Z]{2})?")
PLURAL_SUFFIX = re.compile(r"_(zero|one|two|few|many|other)$")
COUNT_PLACEHOLDER = re.compile(r"\{\{\s*count\s*\}\}")
AUTOMAT_WORD = re.compile(
    r"\bautoma(?:t|tu|towi|tem|cie|ty|tów|tom|tami|tach)\b", re.IGNORECASE
)
POLISH = "pl"
ENGLISH = "en"
SIBLINGS = {POLISH: ENGLISH, ENGLISH: POLISH}
REQUIRED_FORMS = {
    POLISH: frozenset({"one", "few", "many"}),
    ENGLISH: frozenset({"one", "other"}),
}
AUTOMAT_REPOS = frozenset(
    {"acme/web-ui", "acme/service-menu-ui"}
)
JSON_TOKEN = re.compile(r'"(?:\\.|[^"\\])*"|[{}\[\],:]|[^\s{}\[\],:"]+')
NEWLINE_PATTERN = "\n"
STRING_QUOTE = '"'
OBJECT_OPEN = "{"
OBJECT_CLOSE = "}"
ARRAY_OPEN = "["
ARRAY_CLOSE = "]"
SEPARATOR = ","
KEY_SEPARATOR = "."
FIRST_COLUMN = 1
FIRST_LINE = 1
MIN_FAMILY_FORMS = 2


@dataclass(frozen=True, slots=True)
class LocaleEntry:
    """One translation key, the line it sits on and its string value."""

    key: str
    line: int
    value: str | None
    value_line: int


@dataclass(frozen=True, slots=True)
class LocaleDocument:
    """A parsed locale file."""

    language: str
    path: str
    entries: tuple[LocaleEntry, ...]


@dataclass(frozen=True, slots=True)
class JsonToken:
    """A JSON token and the line it starts on."""

    text: str
    line: int


class LocaleWalker:
    """Walks the tokens of valid JSON, collecting every leaf with its line."""

    def __init__(self, tokens: list[JsonToken]) -> None:
        """Start a walk over the tokens."""
        self.tokens = tokens
        self.position = 0
        self.entries: list[LocaleEntry] = []

    def next(self) -> JsonToken:
        """Consume and return the next token."""
        token = self.tokens[self.position]
        self.position += 1
        return token

    def peek(self) -> JsonToken:
        """Return the next token without consuming it."""
        return self.tokens[self.position]

    def walk_value(self, key: str, line: int) -> None:
        """Walk the value that follows a key sitting on a line."""
        token = self.next()
        if token.text == OBJECT_OPEN:
            self.walk_object(key)
        elif token.text == ARRAY_OPEN:
            self.walk_array(key)
        else:
            value = (
                json.loads(token.text)
                if token.text.startswith(STRING_QUOTE)
                else None
            )
            self.entries.append(LocaleEntry(key, line, value, token.line))

    def walk_object(self, prefix: str) -> None:
        """Walk the members of an object."""
        while (token := self.next()).text != OBJECT_CLOSE:
            if token.text == SEPARATOR:
                continue
            name = json.loads(token.text)
            self.next()
            key = f"{prefix}{KEY_SEPARATOR}{name}" if prefix else name
            self.walk_value(key, token.line)

    def walk_array(self, prefix: str) -> None:
        """Walk the items of an array."""
        index = 0
        while self.peek().text != ARRAY_CLOSE:
            if self.peek().text == SEPARATOR:
                self.next()
                continue
            key = f"{prefix}{KEY_SEPARATOR}{index}"
            self.walk_value(key, self.peek().line)
            index += 1
        self.next()


def json_tokens(text: str) -> list[JsonToken]:
    """Split JSON text into tokens with their line numbers."""
    starts = [match.end() for match in re.finditer(NEWLINE_PATTERN, text)]
    return [
        JsonToken(
            match.group(),
            bisect.bisect_right(starts, match.start()) + FIRST_LINE,
        )
        for match in JSON_TOKEN.finditer(text)
    ]


def locale_anchor(parts: list[str] | tuple[str, ...]) -> int:
    """Return the index of the last locale directory, -1 without one."""
    return max(
        (i for i, part in enumerate(parts) if part in LOCALE_DIRS),
        default=-1,
    )


def language_tag(path: str) -> str | None:
    """Return the language of a locale file from its path."""
    pure = PurePosixPath(path)
    parts = pure.parts[:-1]
    for candidate in (*parts[locale_anchor(parts) + 1 :], pure.stem):
        if LANGUAGE_TAG.fullmatch(candidate):
            return candidate
    return None


def parse_locale(path: str, text: str) -> LocaleDocument | None:
    """Parse a locale file, None when it is not a JSON object."""
    try:
        data = json.loads(text)
        if not isinstance(data, dict):
            return None
        walker = LocaleWalker(json_tokens(text))
        walker.walk_value("", FIRST_LINE)
    except (ValueError, RecursionError):
        return None
    return LocaleDocument(
        language_tag(path) or "", path, tuple(walker.entries)
    )


def sibling_path(path: str, language: str) -> str | None:
    """Return the path of the other language's file, None without one."""
    other = SIBLINGS.get(language)
    if other is None:
        return None
    pure = PurePosixPath(path)
    parts = list(pure.parts)
    for index in range(locale_anchor(parts[:-1]) + 1, len(parts) - 1):
        if parts[index] == language:
            parts[index] = other
            return str(PurePosixPath(*parts))
    if pure.stem == language:
        return str(pure.with_name(f"{other}{pure.suffix}"))
    return None


def base_key(key: str) -> str:
    """Return a key without its plural suffix."""
    return PLURAL_SUFFIX.sub("", key)


def plural_form(key: str) -> str | None:
    """Return the plural form a key ends with, if any."""
    match = PLURAL_SUFFIX.search(key)
    return match.group(1) if match else None


def locale_hit(rule: HabitRule, line: int) -> HabitHit:
    """Build the hit of a rule at a line."""
    return HabitHit(rule, line, FIRST_COLUMN, HABIT_MESSAGES[rule])


def reported_line(entry: LocaleEntry, changed: frozenset[int]) -> int | None:
    """Return the changed line of an entry a value rule reports on."""
    if entry.value_line in changed:
        return entry.value_line
    return entry.line if entry.line in changed else None


def is_plural_family(members: list[LocaleEntry]) -> bool:
    """Tell whether keys sharing a base are really plural forms."""
    forms = {plural_form(member.key) for member in members}
    return len(forms) >= MIN_FAMILY_FORMS or any(
        member.value and COUNT_PLACEHOLDER.search(member.value)
        for member in members
    )


def plural_families(
    entries: tuple[LocaleEntry, ...],
) -> dict[str, list[LocaleEntry]]:
    """Group plural-suffixed keys by base, keeping real families only."""
    groups: dict[str, list[LocaleEntry]] = {}
    for entry in entries:
        if plural_form(entry.key) is not None:
            groups.setdefault(base_key(entry.key), []).append(entry)
    return {
        base: members
        for base, members in groups.items()
        if is_plural_family(members)
    }


def parity_key(
    entry: LocaleEntry, families: dict[str, list[LocaleEntry]]
) -> str:
    """Return the key an entry is compared by across languages."""
    base = base_key(entry.key)
    return base if base in families else entry.key


def count_without_plural_hits(
    entries: tuple[LocaleEntry, ...], changed: frozenset[int]
) -> list[HabitHit]:
    """Return hits for {{count}} values whose key has no plural form."""
    lines = (
        reported_line(entry, changed)
        for entry in entries
        if entry.value
        and COUNT_PLACEHOLDER.search(entry.value)
        and plural_form(entry.key) is None
    )
    return [
        locale_hit(HabitRule.PLURAL_FORMS, line)
        for line in lines
        if line is not None
    ]


def missing_form_hits(document: LocaleDocument) -> list[HabitHit]:
    """Return hits for plural families that lack a required form."""
    required = REQUIRED_FORMS.get(document.language)
    if required is None:
        return []
    families = plural_families(document.entries)
    return [
        locale_hit(HabitRule.PLURAL_FORMS, entry.line)
        for members in families.values()
        if required - {plural_form(member.key) for member in members}
        for entry in members
    ]


def missing_in_sibling_hits(
    document: LocaleDocument, sibling: LocaleDocument | None
) -> list[HabitHit]:
    """Return hits for keys the other language's file lacks."""
    if sibling is None or document.language not in SIBLINGS:
        return []
    own = plural_families(document.entries)
    other = plural_families(sibling.entries)
    known = {parity_key(entry, other) for entry in sibling.entries}
    return [
        locale_hit(HabitRule.PLURAL_FORMS, entry.line)
        for entry in document.entries
        if parity_key(entry, own) not in known
    ]


def automat_hits(
    document: LocaleDocument,
    context: HabitContext,
    changed: frozenset[int],
) -> list[HabitHit]:
    """Return hits for Polish values that use the word automat."""
    if document.language != POLISH or context.repo_slug not in AUTOMAT_REPOS:
        return []
    lines = (
        reported_line(entry, changed)
        for entry in document.entries
        if entry.value and AUTOMAT_WORD.search(entry.value)
    )
    return [
        locale_hit(HabitRule.AUTOMAT_WORD, line)
        for line in lines
        if line is not None
    ]


def locale_habit_hits(
    document: LocaleDocument,
    changed: frozenset[int],
    context: HabitContext,
    sibling: LocaleDocument | None,
) -> list[HabitHit]:
    """Return the habit hits of a locale file on its changed lines."""
    found = {
        *count_without_plural_hits(document.entries, changed),
        *missing_form_hits(document),
        *missing_in_sibling_hits(document, sibling),
        *automat_hits(document, context, changed),
    }
    hits = [hit for hit in found if hit.line in changed]
    return sorted(hits, key=lambda hit: (hit.line, hit.rule))
