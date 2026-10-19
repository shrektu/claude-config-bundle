from collections.abc import Mapping, Sequence
from pathlib import Path

import agy_workspace
import pytest
from agy_errors import AgyUnavailableError
from helpers_test import (
    IGNORED_FILE,
    ORIGIN_URL,
    FakeAgy,
    force_add_ignored_file,
    git,
    git_output,
    plan_review,
    repo_state,
)


def test_user_repo_untouched_after_review(
    fake_agy: FakeAgy, allowlisted_repo: Path
) -> None:
    (allowlisted_repo / "tracked.txt").write_text("edited\n")
    (allowlisted_repo / "staged.txt").write_text("new\n")
    git(allowlisted_repo, "add", "staged.txt")
    (allowlisted_repo / "untracked.txt").write_text("loose\n")
    before = repo_state(allowlisted_repo)

    result = plan_review(allowlisted_repo)

    assert result.startswith("Gemini review completed")
    assert repo_state(allowlisted_repo) == before
    assert list(fake_agy.work_dir.iterdir()) == []


def test_snapshot_includes_uncommitted_and_untracked_excludes_ignored(
    fake_agy: FakeAgy, allowlisted_repo: Path
) -> None:
    (allowlisted_repo / ".gitignore").write_text("ignored.log\n")
    git(allowlisted_repo, "add", ".gitignore")
    git(allowlisted_repo, "commit", "-q", "-m", "ignore")
    (allowlisted_repo / "tracked.txt").write_text("edited\n")
    (allowlisted_repo / "staged.txt").write_text("staged\n")
    git(allowlisted_repo, "add", "staged.txt")
    (allowlisted_repo / "untracked.txt").write_text("loose\n")
    (allowlisted_repo / "ignored.log").write_text("noise\n")

    result = plan_review(allowlisted_repo)

    files = fake_agy.invocation().files
    assert result.startswith("Gemini review completed")
    assert {name: files[name] for name in files if name != ".git"} == {
        ".gitignore": "ignored.log\n",
        "tracked.txt": "edited\n",
        "staged.txt": "staged\n",
        "untracked.txt": "loose\n",
    }


def test_repo_without_commits_unavailable(
    fake_agy: FakeAgy, tmp_path: Path
) -> None:
    repo = tmp_path / "fresh"
    repo.mkdir()
    git(repo, "init", "-q")
    git(repo, "remote", "add", "origin", ORIGIN_URL)

    result = plan_review(repo)

    assert result.startswith("AGY-UNAVAILABLE: ")
    assert "no commits" in result
    assert not fake_agy.ran()


def test_workspace_write_reports_modified_and_removes_worktree(
    fake_agy: FakeAgy,
    allowlisted_repo: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setenv("AGY_FAKE_MODE", "write")
    worktrees_before = git_output(allowlisted_repo, "worktree", "list")

    result = plan_review(allowlisted_repo)

    assert result.startswith("AGY-UNAVAILABLE: ")
    assert "workspace modified" in result
    assert "evil.txt" in result
    assert "REVIEW BODY" in result
    assert list(fake_agy.work_dir.iterdir()) == []
    assert git_output(allowlisted_repo, "worktree", "list") == worktrees_before


def test_unrelated_missing_worktree_stays_registered(
    fake_agy: FakeAgy, allowlisted_repo: Path, tmp_path: Path
) -> None:
    other = tmp_path / "other"
    git(allowlisted_repo, "worktree", "add", "--detach", str(other))
    other.rename(tmp_path / "other-moved")

    result = plan_review(allowlisted_repo)

    registered = git_output(
        allowlisted_repo, "worktree", "list", "--porcelain"
    )
    assert result.startswith("Gemini review completed")
    assert f"worktree {other}" in registered
    assert list(fake_agy.work_dir.iterdir()) == []


def test_drop_worktree_fallback_removes_only_its_own_directories(
    allowlisted_repo: Path, tmp_path: Path
) -> None:
    mine, other = tmp_path / "mine", tmp_path / "other"
    git(allowlisted_repo, "worktree", "add", "--detach", str(mine))
    git(allowlisted_repo, "worktree", "add", "--detach", str(other))
    git(allowlisted_repo, "worktree", "lock", str(mine))
    other.rename(tmp_path / "other-moved")
    mine_admin = allowlisted_repo / ".git" / "worktrees" / "mine"
    other_admin = allowlisted_repo / ".git" / "worktrees" / "other"

    agy_workspace.drop_worktree(allowlisted_repo, mine, mine_admin)

    registered = git_output(
        allowlisted_repo, "worktree", "list", "--porcelain"
    )
    assert not mine.exists()
    assert not mine_admin.exists()
    assert other_admin.exists()
    assert f"worktree {other}" in registered
    assert f"worktree {mine}" not in registered


def test_workspace_git_calls_ignore_global_excludes_unit(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    seen: list[list[str]] = []

    def record(arguments: Sequence[str], _env: Mapping[str, str]) -> str:
        seen.append(list(arguments))
        return ""

    monkeypatch.setattr(agy_workspace, "run_tool", record)
    workspace = agy_workspace.Workspace(tmp_path / "ws", tmp_path / "gitdir")

    (tmp_path / "scratch").mkdir()

    agy_workspace.run_git_in(workspace, ["status"])
    agy_workspace.create_workspace(tmp_path / "scratch")

    assert len(seen) == 2
    for command in seen:
        assert "core.excludesFile=/dev/null" in command


def test_remove_tree_deletes_locked_directories_unit(tmp_path: Path) -> None:
    tree = tmp_path / "tree"
    locked = tree / "a" / "locked"
    read_only = tree / "ro"
    (locked / "deep").mkdir(parents=True)
    (locked / "deep" / "f.txt").write_text("x")
    read_only.mkdir()
    (read_only / "g.txt").write_text("y")
    locked.chmod(0)
    read_only.chmod(0o500)

    agy_workspace.remove_tree(tree)

    assert not tree.exists()


def test_remove_tree_never_touches_symlink_targets_unit(
    tmp_path: Path,
) -> None:
    outside = tmp_path / "outside"
    outside.mkdir()
    (outside / "keep.txt").write_text("keep")
    outside.chmod(0o555)
    tree = tmp_path / "tree"
    tree.mkdir()
    (tree / "link").symlink_to(outside, target_is_directory=True)
    (tree / "file-link").symlink_to(outside / "keep.txt")

    agy_workspace.remove_tree(tree)

    assert not tree.exists()
    assert (outside / "keep.txt").read_text() == "keep"
    assert outside.stat().st_mode & 0o777 == 0o555
    outside.chmod(0o755)


def test_locked_directories_do_not_survive_the_tool_call(
    fake_agy: FakeAgy,
    allowlisted_repo: Path,
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    home = tmp_path / "home"
    (home / ".gemini").mkdir(parents=True)
    monkeypatch.setenv("HOME", str(home))
    monkeypatch.setenv("AGY_FAKE_MODE", "locked")
    monkeypatch.setenv("AGY_BWRAP", "/usr/bin/bwrap")

    result = plan_review(allowlisted_repo)

    assert result.startswith("AGY-UNAVAILABLE: ")
    assert list(fake_agy.work_dir.iterdir()) == []
    assert list((home / ".gemini").iterdir()) == []


def test_drop_worktree_never_deletes_main_git_dir(
    allowlisted_repo: Path, tmp_path: Path
) -> None:
    mine = tmp_path / "mine"
    git(allowlisted_repo, "worktree", "add", "--detach", str(mine))
    git(allowlisted_repo, "worktree", "lock", str(mine))
    main_git_dir = allowlisted_repo / ".git"

    agy_workspace.drop_worktree(allowlisted_repo, mine, main_git_dir)

    assert main_git_dir.exists()
    assert git_output(allowlisted_repo, "rev-parse", "HEAD")
    assert not mine.exists()


def test_snapshot_cleanup_never_deletes_main_git_dir(
    fake_agy: FakeAgy,
    allowlisted_repo: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    real_run_git = agy_workspace.run_git
    main_git_dir = allowlisted_repo / ".git"

    def hostile_run_git(
        root: Path,
        args: Sequence[str],
        env: Mapping[str, str] | None = None,
    ) -> str:
        if "--absolute-git-dir" in args:
            return f"{main_git_dir}\n"
        if args[:2] == ["worktree", "remove"]:
            message = "refused"
            raise AgyUnavailableError(message)
        return real_run_git(root, args, env)

    monkeypatch.setattr(agy_workspace, "run_git", hostile_run_git)

    plan_review(allowlisted_repo)

    assert fake_agy.ran()
    assert main_git_dir.exists()
    assert git_output(allowlisted_repo, "rev-parse", "HEAD")


@pytest.mark.usefixtures("fake_agy")
def test_snapshot_extra_files_committed_and_clean(
    allowlisted_repo: Path,
) -> None:
    before = repo_state(allowlisted_repo)

    with agy_workspace.snapshot_workspace(
        allowlisted_repo, {".agy/note.txt": b"attached\n"}
    ) as workspace:
        attached = workspace.path / ".agy" / "note.txt"
        content = attached.read_bytes() if attached.exists() else None
        dirty = agy_workspace.dirty_paths(workspace)

    assert content == b"attached\n"
    assert dirty == []
    assert repo_state(allowlisted_repo) == before


def test_snapshot_includes_force_added_ignored_file(
    allowlisted_repo: Path, tmp_path: Path
) -> None:
    index_before = force_add_ignored_file(allowlisted_repo)

    commit = agy_workspace.snapshot_commit(
        allowlisted_repo, tmp_path / "snapshot.index"
    )

    files = git_output(
        allowlisted_repo, "ls-tree", "-r", "--name-only", commit
    ).split()
    assert IGNORED_FILE in files
    assert (allowlisted_repo / ".git" / "index").read_bytes() == index_before


@pytest.mark.usefixtures("fake_agy")
def test_snapshot_extra_file_collision_unavailable(
    allowlisted_repo: Path,
) -> None:
    (allowlisted_repo / ".agy").mkdir()
    (allowlisted_repo / ".agy" / "note.txt").write_text("mine\n")

    with (
        pytest.raises(AgyUnavailableError, match="already exists"),
        agy_workspace.snapshot_workspace(
            allowlisted_repo, {".agy/note.txt": b"attached\n"}
        ),
    ):
        pass
