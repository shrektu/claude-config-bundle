from collections.abc import Callable
from pathlib import Path

import agy_remotes
import pytest
from helpers_test import FOREIGN_URL, FakeAgy, git, make_repo, plan_review
from hypothesis import given, settings
from hypothesis import strategies as st

SHIPPED_ALLOWLIST = (
    (Path(agy_remotes.__file__).parent / "allowed-remotes.txt")
    .read_text()
    .split()
)
NAME_STRATEGY = st.from_regex(
    r"[A-Za-z0-9][A-Za-z0-9_-]{0,15}", fullmatch=True
)
HOST_STRATEGY = st.sampled_from(["github.com", "bitbucket.org"])
HOST_CASE_STRATEGY = st.sampled_from(
    [str.lower, str.upper, str.title, str.swapcase]
)


def shipped_allows(url: str) -> bool:
    normalised = agy_remotes.normalise_remote(url)
    return normalised is not None and agy_remotes.is_allowed(
        normalised, SHIPPED_ALLOWLIST
    )


@pytest.mark.parametrize(
    ("url", "expected"),
    [
        ("git@github.com:acme/widgets.git", "github.com/acme/widgets"),
        ("https://github.com/acme/widgets", "github.com/acme/widgets"),
        (
            "https://user:pw@GitHub.COM/acme/widgets.git/",
            "github.com/acme/widgets",
        ),
        (
            "ssh://git@bitbucket.org:7999/acme/widgets.git",
            "bitbucket.org/acme/widgets",
        ),
        ("/srv/git/widgets.git", None),
        ("file:///github.com/acme/widgets", None),
        ("https://github.com/acme", None),
        ("https://github.com/acme/widgets/extra", None),
        ("https://github.com/acme/widgets?x=1", None),
        ("https://github.com\\@evil.com/acme/widgets", None),
        ("git@github.com:../widgets", None),
        ("", None),
    ],
)
def test_normalise_remote_forms(url: str, expected: str | None) -> None:
    assert agy_remotes.normalise_remote(url) == expected


def test_allowlist_matching_uses_host_owner_repo_patterns() -> None:
    patterns = ["github.com/*", "bitbucket.org/acme/*"]

    assert agy_remotes.is_allowed("github.com/acme/widgets", patterns)
    assert agy_remotes.is_allowed("bitbucket.org/acme/widgets", patterns)
    assert not agy_remotes.is_allowed("bitbucket.org/other/widgets", patterns)
    assert not agy_remotes.is_allowed("gitlab.com/acme/widgets", patterns)


def test_load_allowlist_skips_comments_and_blank_lines(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    allowlist = tmp_path / "list.txt"
    allowlist.write_text("# note\n\n  github.com/*  \nbitbucket.org/*\n")
    monkeypatch.setenv("AGY_ALLOWLIST", str(allowlist))

    assert agy_remotes.load_allowlist() == ["github.com/*", "bitbucket.org/*"]


def test_shipped_allowlist_lists_github_and_bitbucket_only() -> None:
    assert SHIPPED_ALLOWLIST == ["github.com/*", "bitbucket.org/*"]


def test_repo_without_remote_unavailable(
    fake_agy: FakeAgy, allowlisted_repo: Path
) -> None:
    git(allowlisted_repo, "remote", "remove", "origin")

    result = plan_review(allowlisted_repo)

    assert result.startswith("AGY-UNAVAILABLE: ")
    assert "no remote" in result
    assert not fake_agy.ran()


def test_one_foreign_remote_among_allowed_ones_denies(
    fake_agy: FakeAgy, allowlisted_repo: Path
) -> None:
    git(allowlisted_repo, "remote", "add", "mirror", FOREIGN_URL)

    result = plan_review(allowlisted_repo)

    assert result.startswith("AGY-UNAVAILABLE: ")
    assert "remote 'mirror' (gitlab.com/acme/widgets)" in result
    assert not fake_agy.ran()


def test_unparseable_remote_denies_without_leaking_credentials(
    fake_agy: FakeAgy, tmp_path: Path
) -> None:
    repo = make_repo(tmp_path / "local", "/srv/git/widgets.git")

    result = plan_review(repo)

    assert result.startswith("AGY-UNAVAILABLE: ")
    assert "cannot be parsed" in result
    assert not fake_agy.ran()


def test_missing_allowlist_denies(
    fake_agy: FakeAgy,
    allowlisted_repo: Path,
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setenv("AGY_ALLOWLIST", str(tmp_path / "absent.txt"))

    result = plan_review(allowlisted_repo)

    assert result.startswith("AGY-UNAVAILABLE: ")
    assert "allowlist file" in result
    assert "unreadable" in result
    assert not fake_agy.ran()


@settings(max_examples=200, deadline=None)
@given(
    host=HOST_STRATEGY,
    owner=NAME_STRATEGY,
    repo=NAME_STRATEGY,
    change_case=HOST_CASE_STRATEGY,
)
def test_normalise_equivalent_forms(
    host: str, owner: str, repo: str, change_case: Callable[[str], str]
) -> None:
    shown = change_case(host)
    forms = [
        f"git@{shown}:{owner}/{repo}.git",
        f"{shown}:{owner}/{repo}",
        f"https://{shown}/{owner}/{repo}",
        f"https://{shown}/{owner}/{repo}.git",
        f"https://{shown}/{owner}/{repo}.git/",
        f"https://user:pw@{shown}/{owner}/{repo}.git",
        f"ssh://git@{shown}:22/{owner}/{repo}.git",
        f"ssh://git@{shown}/{owner}/{repo}/",
        f"git://{shown}/{owner}/{repo}.git",
    ]

    assert {agy_remotes.normalise_remote(form) for form in forms} == {
        f"{host}/{owner}/{repo}"
    }


@settings(max_examples=200, deadline=None)
@given(owner=NAME_STRATEGY, repo=NAME_STRATEGY)
def test_lookalike_hosts_never_allowed(owner: str, repo: str) -> None:
    lookalikes = [
        f"https://github.com.evil.com/{owner}/{repo}",
        f"https://evil.com/github.com/{owner}/{repo}",
        f"https://evil.com/github.com/{owner}",
        f"https://user@github.com@evil.com/{owner}/{repo}",
        f"git@github.com@evil.com:{owner}/{repo}",
        f"https://github.com:443@evil.com/{owner}/{repo}",
        f"https://github.com\\@evil.com/{owner}/{repo}",
        f"https://githubXcom/{owner}/{repo}",
        f"https://notgithub.com/{owner}/{repo}",
        f"https://github.com.cn/{owner}/{repo}",
        f"https://bitbucket.org.attacker.io/{owner}/{repo}",
        f"file:///github.com/{owner}/{repo}",
        f"/srv/github.com/{owner}/{repo}.git",
        f"../github.com/{owner}/{repo}",
        f"github.com/{owner}/{repo}",
        f"http://github.com/{owner}/{repo}",
    ]

    assert [url for url in lookalikes if shipped_allows(url)] == []
