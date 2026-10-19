import fnmatch
import re
from collections.abc import Sequence
from pathlib import Path
from urllib.parse import urlsplit

from agy_errors import fail
from agy_workspace import TEXT_ENCODING, path_from_env, run_git

ALLOWLIST_ENV = "AGY_ALLOWLIST"
ALLOWLIST_FILE = "allowed-remotes.txt"
URL_SCHEME_SEPARATOR = "://"
SCP_SEPARATOR = ":"
PATH_SEPARATOR = "/"
GIT_SUFFIX = ".git"
REMOTE_SCHEMES = frozenset({"https", "ssh", "git"})
HOST_PATTERN = re.compile(r"[a-z0-9]([a-z0-9.-]*[a-z0-9])?")
SEGMENT_PATTERN = re.compile(r"[A-Za-z0-9._-]+")
FORBIDDEN_URL_CHARS = re.compile(r"[\s\x00-\x1f\x7f\\]")
OWNER_AND_REPO = 2
DOT_SEGMENTS = frozenset({".", ".."})
COMMENT_PREFIX = "#"


def split_scheme_url(text: str) -> tuple[str, str] | None:
    """Return host and path of a URL with a scheme, if it is acceptable."""
    try:
        parts = urlsplit(text)
    except ValueError:
        return None
    if parts.scheme.lower() not in REMOTE_SCHEMES:
        return None
    if parts.query or parts.fragment:
        return None
    return parts.hostname or "", parts.path


def split_scp_url(text: str) -> tuple[str, str] | None:
    """Return host and path of an scp-like remote, if it is one."""
    head, separator, path = text.partition(SCP_SEPARATOR)
    if not separator or PATH_SEPARATOR in head:
        return None
    return head.rpartition("@")[2], path


def valid_segment(segment: str) -> bool:
    """Tell whether a path segment is a plain owner or repo name."""
    return segment not in DOT_SEGMENTS and bool(
        SEGMENT_PATTERN.fullmatch(segment)
    )


def normalise_remote(url: str) -> str | None:
    """Reduce a git remote URL to host/owner/repo, or None if unusable."""
    text = url.strip()
    if not text or FORBIDDEN_URL_CHARS.search(text):
        return None
    if URL_SCHEME_SEPARATOR in text:
        split = split_scheme_url(text)
    else:
        split = split_scp_url(text)
    if split is None:
        return None
    host = split[0].lower()
    segments = [part for part in split[1].split(PATH_SEPARATOR) if part]
    if len(segments) != OWNER_AND_REPO or not HOST_PATTERN.fullmatch(host):
        return None
    owner, repo = segments[0], segments[1].removesuffix(GIT_SUFFIX)
    if not (valid_segment(owner) and valid_segment(repo)):
        return None
    return f"{host}{PATH_SEPARATOR}{owner}{PATH_SEPARATOR}{repo}"


def load_allowlist() -> list[str]:
    """Read the allowed remote patterns; an unreadable file denies all."""
    default = Path(__file__).resolve().parent / ALLOWLIST_FILE
    path = path_from_env(ALLOWLIST_ENV, default)
    try:
        lines = path.read_text(encoding=TEXT_ENCODING).splitlines()
    except OSError as error:
        fail(
            f"allowlist file {path} is unreadable ({error.strerror}); "
            "refusing to send any repository"
        )
    stripped = (line.strip() for line in lines)
    return [
        line
        for line in stripped
        if line and not line.startswith(COMMENT_PREFIX)
    ]


def is_allowed(normalised: str, patterns: Sequence[str]) -> bool:
    """Tell whether a normalised remote matches an allowlist pattern."""
    return any(
        fnmatch.fnmatchcase(normalised, pattern) for pattern in patterns
    )


def remote_urls(root: Path) -> list[tuple[str, str]]:
    """List every fetch and push URL of every remote."""
    found: dict[tuple[str, str], None] = {}
    for name in run_git(root, ["remote"]).split():
        for extra in ([], ["--push"]):
            listing = run_git(
                root, ["remote", "get-url", *extra, "--all", name]
            )
            for url in listing.splitlines():
                found[(name, url)] = None
    return list(found)


def require_allowlisted(root: Path) -> None:
    """Refuse a repository unless every remote is on the allowlist."""
    remotes = remote_urls(root)
    if not remotes:
        fail(
            "the repository has no remote, so it cannot be shown to be "
            "allowlisted"
        )
    patterns = load_allowlist()
    for name, url in remotes:
        normalised = normalise_remote(url)
        if normalised is None:
            fail(
                f"remote '{name}' has a URL that cannot be parsed into "
                "host/owner/repo"
            )
        if not is_allowed(normalised, patterns):
            fail(f"remote '{name}' ({normalised}) is not allowlisted")
