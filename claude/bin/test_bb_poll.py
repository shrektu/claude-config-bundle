import fcntl
import importlib.machinery
import importlib.util
import json
import socket
import subprocess
import sys
import threading
import urllib.error
from collections.abc import Callable
from datetime import UTC, datetime, timedelta
from email.message import EmailMessage
from pathlib import Path
from types import ModuleType
from typing import Any

import pytest

BIN_DIR = Path(__file__).resolve().parent
MODULE_NAME = "bb_poll"
SCRIPT_PATH = BIN_DIR / "bb-poll"
CACHE_DIR_ENV = "BB_SWEEP_CACHE_DIR"
REPO = "cert-manager"
PR_ID = 7
MY_UUID = "{my-uuid}"
AUTHOR_UUID = "{author-uuid}"
TITLE = "Test pull request"
URL = "https://bitbucket.example/cert-manager/7"
HEAD_ONE = "aaaaaaaaaaaaaaaa"
HEAD_TWO = "bbbbbbbbbbbbbbbb"
UPDATED_ON = "2026-10-22T09:00:00+00:00"
NOW = datetime(2026, 10, 22, 12, 0, tzinfo=UTC)
CLAUDE = "claude"
NOTIFY = "notify-send"
STATE_FILE = "poll-state.json"
LOCK_FILE = "poll.lock"
MAX_FAILURES = 3
BARRIER_TIMEOUT_S = 1.0


@pytest.fixture(autouse=True)
def isolated_cache_dir(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    monkeypatch.setenv(CACHE_DIR_ENV, str(tmp_path / "cache"))
    monkeypatch.delenv("CLAUDE_MODE", raising=False)


def load_module() -> ModuleType:
    assert SCRIPT_PATH.exists(), f"missing {SCRIPT_PATH}"
    sys.path.insert(0, str(BIN_DIR))
    loader = importlib.machinery.SourceFileLoader(
        MODULE_NAME, str(SCRIPT_PATH)
    )
    spec = importlib.util.spec_from_loader(MODULE_NAME, loader)
    assert spec is not None
    module = importlib.util.module_from_spec(spec)
    sys.modules[MODULE_NAME] = module
    loader.exec_module(module)
    return module


def make_pr(
    head: str = HEAD_ONE,
    *,
    pr_id: int = PR_ID,
    my_vote: str | None = None,
    updated_on: str = UPDATED_ON,
) -> dict[str, Any]:
    participants = []
    if my_vote is not None:
        participants.append({"user": {"uuid": MY_UUID}, "state": my_vote})
    return {
        "id": pr_id,
        "title": TITLE,
        "draft": False,
        "updated_on": updated_on,
        "author": {"uuid": AUTHOR_UUID},
        "source": {"commit": {"hash": head}},
        "participants": participants,
        "links": {"html": {"href": URL}},
    }


def make_draft(pr_id: int) -> dict[str, Any]:
    pr = make_pr(pr_id=pr_id)
    pr["draft"] = True
    return pr


def make_own(pr_id: int) -> dict[str, Any]:
    pr = make_pr(pr_id=pr_id)
    pr["author"] = {"uuid": MY_UUID}
    return pr


def http_error(code: int) -> urllib.error.HTTPError:
    return urllib.error.HTTPError(
        "https://api.example", code, "error", EmailMessage(), None
    )


class Clock:
    def __init__(self, step: timedelta = timedelta(0)) -> None:
        self.current = NOW
        self.step = step

    def __call__(self) -> datetime:
        value = self.current
        self.current += self.step
        return value


class FakeRunner:
    def __init__(self, claude_rc: int = 0) -> None:
        self.calls: list[list[str]] = []
        self.claude_rc = claude_rc
        self.claude_times_out = False
        self.notify_missing = False
        self.observe: Callable[[], object] | None = None
        self.observed: list[object] = []
        self.claude_hook: Callable[[list[str]], None] | None = None
        self.claude_kwargs: list[dict[str, object]] = []

    def __call__(
        self, argv: list[str], **kwargs: object
    ) -> subprocess.CompletedProcess[str]:
        self.calls.append(argv)
        if argv[0] == CLAUDE:
            self.claude_kwargs.append(kwargs)
        if argv[0] == NOTIFY and self.notify_missing:
            raise FileNotFoundError(NOTIFY)
        if argv[0] == CLAUDE:
            if self.claude_hook is not None:
                self.claude_hook(argv)
            if self.observe is not None:
                self.observed.append(self.observe())
            if self.claude_times_out:
                raise subprocess.TimeoutExpired(argv, 1)
            return subprocess.CompletedProcess(
                argv, self.claude_rc, "out", "err"
            )
        return subprocess.CompletedProcess(argv, 0, "", "")

    @property
    def claude_calls(self) -> list[list[str]]:
        return [c for c in self.calls if c[0] == CLAUDE]

    @property
    def notify_calls(self) -> list[list[str]]:
        return [c for c in self.calls if c[0] == NOTIFY]


class Env:
    def __init__(
        self, module: ModuleType, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        self.module = module
        self.monkeypatch = monkeypatch
        self.prs: list[dict[str, Any]] = []
        self.others: dict[str, list[dict[str, Any]]] = {}
        self.scan_error: Exception | None = None
        self.api_calls = 0
        self.real_scan_repo = module.scan_repo
        monkeypatch.setattr(module, "me", self.fake_me)
        monkeypatch.setattr(module, "repo_index", self.fake_repo_index)
        monkeypatch.setattr(module, "candidate_repos", self.fake_candidates)
        monkeypatch.setattr(module, "scan_repo", self.fake_scan_repo)

    def fake_me(self) -> dict[str, str]:
        self.api_calls += 1
        return {"uuid": MY_UUID}

    def fake_repo_index(self, *, refresh: bool) -> dict[str, str]:
        assert not refresh
        return {REPO: UPDATED_ON}

    def fake_candidates(
        self, _index: dict[str, str], *, deep: bool
    ) -> list[str]:
        assert not deep
        return [REPO, *self.others]

    def fake_scan_repo(self, repo: str) -> list[dict[str, Any]]:
        if self.scan_error is not None:
            raise self.scan_error
        return self.prs if repo == REPO else self.others[repo]

    def use_real_scan_repo(self, pages: Callable[[str], object]) -> None:
        self.monkeypatch.setattr(self.module, "scan_repo", self.real_scan_repo)
        self.monkeypatch.setattr(self.module, "pages", pages)

    def seed(self, entries: dict[str, Any], **fields: str | None) -> None:
        state = self.module.PollState(
            fields.get("last_full_scan"), fields.get("last_poll"), entries
        )
        self.module.write_state(state)

    def run(
        self,
        runner: FakeRunner,
        *args: str,
        full: bool = True,
        clock: Callable[[], datetime] | None = None,
    ) -> int:
        argv = [*(["--full"] if full else []), *args]
        code: int = self.module.main(argv, runner=runner, now=clock or Clock())
        return code

    def entry(self, key: str = f"{REPO}#{PR_ID}") -> dict[str, Any]:
        raw = (Path(self.module.CACHE_DIR) / STATE_FILE).read_text()
        entry: dict[str, Any] = json.loads(raw)["prs"][key]
        return entry


@pytest.fixture
def env(monkeypatch: pytest.MonkeyPatch) -> Env:
    return Env(load_module(), monkeypatch)


def test_new_pr_without_vote_reviewed_once(env: Env) -> None:
    env.prs = [make_pr()]
    runner = FakeRunner()

    assert env.run(runner) == 0

    assert len(runner.claude_calls) == 1
    prompt = runner.claude_calls[0][2]
    assert f"{REPO}#{PR_ID}" in prompt
    assert HEAD_ONE in prompt
    state = env.module.read_state()
    assert state.prs[f"{REPO}#{PR_ID}"].reviewed_head == HEAD_ONE


def test_new_head_after_review_rechecked(env: Env) -> None:
    env.prs = [make_pr(HEAD_ONE)]
    env.run(FakeRunner())
    env.prs = [make_pr(HEAD_TWO)]
    runner = FakeRunner()

    env.run(runner)

    assert len(runner.claude_calls) == 1
    assert "Nowy push po moim głosie" in runner.claude_calls[0][2]
    assert HEAD_TWO in runner.claude_calls[0][2]


def test_voted_pr_baselined_then_rechecked_on_push(env: Env) -> None:
    env.prs = [make_pr(HEAD_ONE, my_vote="approved")]
    first = FakeRunner()
    env.run(first)
    assert first.claude_calls == []
    entry = env.module.read_state().prs[f"{REPO}#{PR_ID}"]
    assert entry.reviewed_head == HEAD_ONE

    env.prs = [make_pr(HEAD_TWO, my_vote="approved")]
    second = FakeRunner()
    env.run(second)

    assert len(second.claude_calls) == 1
    assert "Nowy push po moim głosie" in second.claude_calls[0][2]


def test_drafts_and_own_prs_never_reviewed(env: Env) -> None:
    env.prs = [
        make_draft(1),
        make_own(2),
    ]
    runner = FakeRunner()

    assert env.run(runner) == 0

    assert runner.claude_calls == []


def test_lock_held_exits_without_api(env: Env) -> None:
    cache = Path(env.module.CACHE_DIR)
    cache.mkdir(parents=True, exist_ok=True)
    env.prs = [make_pr()]
    runner = FakeRunner()
    with (cache / LOCK_FILE).open("w") as holder:
        fcntl.flock(holder, fcntl.LOCK_EX | fcntl.LOCK_NB)

        assert env.run(runner) == 0

    assert env.api_calls == 0
    assert runner.calls == []


def test_dry_run_no_claude_no_state_write(env: Env) -> None:
    env.prs = [make_pr()]
    runner = FakeRunner()

    assert env.run(runner, "--dry-run") == 0

    assert runner.calls == []
    assert not (Path(env.module.CACHE_DIR) / STATE_FILE).exists()


def test_failed_review_retried_three_times_per_head(env: Env) -> None:
    env.prs = [make_pr(HEAD_ONE)]
    runner = FakeRunner(claude_rc=1)

    for _ in range(MAX_FAILURES + 2):
        env.run(runner)

    assert len(runner.claude_calls) == MAX_FAILURES

    env.prs = [make_pr(HEAD_TWO)]
    env.run(runner)

    assert len(runner.claude_calls) == MAX_FAILURES + 1


def test_full_scan_when_last_full_older_than_two_hours(env: Env) -> None:
    env.seed(
        {},
        last_full_scan="2026-10-22T08:30:00+00:00",
        last_poll="2026-10-22T11:50:00+00:00",
    )
    env.monkeypatch.setattr(env.module, "pages", fail_pages)
    env.prs = [make_pr()]
    runner = FakeRunner()

    assert env.run(runner, full=False) == 0

    assert len(runner.claude_calls) == 1
    state = json.loads((Path(env.module.CACHE_DIR) / STATE_FILE).read_text())
    assert state["last_full_scan"] == "2026-10-22T12:00:00+00:00"


def fail_pages(url: str) -> list[dict[str, Any]]:
    message = f"unexpected listing {url}"
    raise AssertionError(message)


def test_incremental_query_uses_utc_since_with_margin(env: Env) -> None:
    env.seed(
        {},
        last_full_scan="2026-10-22T11:30:00+00:00",
        last_poll="2026-10-22T13:40:00+02:00",
    )
    urls: list[str] = []

    def listing(url: str) -> list[dict[str, str]]:
        urls.append(url)
        return [{"slug": REPO}]

    env.monkeypatch.setattr(env.module, "pages", listing)
    env.prs = [make_pr()]
    runner = FakeRunner()

    assert env.run(runner, full=False) == 0

    expected_url = (
        "repositories/acme?q=updated_on%3E%222026-10-22T11%3A38%3A00"
        "%2B00%3A00%22&pagelen=100&fields=values.slug,next"
    )
    assert urls == [expected_url]
    assert len(runner.claude_calls) == 1
    state = json.loads((Path(env.module.CACHE_DIR) / STATE_FILE).read_text())
    assert state["last_full_scan"] == "2026-10-22T11:30:00+00:00"


def test_comment_only_update_no_review(env: Env) -> None:
    env.seed({f"{REPO}#{PR_ID}": env.module.PrEntry(HEAD_ONE, HEAD_ONE, 0)})
    env.prs = [
        make_pr(
            HEAD_ONE,
            my_vote="approved",
            updated_on="2026-10-22T11:59:00+00:00",
        )
    ]
    runner = FakeRunner()

    assert env.run(runner) == 0

    assert runner.claude_calls == []


def test_prune_only_scanned_repos(env: Env) -> None:
    env.seed(
        {
            f"{REPO}#{PR_ID}": env.module.PrEntry(HEAD_ONE, HEAD_ONE, 0),
            "other#9": env.module.PrEntry(HEAD_ONE, HEAD_ONE, 0),
        }
    )
    env.prs = [make_pr(pr_id=8, my_vote="approved")]

    assert env.run(FakeRunner()) == 0

    keys = set(env.module.read_state().prs)
    assert keys == {f"{REPO}#8", "other#9"}


def test_corrupt_state_exits_nonzero_without_overwrite(env: Env) -> None:
    path = Path(env.module.CACHE_DIR) / STATE_FILE
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text("{not json")
    env.prs = [make_pr()]
    runner = FakeRunner()

    assert env.run(runner) == 1

    assert path.read_text() == "{not json"
    assert env.api_calls == 0
    assert runner.calls == []


def test_unknown_state_version_exits_nonzero(env: Env) -> None:
    path = Path(env.module.CACHE_DIR) / STATE_FILE
    path.parent.mkdir(parents=True, exist_ok=True)
    content = (
        '{"version": 99, "last_full_scan": null, "last_poll": null, "prs": {}}'
    )
    path.write_text(content)

    assert env.run(FakeRunner()) == 1

    assert path.read_text() == content


def test_scan_http_error_keeps_state(env: Env) -> None:
    env.seed({f"{REPO}#{PR_ID}": env.module.PrEntry(HEAD_ONE, HEAD_ONE, 0)})
    path = Path(env.module.CACHE_DIR) / STATE_FILE
    before = path.read_text()

    def failing_pages(_url: str) -> list[dict[str, Any]]:
        raise http_error(500)

    env.use_real_scan_repo(failing_pages)
    runner = FakeRunner()

    assert env.run(runner) == 1

    assert path.read_text() == before
    assert runner.calls == []


def test_no_access_repo_keeps_state_entries(env: Env) -> None:
    env.seed({f"{REPO}#{PR_ID}": env.module.PrEntry(HEAD_ONE, HEAD_ONE, 0)})

    def forbidden_pages(_url: str) -> list[dict[str, Any]]:
        raise http_error(403)

    env.use_real_scan_repo(forbidden_pages)
    runner = FakeRunner()

    assert env.run(runner) == 0

    assert env.entry()["reviewed_head"] == HEAD_ONE
    assert runner.claude_calls == []


def test_timeout_abandons_head(env: Env) -> None:
    env.prs = [make_pr()]
    runner = FakeRunner()
    runner.claude_times_out = True

    assert env.run(runner) == 0
    assert env.run(runner) == 0

    assert len(runner.claude_calls) == 1
    assert env.entry()["failures"] == MAX_FAILURES
    assert env.entry()["reviewed_head"] == ""
    assert len(runner.notify_calls) == 1
    assert "porzucone" in runner.notify_calls[0][2]
    assert not (Path(env.module.CACHE_DIR) / "poll-reports").exists()


def test_review_writes_no_report_files(
    env: Env, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setattr(env.module, "MAX_PARALLEL_REVIEWS", 1)
    env.prs = [
        make_pr(pr_id=1, updated_on="2026-10-22T09:01:00+00:00"),
        make_pr(pr_id=2, updated_on="2026-10-22T09:02:00+00:00"),
    ]
    runner = FakeRunner()
    runner.claude_hook = lambda argv: setattr(
        runner, "claude_rc", 1 if f"{REPO}#2 " in argv[2] else 0
    )

    assert env.run(runner) == 0

    cache = Path(env.module.CACHE_DIR)
    assert not (cache / "poll-reports").exists()
    assert list(cache.rglob("*.md")) == []
    assert len(runner.notify_calls) == 2
    assert all("raport" not in call[2] for call in runner.notify_calls)


def test_review_output_not_captured(env: Env) -> None:
    env.prs = [make_pr()]
    runner = FakeRunner()

    env.run(runner)

    assert not runner.claude_kwargs[0].get("capture_output")


def test_failure_counted_before_review_runs(env: Env) -> None:
    env.prs = [make_pr()]
    runner = FakeRunner()
    runner.observe = lambda: env.entry()["failures"]

    assert env.run(runner) == 0

    assert runner.observed == [1]
    assert env.entry()["failures"] == 0


def test_all_candidates_reviewed_in_one_run(env: Env) -> None:
    env.prs = [
        make_pr(pr_id=5, updated_on="2026-10-22T09:05:00+00:00"),
        make_pr(pr_id=3, updated_on="2026-10-22T09:03:00+00:00"),
        make_pr(pr_id=1, updated_on="2026-10-22T09:01:00+00:00"),
        make_pr(pr_id=4, updated_on="2026-10-22T09:04:00+00:00"),
        make_pr(pr_id=2, updated_on="2026-10-22T09:02:00+00:00"),
    ]
    runner = FakeRunner()

    assert env.run(runner) == 0

    prompts = [call[2] for call in runner.claude_calls]
    assert len(prompts) == 5
    assert reviewed_ids(runner) == {1, 2, 3, 4, 5}


def reviewed_ids(runner: FakeRunner) -> set[int]:
    return {
        pr_id
        for pr_id in range(1, 10)
        for call in runner.claude_calls
        if f"{REPO}#{pr_id} " in call[2]
    }


def pr_id_of(argv: list[str]) -> int:
    return next(
        pr_id for pr_id in range(1, 10) if f"{REPO}#{pr_id} " in argv[2]
    )


class Overlap:
    def __init__(self, parties: int, *, limit: int | None = None) -> None:
        self.barrier = threading.Barrier(parties, timeout=BARRIER_TIMEOUT_S)
        self.limit = parties if limit is None else limit
        self.lock = threading.Lock()
        self.started = 0
        self.active = 0
        self.peak = 0
        self.broken = 0

    def __call__(self, _argv: list[str]) -> None:
        with self.lock:
            index = self.started
            self.started += 1
            self.active += 1
            self.peak = max(self.peak, self.active)
        try:
            if index < self.limit:
                self.barrier.wait()
        except threading.BrokenBarrierError:
            with self.lock:
                self.broken += 1
        finally:
            with self.lock:
                self.active -= 1


def five_prs() -> list[dict[str, Any]]:
    return [
        make_pr(pr_id=i, updated_on=f"2026-10-22T09:0{i}:00+00:00")
        for i in range(1, 6)
    ]


def test_reviews_run_three_at_a_time(env: Env) -> None:
    env.prs = five_prs()
    runner = FakeRunner()
    overlap = Overlap(3)
    runner.claude_hook = overlap

    assert env.run(runner) == 0

    assert overlap.peak == 3
    assert reviewed_ids(runner) == {1, 2, 3, 4, 5}


def test_claude_called_with_effort_medium(env: Env) -> None:
    env.prs = [make_pr()]
    runner = FakeRunner()

    env.run(runner)

    argv = runner.claude_calls[0]
    assert "--effort" in argv
    assert argv[argv.index("--effort") + 1] == "medium"
    assert argv[argv.index("--model") + 1] == "opus"


def test_reviews_submitted_oldest_first(
    env: Env, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setattr(env.module, "MAX_PARALLEL_REVIEWS", 1)
    env.prs = [
        make_pr(pr_id=i, updated_on=f"2026-10-22T09:0{i}:00+00:00")
        for i in (4, 2, 5, 1, 3)
    ]
    runner = FakeRunner()

    env.run(runner)

    order = [pr_id_of(call) for call in runner.claude_calls]
    assert order == [1, 2, 3, 4, 5]


def test_personal_mode_exits(
    env: Env, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setenv("CLAUDE_MODE", "personal")
    env.prs = [make_pr()]
    runner = FakeRunner()

    assert env.run(runner) == 0

    assert env.api_calls == 0
    assert runner.calls == []


def test_missing_notify_send_does_not_fail(env: Env) -> None:
    env.prs = [make_pr()]
    runner = FakeRunner()
    runner.notify_missing = True

    assert env.run(runner) == 0

    assert env.entry()["reviewed_head"] == HEAD_ONE


def test_sets_socket_timeout(
    env: Env, monkeypatch: pytest.MonkeyPatch
) -> None:
    timeouts: list[float | None] = []
    monkeypatch.setattr(socket, "setdefaulttimeout", timeouts.append)
    env.prs = []

    assert env.run(FakeRunner()) == 0

    assert timeouts == [60]


def test_push_clearing_vote_is_recheck(env: Env) -> None:
    env.seed({f"{REPO}#{PR_ID}": env.module.PrEntry(HEAD_ONE, HEAD_ONE, 0)})
    env.prs = [make_pr(HEAD_TWO)]
    runner = FakeRunner()

    assert env.run(runner) == 0

    assert len(runner.claude_calls) == 1
    assert "Nowy push po moim głosie" in runner.claude_calls[0][2]


def test_last_poll_is_scan_start(env: Env) -> None:
    env.prs = [make_pr()]
    clock = Clock(step=timedelta(minutes=7))

    assert env.run(FakeRunner(), clock=clock) == 0

    state = json.loads((Path(env.module.CACHE_DIR) / STATE_FILE).read_text())
    assert state["last_poll"] == "2026-10-22T12:00:00+00:00"


def test_unreviewed_entry_baselined_once_voted(env: Env) -> None:
    pending = env.module.PrEntry(HEAD_ONE, "", 1)

    entry, kind = env.module.decide(pending, HEAD_ONE, voted=True)

    assert entry == env.module.PrEntry(HEAD_ONE, HEAD_ONE, 1)
    assert kind is None


def test_failed_first_review_then_manual_vote_then_push_rechecked(
    env: Env,
) -> None:
    env.prs = [make_pr(HEAD_ONE)]
    env.run(FakeRunner(claude_rc=1))
    env.prs = [make_pr(HEAD_ONE, my_vote="approved")]
    env.run(FakeRunner())
    env.prs = [make_pr(HEAD_TWO)]
    runner = FakeRunner()

    assert env.run(runner) == 0

    assert len(runner.claude_calls) == 1
    assert "Nowy push po moim głosie" in runner.claude_calls[0][2]


def test_repos_to_scan_adds_repos_with_pending_reviews(env: Env) -> None:
    pending = env.module.PrEntry(HEAD_ONE, "", 1)
    reviewed = env.module.PrEntry(HEAD_ONE, HEAD_ONE, 0)
    abandoned = env.module.PrEntry(HEAD_ONE, "", MAX_FAILURES)
    state = env.module.PollState(
        "2026-10-22T11:30:00+00:00",
        "2026-10-22T11:50:00+00:00",
        {
            "zeta#1": pending,
            "alpha#2": pending,
            "alpha#3": pending,
            "reviewed#4": reviewed,
            "abandoned#5": abandoned,
        },
    )
    env.monkeypatch.setattr(
        env.module, "pages", lambda _url: [{"slug": "beta"}]
    )

    repos, full = env.module.repos_to_scan(state, NOW, full=False)

    assert repos == ["alpha", "beta", "zeta"]
    assert not full


def test_failed_review_retried_by_next_incremental_run(env: Env) -> None:
    env.prs = [make_pr()]
    env.run(FakeRunner(claude_rc=1))
    env.monkeypatch.setattr(env.module, "pages", lambda _url: [])
    runner = FakeRunner()

    assert env.run(runner, full=False) == 0

    assert len(runner.claude_calls) == 1
    assert f"{REPO}#{PR_ID} " in runner.claude_calls[0][2]


def test_uuid_cached_after_first_run(env: Env) -> None:
    env.prs = []
    env.run(FakeRunner())
    env.run(FakeRunner())

    assert env.api_calls == 1


def test_state_without_uuid_key_still_loads(env: Env) -> None:
    path = Path(env.module.CACHE_DIR) / STATE_FILE
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(
        '{"version": 1, "last_full_scan": null, "last_poll": null, '
        '"prs": {"a#1": {"head": "h", "reviewed_head": "h", "failures": 0}}}'
    )

    state = env.module.read_state()

    assert state.my_uuid is None
    assert state.prs == {"a#1": env.module.PrEntry("h", "h", 0)}


def overlapping_with(
    overlap: Overlap, errors: dict[int, Exception]
) -> Callable[[list[str]], None]:
    def hook(argv: list[str]) -> None:
        overlap(argv)
        error = errors.get(pr_id_of(argv))
        if error is not None:
            raise error

    return hook


def test_parallel_reviews_same_repo_both_recorded(env: Env) -> None:
    env.prs = [
        make_pr(HEAD_ONE, pr_id=1, updated_on="2026-10-22T09:01:00+00:00"),
        make_pr(HEAD_TWO, pr_id=2, updated_on="2026-10-22T09:02:00+00:00"),
    ]
    runner = FakeRunner()
    overlap = Overlap(2)
    runner.claude_hook = overlap

    assert env.run(runner) == 0

    assert overlap.peak == 2
    assert overlap.broken == 0
    first = env.entry(f"{REPO}#1")
    second = env.entry(f"{REPO}#2")
    assert (first["reviewed_head"], first["failures"]) == (HEAD_ONE, 0)
    assert (second["reviewed_head"], second["failures"]) == (HEAD_TWO, 0)


def test_review_exception_does_not_lose_other_results(env: Env) -> None:
    env.prs = [
        make_pr(pr_id=i, updated_on=f"2026-10-22T09:0{i}:00+00:00")
        for i in (1, 2, 3)
    ]
    runner = FakeRunner()
    overlap = Overlap(3)
    runner.claude_hook = overlapping_with(overlap, {2: FileNotFoundError()})

    with pytest.raises(FileNotFoundError):
        env.run(runner)

    assert env.entry(f"{REPO}#1")["reviewed_head"] == HEAD_ONE
    assert env.entry(f"{REPO}#3")["reviewed_head"] == HEAD_ONE
    assert env.entry(f"{REPO}#2")["reviewed_head"] == ""


def test_timeout_does_not_block_parallel_review(env: Env) -> None:
    env.prs = [
        make_pr(pr_id=i, updated_on=f"2026-10-22T09:0{i}:00+00:00")
        for i in (1, 2)
    ]
    runner = FakeRunner()
    overlap = Overlap(2)
    timeout = subprocess.TimeoutExpired([CLAUDE], 1)
    runner.claude_hook = overlapping_with(overlap, {1: timeout})

    assert env.run(runner) == 0

    timed_out = env.entry(f"{REPO}#1")
    reviewed = env.entry(f"{REPO}#2")
    assert timed_out["failures"] == MAX_FAILURES
    assert timed_out["reviewed_head"] == ""
    assert reviewed["reviewed_head"] == HEAD_ONE
    assert reviewed["failures"] == 0


def test_concurrent_state_writes_consistent(env: Env) -> None:
    env.prs = [
        make_pr(pr_id=i, updated_on=f"2026-10-22T09:0{i}:00+00:00")
        for i in (1, 2, 3)
    ]
    runner = FakeRunner(claude_rc=1)
    runner.claude_hook = Overlap(3)

    assert env.run(runner) == 0

    keys = [f"{REPO}#{i}" for i in (1, 2, 3)]
    assert [env.entry(key)["failures"] for key in keys] == [1, 1, 1]

    for expected in (2, MAX_FAILURES):
        again = FakeRunner(claude_rc=1)
        env.run(again)
        assert [env.entry(key)["failures"] for key in keys] == [expected] * 3

    last = FakeRunner(claude_rc=1)
    env.run(last)
    assert last.claude_calls == []
