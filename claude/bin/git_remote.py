from __future__ import annotations

import subprocess
from pathlib import Path
from urllib.parse import urlsplit

GIT = "git"
ORIGIN = "origin"
URL_SCHEME_SEPARATOR = "://"
SCP_SEPARATOR = ":"
GIT_SUFFIX = ".git"
PATH_SEPARATOR = "/"
OWNER_AND_SLUG = 2


def git_output(repo: Path, *args: str) -> str | None:
    """Run git in repo and return stdout, or None when it fails."""
    try:
        result = subprocess.run(
            [GIT, "-C", str(repo), *args],
            capture_output=True,
            text=True,
            check=False,
        )
    except OSError:
        return None
    if result.returncode:
        return None
    return result.stdout


def parse_remote_slug(url: str) -> str | None:
    """Return <workspace>/<slug> from an ssh, scp-like or https remote."""
    text = url.strip()
    if URL_SCHEME_SEPARATOR in text:
        path = urlsplit(text).path
    elif SCP_SEPARATOR in text:
        path = text.split(SCP_SEPARATOR, 1)[1]
    else:
        return None
    parts = [
        part
        for part in path.strip(PATH_SEPARATOR).split(PATH_SEPARATOR)
        if part
    ]
    if len(parts) < OWNER_AND_SLUG:
        return None
    owner, slug = parts[-OWNER_AND_SLUG:]
    slug = slug.removesuffix(GIT_SUFFIX)
    if not slug:
        return None
    return f"{owner}{PATH_SEPARATOR}{slug}"


def origin_slug(root: Path) -> str | None:
    """Return the <workspace>/<slug> of the origin remote, if any."""
    remote = git_output(root, "remote", "get-url", ORIGIN)
    return parse_remote_slug(remote) if remote else None
