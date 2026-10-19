import contextlib
import os
import shutil
import stat
import subprocess
import tempfile
from collections.abc import Iterator, Mapping, Sequence
from pathlib import Path
from typing import NamedTuple

from agy_errors import AgyUnavailableError, fail

TEXT_ENCODING = "utf-8"
DECODE_ERRORS = "replace"
WORK_DIR_ENV = "AGY_WORK_DIR"
DEFAULT_WORK_PARTS = (".cache", "agy-worker", "work")
GIT_TIMEOUT_SECONDS = 120
GIT_INDEX_FILE_ENV = "GIT_INDEX_FILE"
GIT_IDENTITY_ENV = {
    "GIT_AUTHOR_NAME": "agy-worker",
    "GIT_AUTHOR_EMAIL": "agy-worker@localhost",
    "GIT_COMMITTER_NAME": "agy-worker",
    "GIT_COMMITTER_EMAIL": "agy-worker@localhost",
}
GIT_SAFE_CONFIG = (
    "-c",
    f"core.hooksPath={os.devnull}",
    "-c",
    "core.fsmonitor=false",
    "-c",
    "commit.gpgsign=false",
)
WORKSPACE_GIT_CONFIG = (
    *GIT_SAFE_CONFIG,
    "-c",
    f"core.excludesFile={os.devnull}",
)
SNAPSHOT_MESSAGE = "agy-snapshot"
INITIAL_MESSAGE = "agy-workspace"
INDEX_NAME = "snapshot.index"
BLOB_NAME = "attachment.blob"
ATTACHMENT_MODE = "100644"
DIFF_ARGUMENTS = ("diff", "--no-color", "--no-ext-diff", "--end-of-options")
WORKTREE_NAME = "wt"
WORKSPACE_NAME = "ws"
GIT_DIR_NAME = "gitdir"
WORKTREES_DIR = "worktrees"
SCRATCH_PREFIX = "agy-"
PORCELAIN_PATH_OFFSET = 3


class Workspace(NamedTuple):
    """A disposable directory and the git directory that tracks it."""

    path: Path
    git_dir: Path


def run_tool(arguments: Sequence[str], env: Mapping[str, str]) -> str:
    """Run a helper program and return its stdout."""
    name = arguments[0]
    try:
        done = subprocess.run(
            arguments,
            capture_output=True,
            check=False,
            encoding=TEXT_ENCODING,
            errors=DECODE_ERRORS,
            timeout=GIT_TIMEOUT_SECONDS,
            env={**os.environ, **env},
        )
    except (OSError, subprocess.TimeoutExpired) as error:
        fail(f"{name} could not run: {error}")
    if done.returncode:
        fail(f"{name} failed: {done.stderr.strip()}")
    return done.stdout


def run_git(
    root: Path, args: Sequence[str], env: Mapping[str, str] | None = None
) -> str:
    """Run git in a directory and return its stdout."""
    command = ["git", "-C", str(root), *GIT_SAFE_CONFIG, *args]
    return run_tool(command, {**GIT_IDENTITY_ENV, **(env or {})})


def run_git_in(workspace: Workspace, args: Sequence[str]) -> str:
    """Run git against a workspace through its trusted git directory."""
    command = [
        "git",
        "--git-dir",
        str(workspace.git_dir),
        "--work-tree",
        str(workspace.path),
        *WORKSPACE_GIT_CONFIG,
        *args,
    ]
    return run_tool(command, GIT_IDENTITY_ENV)


def path_from_env(env_name: str, default: Path) -> Path:
    """Return the path an environment variable names, else the default."""
    configured = os.environ.get(env_name)
    return Path(configured).expanduser() if configured else default


def work_base() -> Path:
    """Return the directory that holds the disposable workspaces."""
    default = Path.home().joinpath(*DEFAULT_WORK_PARTS)
    return path_from_env(WORK_DIR_ENV, default)


def unlock_tree(path: Path) -> None:
    """Make every real directory of a tree accessible to its owner."""
    if path.is_symlink():
        return
    with contextlib.suppress(OSError):
        path.chmod(stat.S_IRWXU)
    for root, dirs, _ in os.walk(path):
        for name in dirs:
            child = Path(root, name)
            if not child.is_symlink():
                with contextlib.suppress(OSError):
                    child.chmod(stat.S_IRWXU)


def remove_tree(path: Path) -> None:
    """Delete a tree the sandboxed agent could write to."""
    unlock_tree(path)
    shutil.rmtree(path, ignore_errors=True)


@contextlib.contextmanager
def scratch_dir() -> Iterator[Path]:
    """Create a private temporary directory and remove it afterwards."""
    base = work_base()
    base.mkdir(parents=True, exist_ok=True)
    path = Path(tempfile.mkdtemp(prefix=SCRATCH_PREFIX, dir=base)).resolve()
    try:
        yield path
    finally:
        remove_tree(path)


def create_workspace(scratch: Path) -> Workspace:
    """Create an empty workspace whose git directory lies outside it."""
    path = scratch / WORKSPACE_NAME
    git_dir = scratch / GIT_DIR_NAME
    path.mkdir()
    command = [
        "git",
        *WORKSPACE_GIT_CONFIG,
        "init",
        "-q",
        "--separate-git-dir",
        str(git_dir),
        str(path),
    ]
    run_tool(command, GIT_IDENTITY_ENV)
    return Workspace(path, git_dir)


def commit_workspace(workspace: Workspace) -> None:
    """Commit every file currently in the workspace."""
    run_git_in(workspace, ["add", "-A"])
    run_git_in(
        workspace, ["commit", "-q", "--allow-empty", "-m", INITIAL_MESSAGE]
    )


def dirty_paths(workspace: Workspace) -> list[str]:
    """List files that differ from the workspace commit, ignored included."""
    unlock_tree(workspace.path)
    status = run_git_in(
        workspace,
        ["status", "--porcelain", "--untracked-files=all", "--ignored"],
    )
    return [line[PORCELAIN_PATH_OFFSET:] for line in status.splitlines()]


def resolve_repo_root(project_path: str) -> Path:
    """Return the top level of the git repository at project_path."""
    if not project_path.strip():
        fail("project_path is empty")
    path = Path(project_path).expanduser().resolve()
    if not path.is_dir():
        fail(f"project_path {path} is not a directory")
    return Path(run_git(path, ["rev-parse", "--show-toplevel"]).strip())


def add_attachment(
    root: Path, index_file: Path, path: str, content: bytes
) -> None:
    """Add a file to the temporary index unless the path is taken."""
    index_env = {GIT_INDEX_FILE_ENV: str(index_file)}
    if run_git(root, ["ls-files", "--", path], index_env).strip():
        fail(f"attachment path {path} already exists in the repository")
    blob_file = index_file.with_name(BLOB_NAME)
    blob_file.write_bytes(content)
    blob = run_git(
        root, ["hash-object", "-w", "--no-filters", "--", str(blob_file)]
    ).strip()
    entry = f"{ATTACHMENT_MODE},{blob},{path}"
    run_git(root, ["update-index", "--add", "--cacheinfo", entry], index_env)


def seed_index(root: Path, index_file: Path, head: str) -> None:
    """Start the temporary index from the real index, else from HEAD."""
    real_index = Path(
        run_git(
            root,
            ["rev-parse", "--path-format=absolute", "--git-path", "index"],
        ).strip()
    )
    if real_index.is_file():
        shutil.copyfile(real_index, index_file)
        return
    run_git(root, ["read-tree", head], {GIT_INDEX_FILE_ENV: str(index_file)})


def snapshot_commit(
    root: Path,
    index_file: Path,
    extra_files: Mapping[str, bytes] | None = None,
) -> str:
    """Commit the whole working tree without touching refs or the index."""
    try:
        head = run_git(root, ["rev-parse", "--verify", "HEAD"]).strip()
    except AgyUnavailableError:
        fail("the repository has no commits yet, nothing to review")
    index_env = {GIT_INDEX_FILE_ENV: str(index_file)}
    seed_index(root, index_file, head)
    run_git(root, ["add", "-A"], index_env)
    for path, content in (extra_files or {}).items():
        add_attachment(root, index_file, path, content)
    tree = run_git(root, ["write-tree"], index_env).strip()
    return run_git(
        root, ["commit-tree", tree, "-p", head, "-m", SNAPSHOT_MESSAGE]
    ).strip()


def build_diff(root: Path, base: str) -> str:
    """Diff the working tree against a ref, untracked files included."""
    with scratch_dir() as scratch:
        commit = snapshot_commit(root, scratch / INDEX_NAME)
        return run_git(root, [*DIFF_ARGUMENTS, base, commit])


def is_worktree_admin_dir(root: Path, candidate: Path) -> bool:
    """Tell whether a directory is a worktree entry of the repository."""
    try:
        common = run_git(
            root, ["rev-parse", "--path-format=absolute", "--git-common-dir"]
        )
    except AgyUnavailableError:
        return False
    worktrees = Path(common.strip()).resolve() / WORKTREES_DIR
    return candidate.resolve().parent == worktrees


def drop_worktree(
    root: Path, workspace: Path, admin_dir: Path | None = None
) -> None:
    """Remove a worktree without touching any other registration."""
    try:
        run_git(root, ["worktree", "remove", "--force", str(workspace)])
    except AgyUnavailableError:
        remove_tree(workspace)
        if admin_dir is not None and is_worktree_admin_dir(root, admin_dir):
            shutil.rmtree(admin_dir, ignore_errors=True)


@contextlib.contextmanager
def snapshot_workspace(
    root: Path, extra_files: Mapping[str, bytes] | None = None
) -> Iterator[Workspace]:
    """Check out a snapshot of the working tree into a disposable worktree."""
    with scratch_dir() as scratch:
        commit = snapshot_commit(root, scratch / INDEX_NAME, extra_files)
        path = scratch / WORKTREE_NAME
        admin_dir: Path | None = None
        try:
            run_git(root, ["worktree", "add", "--detach", str(path), commit])
            git_dir = run_git(path, ["rev-parse", "--absolute-git-dir"])
            admin_dir = Path(git_dir.strip())
            yield Workspace(path, admin_dir)
        finally:
            drop_worktree(root, path, admin_dir)


@contextlib.contextmanager
def empty_workspace() -> Iterator[Workspace]:
    """Provide a disposable git workspace without files."""
    with scratch_dir() as scratch:
        workspace = create_workspace(scratch)
        commit_workspace(workspace)
        yield workspace
