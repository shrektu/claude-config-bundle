import importlib.machinery
import importlib.util
import fcntl
import json
import os
import subprocess
import sys
import urllib.error
from datetime import date
from pathlib import Path
from types import ModuleType

import pytest


MODULE_NAME = "bb_sweep"
SCRIPT_PATH = str(Path(__file__).resolve().with_name("bb-sweep"))
WORKSPACE = "acme"
REPO = "cert-manager"
PR_ID = 1
MY_UUID = "{my-uuid}"
ENCODED_MY_UUID = "%7Bmy-uuid%7D"
AUTHOR_UUID = "{author-uuid}"
OTHER_UUID = "{other-uuid}"
MY_NAME = "Me"
AUTHOR_NAME = "Author"
OTHER_NAME = "Other"
BOT_NICKNAME = "coderabbit"
CHANGES_REQUESTED = "changes_requested"
OPEN = "OPEN"
BASE_HASH = "1234567890abcdef"
HEAD_HASH = "abcdef1234567890"
MY_LAST_COMMENT = "2026-09-24T10:20:00+00:00"
OLDER_PARTICIPATION = "2026-09-23T10:02:00+00:00"
NEWER_PARTICIPATION = "2026-09-24T10:30:00+00:00"
OLDER_AUTHOR_COMMENT = "2026-09-24T10:00:00+00:00"
OLDER_UPDATE_TIME = "2026-09-24T09:00:00+00:00"
BETWEEN_AUTHOR_COMMENT = "2026-09-24T10:10:00+00:00"
NEW_AUTHOR_COMMENT = "2026-09-24T11:44:00+00:00"
PUSH_TIME = "2026-09-24T11:39:00+00:00"
DESCRIPTION_EDIT_TIME = "2026-09-24T11:00:00+00:00"
NEWEST_TIME = "2026-09-24T12:00:00+00:00"
NEXT_ACTIVITY_URL = "next-activity-page"
ROOT_COMMENT_ID = 100
OUTSIDE_THREAD_ID = 200
THIRD_PARTY_THREAD_ID = 300
OLDER_AUTHOR_THREAD_ID = 400
BOT_THREAD_ID = 500
URL = "https://bitbucket.example/cert-manager/1"
TITLE = "Test pull request"
BRANCH = "feature/test"
COMMENT_TEXT = "comment"
AUTHOR_NEW_THREAD_TEXT = "new author thread"
CONTENT_KEY = "content"
RAW_KEY = "raw"
VALUES_KEY = "values"
RESOLUTION_KEY = "resolution"
EMPTY_VALUES = {VALUES_KEY: []}
RESOLVED_VALUE = "resolved"
DEGRADED_PR = f"{REPO}#{PR_ID}"
OUTSIDE_RENDER_TAG = "[poza moimi wątkami]"
PUSH_RENDER_TEXT = "nowy push po moim ostatnim wpisie"
DESTINATION_FULL_NAME = f"{WORKSPACE}/{REPO}"
CACHE_DIR_ENV = "BB_SWEEP_CACHE_DIR"


@pytest.fixture(autouse=True)
def isolated_cache_dir(monkeypatch: pytest.MonkeyPatch, tmp_path: Path):
    monkeypatch.setenv(CACHE_DIR_ENV, str(tmp_path / "cache"))


def load_module():
    loader = importlib.machinery.SourceFileLoader(MODULE_NAME, SCRIPT_PATH)
    spec = importlib.util.spec_from_loader(MODULE_NAME, loader)
    module = importlib.util.module_from_spec(spec)
    sys.modules[MODULE_NAME] = module
    loader.exec_module(module)
    return module


@pytest.fixture
def bb_sweep(monkeypatch, tmp_path):
    module = load_module()
    requested = []
    responses = {}
    failures = set()

    def fake_get(url):
        requested.append(url)
        if url in failures:
            raise urllib.error.HTTPError(url, 500, "failure", None, None)
        return responses.get(url, {})

    monkeypatch.setattr(module, "get", fake_get)
    monkeypatch.setattr(module, "throttle", lambda: None)
    monkeypatch.setattr(module, "CACHE_DIR", str(tmp_path))
    monkeypatch.setattr(module, "REPO_CACHE", str(tmp_path / "repos.json"))
    monkeypatch.setattr(module, "REVIEWER_CACHE", str(tmp_path / "reviewer-repos.json"))
    monkeypatch.setattr(module, "RESOLVED_CACHE", str(tmp_path / "resolved.json"))
    module.RESOLVED_IDS.clear()
    return module, responses, failures, requested


def participant(uuid, state=None, participated_on=None):
    data = {"user": {"uuid": uuid}}
    if state is not None:
        data["state"] = state
    if participated_on is not None:
        data["participated_on"] = participated_on
    return data


def comment(
    comment_id,
    user_uuid,
    display_name,
    created_on,
    raw,
    parent=None,
    nickname=None,
):
    user = {"uuid": user_uuid, "display_name": display_name}
    if nickname is not None:
        user["nickname"] = nickname
    data = {
        "id": comment_id,
        "user": user,
        "created_on": created_on,
        CONTENT_KEY: {RAW_KEY: raw},
    }
    if parent is not None:
        data["parent"] = {"id": parent}
    return data


def pull_request(head_hash=HEAD_HASH):
    return {
        "id": PR_ID,
        "title": TITLE,
        "draft": False,
        "updated_on": PUSH_TIME,
        "comment_count": 1,
        "author": {"uuid": AUTHOR_UUID, "display_name": AUTHOR_NAME},
        "source": {"branch": {"name": BRANCH}, "commit": {"hash": head_hash}},
        "participants": [
            participant(MY_UUID, CHANGES_REQUESTED, OLDER_PARTICIPATION)
        ],
        "reviewers": [],
        "links": {"html": {"href": URL}},
    }


def configure_collect_responses(
    module, responses, comments, activity, head_hash=HEAD_HASH
):
    my_prs_url = (
        f"workspaces/{WORKSPACE}/pullrequests/{ENCODED_MY_UUID}"
        f"?state={OPEN}&pagelen=50&fields={module.MY_PR_FIELDS}"
    )
    open_prs_url = (
        f"repositories/{WORKSPACE}/{REPO}/pullrequests?q=state%3D%22OPEN%22"
        f"&pagelen=50&fields={module.PR_FIELDS}"
    )
    comments_url = (
        f"repositories/{WORKSPACE}/{REPO}/pullrequests/{PR_ID}/comments?pagelen=100"
    )
    activity_url = (
        f"repositories/{WORKSPACE}/{REPO}/pullrequests/{PR_ID}/activity"
        f"?pagelen={module.ACTIVITY_PAGELEN}"
    )
    responses[my_prs_url] = EMPTY_VALUES
    responses[open_prs_url] = {VALUES_KEY: [pull_request(head_hash)]}
    responses[comments_url] = {VALUES_KEY: comments}
    responses[activity_url] = {VALUES_KEY: activity}
    for item in comments:
        responses[
            f"repositories/{WORKSPACE}/{REPO}/pullrequests/{PR_ID}/comments/{item['id']}"
        ] = {}


def activity_update(date, commit_hash):
    return {"update": {"date": date, "source": {"commit": {"hash": commit_hash}}}}


def test_voted_pr_with_author_root_thread_after_my_last_entry_is_listed_in_replies(
    bb_sweep,
):
    module, responses, _, _ = bb_sweep
    items = [
        comment(ROOT_COMMENT_ID, MY_UUID, MY_NAME, MY_LAST_COMMENT, COMMENT_TEXT),
        comment(
            OUTSIDE_THREAD_ID,
            AUTHOR_UUID,
            AUTHOR_NAME,
            NEW_AUTHOR_COMMENT,
            AUTHOR_NEW_THREAD_TEXT,
        ),
    ]
    configure_collect_responses(
        module,
        responses,
        items,
        [activity_update(MY_LAST_COMMENT, BASE_HASH)],
        BASE_HASH,
    )

    result = module.collect([REPO], MY_UUID)

    assert result["replies"]
    assert any(
        thread["thread"] == OUTSIDE_THREAD_ID and thread["outside"]
        for thread in result["replies"][0]["threads"]
    )


def test_voted_pr_with_push_after_my_last_entry_is_listed_with_new_head(bb_sweep):
    module, responses, _, _ = bb_sweep
    items = [comment(ROOT_COMMENT_ID, MY_UUID, MY_NAME, MY_LAST_COMMENT, COMMENT_TEXT)]
    configure_collect_responses(
        module,
        responses,
        items,
        [
            activity_update(PUSH_TIME, HEAD_HASH),
            activity_update(MY_LAST_COMMENT, BASE_HASH),
        ],
    )

    result = module.collect([REPO], MY_UUID)

    assert result["replies"]
    assert result["replies"][0]["pushed_after_me"]["head"] == HEAD_HASH[:9]


def test_voted_pr_without_author_activity_after_my_last_entry_is_not_listed(bb_sweep):
    module, responses, _, _ = bb_sweep
    items = [
        comment(ROOT_COMMENT_ID, MY_UUID, MY_NAME, MY_LAST_COMMENT, COMMENT_TEXT),
        comment(
            OUTSIDE_THREAD_ID,
            AUTHOR_UUID,
            AUTHOR_NAME,
            OLDER_AUTHOR_COMMENT,
            COMMENT_TEXT,
        ),
    ]
    configure_collect_responses(
        module,
        responses,
        items,
        [
            activity_update(DESCRIPTION_EDIT_TIME, BASE_HASH),
            activity_update(MY_LAST_COMMENT, BASE_HASH),
        ],
        BASE_HASH,
    )

    result = module.collect([REPO], MY_UUID)

    assert result["replies"] == []


def test_my_last_entry_uses_the_latest_comment_or_participation(bb_sweep):
    module, _, _, _ = bb_sweep
    items = [
        comment(
            ROOT_COMMENT_ID,
            MY_UUID,
            MY_NAME,
            MY_LAST_COMMENT,
            COMMENT_TEXT,
        )
    ]

    last_entry = module.my_last_entry(items, MY_UUID, OLDER_PARTICIPATION)

    assert last_entry == module.parse_ts(MY_LAST_COMMENT)
    assert (
        module.my_last_entry(items, MY_UUID, NEWER_PARTICIPATION)
        == module.parse_ts(NEWER_PARTICIPATION)
    )
    assert module.my_last_entry([], MY_UUID, None) is None


def test_my_last_entry_prefers_newer_comment_over_older_participated_on(bb_sweep):
    module, _, _, _ = bb_sweep
    items = [
        comment(ROOT_COMMENT_ID, MY_UUID, MY_NAME, MY_LAST_COMMENT, COMMENT_TEXT)
    ]

    result = module.my_last_entry(items, MY_UUID, OLDER_PARTICIPATION)

    assert result == module.parse_ts(MY_LAST_COMMENT)


def test_my_last_entry_prefers_newer_comment_over_older_participated_on_in_collect(
    bb_sweep,
):
    module, responses, _, _ = bb_sweep
    items = [
        comment(ROOT_COMMENT_ID, MY_UUID, MY_NAME, MY_LAST_COMMENT, COMMENT_TEXT),
        comment(
            OUTSIDE_THREAD_ID,
            AUTHOR_UUID,
            AUTHOR_NAME,
            BETWEEN_AUTHOR_COMMENT,
            COMMENT_TEXT,
        ),
    ]
    configure_collect_responses(
        module,
        responses,
        items,
        [activity_update(MY_LAST_COMMENT, BASE_HASH)],
        BASE_HASH,
    )

    result = module.collect([REPO], MY_UUID)

    assert result["replies"] == []


def test_author_threads_after_excludes_nonqualifying_threads(bb_sweep):
    module, _, _, _ = bb_sweep
    items = [
        comment(ROOT_COMMENT_ID, MY_UUID, MY_NAME, MY_LAST_COMMENT, COMMENT_TEXT),
        comment(
            OUTSIDE_THREAD_ID,
            AUTHOR_UUID,
            AUTHOR_NAME,
            NEW_AUTHOR_COMMENT,
            AUTHOR_NEW_THREAD_TEXT,
        ),
        comment(
            THIRD_PARTY_THREAD_ID,
            OTHER_UUID,
            OTHER_NAME,
            NEW_AUTHOR_COMMENT,
            COMMENT_TEXT,
        ),
        comment(
            OLDER_AUTHOR_THREAD_ID,
            AUTHOR_UUID,
            AUTHOR_NAME,
            OLDER_AUTHOR_COMMENT,
            COMMENT_TEXT,
        ),
        comment(
            BOT_THREAD_ID,
            AUTHOR_UUID,
            AUTHOR_NAME,
            NEW_AUTHOR_COMMENT,
            COMMENT_TEXT,
            nickname=BOT_NICKNAME,
        ),
    ]

    rows = module.author_threads_after(
        items, AUTHOR_UUID, MY_UUID, module.parse_ts(MY_LAST_COMMENT)
    )

    assert [row["thread"] for row in rows] == [OUTSIDE_THREAD_ID]
    assert rows[0]["outside"] is True


def test_author_threads_after_skips_threads_where_user_spoke(bb_sweep):
    module, _, _, _ = bb_sweep
    items = [
        comment(ROOT_COMMENT_ID, MY_UUID, MY_NAME, MY_LAST_COMMENT, COMMENT_TEXT),
        comment(
            OUTSIDE_THREAD_ID,
            AUTHOR_UUID,
            AUTHOR_NAME,
            NEW_AUTHOR_COMMENT,
            COMMENT_TEXT,
            ROOT_COMMENT_ID,
        ),
    ]

    result = module.author_threads_after(
        items, AUTHOR_UUID, MY_UUID, module.parse_ts(MY_LAST_COMMENT)
    )

    assert result == []


def test_author_threads_after_skips_threads_where_user_spoke_in_collect(bb_sweep):
    module, responses, _, _ = bb_sweep
    items = [
        comment(ROOT_COMMENT_ID, MY_UUID, MY_NAME, MY_LAST_COMMENT, COMMENT_TEXT),
        comment(
            OUTSIDE_THREAD_ID,
            AUTHOR_UUID,
            AUTHOR_NAME,
            NEW_AUTHOR_COMMENT,
            COMMENT_TEXT,
            ROOT_COMMENT_ID,
        ),
    ]
    configure_collect_responses(
        module,
        responses,
        items,
        [activity_update(MY_LAST_COMMENT, BASE_HASH)],
        BASE_HASH,
    )

    result = module.collect([REPO], MY_UUID)

    assert len(result["replies"][0]["threads"]) == 1
    assert result["replies"][0]["threads"][0].get("outside") is None


def test_push_after_finds_baseline_ignores_same_hash_and_stops_paginating(bb_sweep):
    module, responses, _, requested = bb_sweep
    activity_url = (
        f"repositories/{WORKSPACE}/{REPO}/pullrequests/{PR_ID}/activity"
        f"?pagelen={module.ACTIVITY_PAGELEN}"
    )
    responses[activity_url] = {
        VALUES_KEY: [
            activity_update(PUSH_TIME, HEAD_HASH),
            activity_update(MY_LAST_COMMENT, BASE_HASH),
        ],
        "next": NEXT_ACTIVITY_URL,
    }
    since = module.parse_ts(MY_LAST_COMMENT)

    push = module.push_after(REPO, PR_ID, HEAD_HASH, since)

    assert push == module.PushAfterMe(HEAD_HASH[: module.SHORT_HASH_LEN], PUSH_TIME)
    assert NEXT_ACTIVITY_URL not in requested
    responses[activity_url] = {VALUES_KEY: [activity_update(MY_LAST_COMMENT, BASE_HASH)]}
    assert module.push_after(REPO, PR_ID, BASE_HASH, since) is None
    responses[activity_url] = {VALUES_KEY: [activity_update(NEWEST_TIME, HEAD_HASH)]}
    with pytest.raises(module.ActivityIncomplete):
        module.push_after(REPO, PR_ID, HEAD_HASH, since)


def test_push_after_raises_activity_incomplete_when_no_baseline_found(bb_sweep):
    module, responses, _, _ = bb_sweep
    activity_url = (
        f"repositories/{WORKSPACE}/{REPO}/pullrequests/{PR_ID}/activity"
        f"?pagelen={module.ACTIVITY_PAGELEN}"
    )
    responses[activity_url] = {VALUES_KEY: [activity_update(NEWEST_TIME, HEAD_HASH)]}

    with pytest.raises(module.ActivityIncomplete):
        module.push_after(
            REPO,
            PR_ID,
            HEAD_HASH,
            module.parse_ts(MY_LAST_COMMENT),
        )


def test_push_after_raises_activity_incomplete_when_head_moved_without_update_after_since(
    bb_sweep,
):
    module, responses, _, _ = bb_sweep
    activity_url = (
        f"repositories/{WORKSPACE}/{REPO}/pullrequests/{PR_ID}/activity"
        f"?pagelen={module.ACTIVITY_PAGELEN}"
    )
    responses[activity_url] = {
        VALUES_KEY: [
            {"comment": {}},
            activity_update(OLDER_UPDATE_TIME, BASE_HASH),
        ]
    }

    with pytest.raises(module.ActivityIncomplete):
        module.push_after(
            REPO,
            PR_ID,
            HEAD_HASH,
            module.parse_ts(MY_LAST_COMMENT),
        )


def test_collect_marks_pr_degraded_when_head_moved_without_update_after_since(
    bb_sweep,
):
    module, responses, _, _ = bb_sweep
    items = [comment(ROOT_COMMENT_ID, MY_UUID, MY_NAME, MY_LAST_COMMENT, COMMENT_TEXT)]
    configure_collect_responses(
        module,
        responses,
        items,
        [
            {"comment": {}},
            activity_update(OLDER_UPDATE_TIME, BASE_HASH),
        ],
        HEAD_HASH,
    )
    resolution_url = (
        f"repositories/{WORKSPACE}/{REPO}/pullrequests/{PR_ID}/comments/{ROOT_COMMENT_ID}"
    )
    responses[resolution_url] = {RESOLUTION_KEY: RESOLVED_VALUE}

    result = module.collect([REPO], MY_UUID)

    assert DEGRADED_PR in result["degraded"]
    assert result["approve"] == []


def test_push_after_raises_activity_incomplete_when_no_baseline_found_in_collect(
    bb_sweep,
):
    module, responses, _, _ = bb_sweep
    items = [comment(ROOT_COMMENT_ID, MY_UUID, MY_NAME, MY_LAST_COMMENT, COMMENT_TEXT)]
    configure_collect_responses(
        module,
        responses,
        items,
        [activity_update(NEWEST_TIME, HEAD_HASH)],
        HEAD_HASH,
    )
    resolution_url = (
        f"repositories/{WORKSPACE}/{REPO}/pullrequests/{PR_ID}/comments/{ROOT_COMMENT_ID}"
    )
    responses[resolution_url] = {RESOLUTION_KEY: RESOLVED_VALUE}

    result = module.collect([REPO], MY_UUID)

    assert DEGRADED_PR in result["degraded"]
    assert result["approve"] == []


def test_author_reply_in_my_thread_appears_once_in_replies(bb_sweep):
    module, responses, _, _ = bb_sweep
    items = [
        comment(ROOT_COMMENT_ID, MY_UUID, MY_NAME, MY_LAST_COMMENT, COMMENT_TEXT),
        comment(
            OUTSIDE_THREAD_ID,
            AUTHOR_UUID,
            AUTHOR_NAME,
            NEW_AUTHOR_COMMENT,
            COMMENT_TEXT,
            ROOT_COMMENT_ID,
        ),
    ]
    configure_collect_responses(
        module,
        responses,
        items,
        [activity_update(MY_LAST_COMMENT, BASE_HASH)],
        BASE_HASH,
    )

    result = module.collect([REPO], MY_UUID)

    assert [thread["thread"] for thread in result["replies"][0]["threads"]] == [
        ROOT_COMMENT_ID
    ]


def test_activity_error_degrades_pr_and_excludes_it_from_approve(bb_sweep):
    module, responses, failures, _ = bb_sweep
    items = [comment(ROOT_COMMENT_ID, MY_UUID, MY_NAME, MY_LAST_COMMENT, COMMENT_TEXT)]
    configure_collect_responses(
        module,
        responses,
        items,
        [activity_update(MY_LAST_COMMENT, BASE_HASH)],
        BASE_HASH,
    )
    resolution_url = (
        f"repositories/{WORKSPACE}/{REPO}/pullrequests/{PR_ID}/comments/{ROOT_COMMENT_ID}"
    )
    activity_url = (
        f"repositories/{WORKSPACE}/{REPO}/pullrequests/{PR_ID}/activity"
        f"?pagelen={module.ACTIVITY_PAGELEN}"
    )
    responses[resolution_url] = {RESOLUTION_KEY: RESOLVED_VALUE}
    failures.add(activity_url)

    result = module.collect([REPO], MY_UUID)

    assert DEGRADED_PR in result["degraded"]
    assert result["approve"] == []


def test_pr_without_my_vote_is_reviewed_without_an_activity_request(bb_sweep):
    module, responses, _, requested = bb_sweep
    configure_collect_responses(
        module,
        responses,
        [],
        [activity_update(MY_LAST_COMMENT, BASE_HASH)],
        BASE_HASH,
    )
    open_prs_url = (
        f"repositories/{WORKSPACE}/{REPO}/pullrequests?q=state%3D%22OPEN%22"
        f"&pagelen=50&fields={module.PR_FIELDS}"
    )
    no_vote_pr = pull_request(BASE_HASH)
    no_vote_pr["participants"] = []
    no_vote_pr["comment_count"] = 0
    responses[open_prs_url] = {VALUES_KEY: [no_vote_pr]}
    activity_url = (
        f"repositories/{WORKSPACE}/{REPO}/pullrequests/{PR_ID}/activity"
        f"?pagelen={module.ACTIVITY_PAGELEN}"
    )

    result = module.collect([REPO], MY_UUID)

    assert [row["id"] for row in result["review"]] == [PR_ID]
    assert activity_url not in requested


def test_existing_mine_and_approve_results_are_unchanged_without_new_activity(
    bb_sweep,
):
    module, responses, _, requested = bb_sweep
    mine_comment = comment(
        ROOT_COMMENT_ID,
        AUTHOR_UUID,
        AUTHOR_NAME,
        NEW_AUTHOR_COMMENT,
        COMMENT_TEXT,
    )
    configure_collect_responses(
        module,
        responses,
        [mine_comment],
        [activity_update(MY_LAST_COMMENT, BASE_HASH)],
        BASE_HASH,
    )
    mine_pr = pull_request(BASE_HASH)
    mine_pr["author"] = {"uuid": MY_UUID, "display_name": MY_NAME}
    mine_pr["destination"] = {"repository": {"full_name": DESTINATION_FULL_NAME}}
    my_prs_url = (
        f"workspaces/{WORKSPACE}/pullrequests/{ENCODED_MY_UUID}"
        f"?state={OPEN}&pagelen=50&fields={module.MY_PR_FIELDS}"
    )
    activity_url = (
        f"repositories/{WORKSPACE}/{REPO}/pullrequests/{PR_ID}/activity"
        f"?pagelen={module.ACTIVITY_PAGELEN}"
    )
    responses[my_prs_url] = {VALUES_KEY: [mine_pr]}

    mine_result = module.collect([], MY_UUID, need_review=False)

    assert [row["id"] for row in mine_result["mine"]] == [PR_ID]
    assert mine_result["replies"] == []
    assert activity_url not in requested

    module.RESOLVED_IDS.clear()
    approve_comment = comment(
        ROOT_COMMENT_ID,
        MY_UUID,
        MY_NAME,
        MY_LAST_COMMENT,
        COMMENT_TEXT,
    )
    configure_collect_responses(
        module,
        responses,
        [approve_comment],
        [activity_update(MY_LAST_COMMENT, BASE_HASH)],
        BASE_HASH,
    )
    resolution_url = (
        f"repositories/{WORKSPACE}/{REPO}/pullrequests/{PR_ID}/comments/{ROOT_COMMENT_ID}"
    )
    responses[resolution_url] = {RESOLUTION_KEY: RESOLVED_VALUE}

    approve_result = module.collect([REPO], MY_UUID)

    assert [row["id"] for row in approve_result["approve"]] == [PR_ID]
    assert approve_result["replies"] == []


def test_render_marks_outside_threads_and_pushes(bb_sweep, capsys):
    module, _, _, _ = bb_sweep
    result = {
        "mine": [],
        "review": [],
        "replies": [
            {
                "repo": REPO,
                "id": PR_ID,
                "title": TITLE,
                "my_state": CHANGES_REQUESTED,
                "my_open": 0,
                "url": URL,
                "pushed_after_me": {"head": HEAD_HASH[:9], "pushed_on": PUSH_TIME},
                "threads": [
                    {
                        "thread": OUTSIDE_THREAD_ID,
                        "bot": False,
                        "outside": True,
                        "where": COMMENT_TEXT,
                        "last_by": AUTHOR_NAME,
                        "last_on": NEW_AUTHOR_COMMENT[:16],
                        "excerpt": AUTHOR_NEW_THREAD_TEXT,
                    }
                ],
            }
        ],
        "approve": [],
        "degraded": [],
    }

    module.render(result, {"replies"})

    output = capsys.readouterr().out
    assert OUTSIDE_RENDER_TAG in output
    assert PUSH_RENDER_TEXT in output


HARVEST_TODAY = date(2026, 9, 29)
HARVEST_SINCE = "2026-09-01"
HARVEST_PR_ID = 7
OLD_PR_ID = 3
OTHER_REPO = "device-service"
NEXT_MY_PRS_URL = "next-my-prs-page"
RECENT_UPDATE = "2026-09-20T08:00:00+00:00"
OLD_UPDATE = "2026-08-01T08:00:00+00:00"
REVIEW_THREAD_ID = 100
MY_REPLY_ID = 101
MY_THREAD_ID = 200
HARVEST_BOT_THREAD_ID = 300
REVIEW_TEXT = "please   use pathlib\nhere"
MY_REPLY_TEXT = "done"
INLINE_PATH = "src/app.py"
INLINE_LINE = 10
HARVEST_STATE_NAME = "harvested.json"
REVIEW_REF = f"{REPO}#{HARVEST_PR_ID}/{REVIEW_THREAD_ID}"
BOT_REF = f"{REPO}#{HARVEST_PR_ID}/{HARVEST_BOT_THREAD_ID}"
CORRUPT_STATE = b"{not json"
PREVIOUS_CUTOFF = "2026-09-10"
LOCK_SUFFIX = ".lock"
CONCURRENT_MARKS = 8
FIRST_CONCURRENT_THREAD = 1000
LOCK_WAIT_S = 2
PROCESS_TIMEOUT_S = 30
HARVEST_FIELD_NAMES = (
    "values.id",
    "values.title",
    "values.updated_on",
    "values.destination.repository.full_name",
    "values.links.html.href",
    "next",
)
HARVEST_FIELDS = ",".join(HARVEST_FIELD_NAMES)
Harness = tuple[ModuleType, dict[str, object], set[str], list[str]]


def my_pr(pr_id: int, updated_on: str, repo: str = REPO) -> dict:
    return {
        "id": pr_id,
        "title": f"{TITLE} {pr_id}",
        "updated_on": updated_on,
        "destination": {"repository": {"full_name": f"{WORKSPACE}/{repo}"}},
        "links": {"html": {"href": f"{URL}/{pr_id}"}},
    }


def harvest_prs_url() -> str:
    return (
        f"workspaces/{WORKSPACE}/pullrequests/{ENCODED_MY_UUID}"
        "?state=OPEN&state=MERGED&sort=-updated_on&pagelen=50"
        f"&fields={HARVEST_FIELDS}"
    )


def pr_comments_url(repo: str, pr_id: int) -> str:
    return (
        f"repositories/{WORKSPACE}/{repo}/pullrequests/{pr_id}"
        "/comments?pagelen=100"
    )


def comment_url(repo: str, pr_id: int, comment_id: int) -> str:
    return (
        f"repositories/{WORKSPACE}/{repo}/pullrequests/{pr_id}"
        f"/comments/{comment_id}"
    )


def harvest_comments() -> list[dict]:
    review = comment(
        REVIEW_THREAD_ID,
        OTHER_UUID,
        OTHER_NAME,
        OLDER_AUTHOR_COMMENT,
        REVIEW_TEXT,
    )
    review["inline"] = {"path": INLINE_PATH, "to": INLINE_LINE}
    return [
        review,
        comment(
            MY_REPLY_ID,
            MY_UUID,
            MY_NAME,
            BETWEEN_AUTHOR_COMMENT,
            MY_REPLY_TEXT,
            parent=REVIEW_THREAD_ID,
        ),
        comment(
            MY_THREAD_ID,
            MY_UUID,
            MY_NAME,
            OLDER_AUTHOR_COMMENT,
            COMMENT_TEXT,
        ),
        comment(
            MY_THREAD_ID + 1,
            OTHER_UUID,
            OTHER_NAME,
            NEWEST_TIME,
            COMMENT_TEXT,
            parent=MY_THREAD_ID,
        ),
        comment(
            HARVEST_BOT_THREAD_ID,
            AUTHOR_UUID,
            "Jenkins",
            NEW_AUTHOR_COMMENT,
            COMMENT_TEXT,
            nickname=BOT_NICKNAME,
        ),
    ]


@pytest.fixture
def harvest(bb_sweep: Harness, monkeypatch: pytest.MonkeyPatch) -> Harness:
    module, responses, failures, requested = bb_sweep
    monkeypatch.setattr(
        module, "harvest_today", lambda: HARVEST_TODAY, raising=False
    )
    responses["user"] = {"uuid": MY_UUID, "display_name": MY_NAME}
    responses[harvest_prs_url()] = {
        VALUES_KEY: [
            my_pr(HARVEST_PR_ID, RECENT_UPDATE),
            my_pr(OLD_PR_ID, OLD_UPDATE),
        ],
        "next": NEXT_MY_PRS_URL,
    }
    responses[NEXT_MY_PRS_URL] = {
        VALUES_KEY: [my_pr(OLD_PR_ID + 1, OLD_UPDATE)]
    }
    responses[pr_comments_url(REPO, HARVEST_PR_ID)] = {
        VALUES_KEY: harvest_comments()
    }
    responses[comment_url(REPO, HARVEST_PR_ID, REVIEW_THREAD_ID)] = {
        RESOLUTION_KEY: {"type": RESOLVED_VALUE}
    }
    return module, responses, failures, requested


def harvest_json(
    module: ModuleType, capsys: pytest.CaptureFixture[str], *args: str
) -> list:
    assert module.cmd_harvest(["--json", *args]) == 0
    return json.loads(capsys.readouterr().out)


def test_harvest_lists_threads_of_others_on_my_recent_prs(
    harvest: Harness,
    capsys: pytest.CaptureFixture[str],
):
    module, _, _, _ = harvest

    records = harvest_json(module, capsys, "--since", HARVEST_SINCE)

    assert [r["thread"] for r in records] == [
        REVIEW_THREAD_ID,
        HARVEST_BOT_THREAD_ID,
    ]
    review, bot = records
    assert review["repo"] == REPO
    assert review["pr"] == HARVEST_PR_ID
    assert review["pr_title"] == f"{TITLE} {HARVEST_PR_ID}"
    assert review["ref"] == REVIEW_REF
    assert review["author"] == OTHER_NAME
    assert review["bot"] is False
    assert review["created_on"] == OLDER_AUTHOR_COMMENT
    assert review["where"] == f"{INLINE_PATH}:{INLINE_LINE}"
    assert review["text"] == "please use pathlib here"
    assert review["my_replies"] == [MY_REPLY_TEXT]
    assert review["resolved"] is True
    assert bot["bot"] is True
    assert bot["resolved"] is False
    assert bot["ref"] == BOT_REF


def test_harvest_stops_paging_at_first_pr_older_than_since(
    harvest: Harness,
    capsys: pytest.CaptureFixture[str],
):
    module, _, _, requested = harvest

    harvest_json(module, capsys, "--since", HARVEST_SINCE)

    assert NEXT_MY_PRS_URL not in requested
    assert pr_comments_url(REPO, OLD_PR_ID) not in requested


def test_harvest_skips_marked_refs_unless_all(
    harvest: Harness,
    capsys: pytest.CaptureFixture[str],
):
    module, _, _, _ = harvest
    assert (
        module.cmd_harvest_mark(
            [REPO, str(HARVEST_PR_ID), str(REVIEW_THREAD_ID)]
        )
        == 0
    )
    capsys.readouterr()

    fresh = harvest_json(module, capsys, "--since", HARVEST_SINCE)
    everything = harvest_json(
        module, capsys, "--since", HARVEST_SINCE, "--all"
    )

    assert [r["ref"] for r in fresh] == [BOT_REF]
    assert [r["ref"] for r in everything] == [REVIEW_REF, BOT_REF]


def test_harvest_mark_records_refs_without_moving_last_harvest(
    harvest: Harness,
    tmp_path: Path,
    capsys: pytest.CaptureFixture[str],
):
    module, _, _, _ = harvest

    code = module.cmd_harvest_mark(
        [
            REPO,
            str(HARVEST_PR_ID),
            str(REVIEW_THREAD_ID),
            str(HARVEST_BOT_THREAD_ID),
        ]
    )
    again = module.cmd_harvest_mark(
        [REPO, str(HARVEST_PR_ID), str(REVIEW_THREAD_ID)]
    )

    assert code == 0
    assert again == 0
    output = capsys.readouterr().out.splitlines()
    assert "2" in output[0]
    assert "0" in output[1]
    state = json.loads((tmp_path / HARVEST_STATE_NAME).read_text())
    assert state["version"] == 1
    assert state["last_harvest"] is None
    assert sorted(state["refs"]) == sorted([REVIEW_REF, BOT_REF])


def test_harvest_without_since_uses_last_harvest(
    harvest: Harness,
    capsys: pytest.CaptureFixture[str],
):
    module, _, _, requested = harvest
    assert harvest_json(module, capsys)
    assert module.cmd_harvest_done([]) == 0
    capsys.readouterr()
    requested.clear()

    records = harvest_json(module, capsys)

    assert records == []
    assert pr_comments_url(REPO, HARVEST_PR_ID) not in requested


def test_harvest_default_since_reaches_back_180_days(
    harvest: Harness,
    capsys: pytest.CaptureFixture[str],
):
    module, _, _, requested = harvest

    records = harvest_json(module, capsys)

    assert records
    assert pr_comments_url(REPO, OLD_PR_ID) in requested
    assert NEXT_MY_PRS_URL in requested


def test_harvest_repos_option_filters_by_slug(
    harvest: Harness,
    capsys: pytest.CaptureFixture[str],
):
    module, _, _, requested = harvest

    records = harvest_json(
        module, capsys, "--since", HARVEST_SINCE, "--repos", OTHER_REPO
    )

    assert records == []
    assert pr_comments_url(REPO, HARVEST_PR_ID) not in requested


def test_harvest_text_output_groups_threads_per_pr(
    harvest: Harness,
    capsys: pytest.CaptureFixture[str],
):
    module, _, _, _ = harvest

    assert module.cmd_harvest(["--since", HARVEST_SINCE]) == 0

    out = capsys.readouterr().out
    assert out.count(f"{REPO}#{HARVEST_PR_ID}") == 1
    assert f"[{REVIEW_THREAD_ID}]" in out
    assert f"[{HARVEST_BOT_THREAD_ID}] [bot]" in out
    assert "please use pathlib here" in out
    assert MY_REPLY_TEXT in out


def test_main_dispatches_harvest_mark(
    harvest: Harness,
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
):
    module, _, _, _ = harvest
    credentials = tmp_path / "credentials"
    credentials.write_text("user:token")
    monkeypatch.setattr(module, "CRED_PATH", str(credentials))

    code = module.main(
        ["harvest-mark", REPO, str(HARVEST_PR_ID), str(REVIEW_THREAD_ID)]
    )

    assert code == 0
    assert (tmp_path / HARVEST_STATE_NAME).exists()


def test_harvest_since_prefers_option_then_state_then_default(
    bb_sweep: Harness,
):
    module, _, _, _ = bb_sweep
    given = date(2026, 9, 1)
    state = module.HarvestState(last_harvest="2026-09-10")
    empty = module.HarvestState()
    broken = module.HarvestState(last_harvest="yesterday")
    default = date(2026, 4, 2)

    assert module.harvest_since(given, state, HARVEST_TODAY) == given
    assert module.harvest_since(None, state, HARVEST_TODAY) == date(
        2026, 9, 10
    )
    assert module.harvest_since(None, empty, HARVEST_TODAY) == default
    assert module.harvest_since(None, broken, HARVEST_TODAY) == default


def test_harvest_ref_format(bb_sweep: Harness):
    module, _, _, _ = bb_sweep

    assert module.harvest_ref(REPO, HARVEST_PR_ID, REVIEW_THREAD_ID) == (
        REVIEW_REF
    )


def test_harvest_skips_thread_whose_root_is_mine(harvest: Harness):
    module, _, _, _ = harvest
    pr = my_pr(HARVEST_PR_ID, RECENT_UPDATE)

    rows = module.harvest_pr(REPO, pr, MY_UUID, set())

    assert MY_THREAD_ID not in [row.thread for row in rows]


def test_harvest_pr_with_unfetchable_comments_prints_warning(
    harvest: Harness,
    capsys: pytest.CaptureFixture[str],
):
    module, _, failures, _ = harvest
    failures.add(pr_comments_url(REPO, HARVEST_PR_ID))

    assert module.cmd_harvest(["--since", HARVEST_SINCE]) == 0

    out = capsys.readouterr().out
    assert "UWAGA:" in out
    assert f"{REPO}#{HARVEST_PR_ID}" in out


def test_harvest_mark_refuses_corrupt_state(
    harvest: Harness,
    tmp_path: Path,
    capsys: pytest.CaptureFixture[str],
):
    module, _, _, _ = harvest
    state_file = tmp_path / HARVEST_STATE_NAME
    state_file.write_bytes(CORRUPT_STATE)

    code = module.cmd_harvest_mark(
        [REPO, str(HARVEST_PR_ID), str(REVIEW_THREAD_ID)]
    )

    assert code == 2
    assert state_file.read_bytes() == CORRUPT_STATE
    assert HARVEST_STATE_NAME in capsys.readouterr().err


def test_harvest_reads_corrupt_state_as_empty(
    harvest: Harness,
    tmp_path: Path,
    capsys: pytest.CaptureFixture[str],
):
    module, _, _, _ = harvest
    (tmp_path / HARVEST_STATE_NAME).write_bytes(CORRUPT_STATE)

    records = harvest_json(module, capsys, "--since", HARVEST_SINCE)

    assert [r["ref"] for r in records] == [REVIEW_REF, BOT_REF]


@pytest.mark.parametrize(
    "argv",
    [[], [REPO, "7"], [REPO, "x", "1"], [REPO, "7", "y"]],
)
def test_harvest_mark_rejects_bad_arguments(
    harvest: Harness,
    tmp_path: Path,
    argv: list[str],
):
    module, _, _, _ = harvest

    assert module.cmd_harvest_mark(argv) == 2
    assert not (tmp_path / HARVEST_STATE_NAME).exists()


def test_marking_one_thread_keeps_the_other_in_default_harvest(
    harvest: Harness, capsys: pytest.CaptureFixture[str]
):
    module, _, _, _ = harvest
    assert (
        module.cmd_harvest_mark(
            [REPO, str(HARVEST_PR_ID), str(REVIEW_THREAD_ID)]
        )
        == 0
    )
    capsys.readouterr()

    records = harvest_json(module, capsys)

    assert [r["ref"] for r in records] == [BOT_REF]


def test_harvest_done_moves_cutoff_to_today_and_prints_both(
    harvest: Harness, tmp_path: Path, capsys: pytest.CaptureFixture[str]
):
    module, _, _, _ = harvest
    state_file = tmp_path / HARVEST_STATE_NAME
    state_file.write_text(
        json.dumps(
            {
                "version": 1,
                "last_harvest": PREVIOUS_CUTOFF,
                "refs": [REVIEW_REF],
            }
        )
    )

    code = module.cmd_harvest_done([])

    assert code == 0
    output = capsys.readouterr().out
    assert PREVIOUS_CUTOFF in output
    assert HARVEST_TODAY.isoformat() in output
    state = json.loads(state_file.read_text())
    assert state["last_harvest"] == HARVEST_TODAY.isoformat()
    assert state["refs"] == [REVIEW_REF]
    assert harvest_json(module, capsys) == []


def test_harvest_done_refuses_corrupt_state(harvest: Harness, tmp_path: Path):
    module, _, _, _ = harvest
    state_file = tmp_path / HARVEST_STATE_NAME
    state_file.write_bytes(CORRUPT_STATE)

    assert module.cmd_harvest_done([]) == 2
    assert state_file.read_bytes() == CORRUPT_STATE


def test_harvest_done_rejects_arguments(harvest: Harness, tmp_path: Path):
    module, _, _, _ = harvest

    assert module.cmd_harvest_done([HARVEST_SINCE]) == 2
    assert not (tmp_path / HARVEST_STATE_NAME).exists()


def mark_process(cache_dir: Path, thread_id: int) -> subprocess.Popen:
    env = {**os.environ, CACHE_DIR_ENV: str(cache_dir)}
    return subprocess.Popen(
        [
            sys.executable,
            SCRIPT_PATH,
            "harvest-mark",
            REPO,
            str(HARVEST_PR_ID),
            str(thread_id),
        ],
        env=env,
        stdout=subprocess.DEVNULL,
        stderr=subprocess.PIPE,
    )


def test_concurrent_harvest_marks_all_persist(tmp_path: Path):
    thread_ids = range(
        FIRST_CONCURRENT_THREAD, FIRST_CONCURRENT_THREAD + CONCURRENT_MARKS
    )
    processes = [mark_process(tmp_path, tid) for tid in thread_ids]
    results = [p.communicate(timeout=PROCESS_TIMEOUT_S) for p in processes]

    assert [p.returncode for p in processes] == [0] * CONCURRENT_MARKS, results
    state = json.loads((tmp_path / HARVEST_STATE_NAME).read_text())
    assert sorted(state["refs"]) == sorted(
        f"{REPO}#{HARVEST_PR_ID}/{tid}" for tid in thread_ids
    )


def test_harvest_mark_waits_for_the_state_lock(tmp_path: Path):
    lock_path = tmp_path / (HARVEST_STATE_NAME + LOCK_SUFFIX)
    with lock_path.open("a") as lock:
        fcntl.flock(lock, fcntl.LOCK_EX)
        process = mark_process(tmp_path, FIRST_CONCURRENT_THREAD)
        with pytest.raises(subprocess.TimeoutExpired):
            process.wait(timeout=LOCK_WAIT_S)
        assert not (tmp_path / HARVEST_STATE_NAME).exists()
    process.communicate(timeout=PROCESS_TIMEOUT_S)

    assert process.returncode == 0
    state = json.loads((tmp_path / HARVEST_STATE_NAME).read_text())
    assert state["refs"] == [
        f"{REPO}#{HARVEST_PR_ID}/{FIRST_CONCURRENT_THREAD}"
    ]
